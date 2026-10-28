"""审计编排：单 URL 检测 与 报表联合诊断。"""
import asyncio
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from . import config, robots as robots_mod
from .fetcher import fetch_url
from .html_extract import extract
from .rules import AdContext, Finding, run_rules
from .scorer import compute_priority, score

# 词集合相似度用的分词（中英文均取 2 字以上的词）
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")
# 站内抽样最多抓几个同域页面（控制抓取量与耗时）
_SIMILARITY_SAMPLE_MAX = 3


def finding_to_dict(f: Finding) -> dict:
    return {
        "rule_id": f.rule_id,
        "title": f.title,
        "basis_type": f.basis_type,
        "basis_label": f.basis_label,
        "dimension": f.dimension,
        "device": f.device,
        "severity": f.severity,
        "status": f.status,
        "method": f.method,
        "evidence": f.evidence,
        "recommendation": f.recommendation,
        "confidence": f.confidence,
        "version": f.version,
        "owner": f.owner,
    }


def _page_summary(p) -> dict:
    return {
        "title": p.title,
        "h1": p.h1_list[:5],
        "meta_description": p.meta_description,
        "canonical": p.canonical,
        "viewport": p.viewport,
        "html_lang": p.html_lang,
        "images_total": p.images_total,
        "images_missing_alt": p.images_missing_alt,
        "images_with_alt": p.images_with_alt,
        "forms": p.forms,
        "form_has_submit": p.form_has_submit,
        "form_inputs": p.form_inputs,
        "links_total": p.links_total,
        "links_internal": p.links_internal,
        "links_external": p.links_external,
        "cta_sample": p.cta_buttons[:8],
        "word_count": p.word_count,
        "text_length": p.text_length,
        "phones": p.phones[:5],
        "emails": p.emails[:5],
        "certs": p.certs,
        "specs": p.specs[:8],
        "page_bytes": p.page_bytes,
        "render_blocking": p.render_blocking_scripts + p.render_blocking_stylesheets,
        "has_media_queries": p.has_media_queries,
        "x_robots_tag": p.x_robots_tag,
        "robots_disallow": p.robots_disallow,
        "extreme_claims": p.extreme_claims[:8],
        "site_similarity": p.site_similarity,
        "site_similarity_sample": p.site_similarity_sample,
    }


def _text_similarity(a: str, b: str) -> float:
    """词集合 Jaccard 相似度（0~1）。含导航页脚等共用文本，只能当估算信号。"""
    ta = set(_WORD_RE.findall((a or "").lower()))
    tb = set(_WORD_RE.findall((b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


async def _check_robots(client, p, final_url: str) -> None:
    """填充 p.robots_disallow。失败静默置 None，不影响主流程。"""
    host = urlparse(final_url).hostname or ""
    if not host:
        return
    try:
        txt = await robots_mod.get_robots(client, host)
        path = robots_mod.path_of(final_url)
        # 广告抓取优先看 AdsBot，没有专门规则再回退到 *
        verdict = robots_mod.disallows(txt, path, agent="AdsBot")
        if verdict is None:
            verdict = robots_mod.disallows(txt, path, agent="*")
        p.robots_disallow = verdict
    except Exception:  # noqa: BLE001
        p.robots_disallow = None


async def _sample_similarity(client, p, final_url: str):
    """站内抽样相似度：抓最多 N 个同域内页，取最高相似度。

    跨站/全网重复无法这样检测，所以结果只作为「疑似套壳」的估算信号。
    """
    links = [l for l in p.internal_links if l != final_url][:_SIMILARITY_SAMPLE_MAX]
    if not links:
        return None, 0
    best, n = 0.0, 0
    for link in links:
        try:
            fr = await fetch_url(link, client)
        except Exception:  # noqa: BLE001
            continue
        if not fr.ok or not fr.content:
            continue
        try:
            other = extract(link, fr.final_url or link, fr.status_code, fr.content, headers=fr.headers)
        except Exception:  # noqa: BLE001
            continue
        if not other.text:
            continue
        n += 1
        best = max(best, _text_similarity(p.text, other.text))
    return (best if n else None), n


async def _analyze_page_async(url: str, ad: Optional[AdContext], client, deep: bool) -> dict:
    fr = await fetch_url(url, client)
    p = extract(url, fr.final_url or url, fr.status_code, fr.content, fr.error, fr.error_type,
                headers=fr.headers)
    if fr.ok:
        await _check_robots(client, p, fr.final_url or url)
        if deep:
            p.site_similarity, p.site_similarity_sample = await _sample_similarity(client, p, fr.final_url or url)
    findings = run_rules(p, ad)
    sc = score(findings)
    prio = compute_priority(findings)  # 无广告指标时的页面优先级
    return {
        "url": url,
        "final_url": fr.final_url,
        "fetch": {
            "ok": fr.ok, "status_code": fr.status_code, "error": fr.error,
            "error_type": fr.error_type, "redirect_chain": fr.redirect_chain,
            "elapsed_ms": fr.elapsed_ms,
        },
        "page_summary": _page_summary(p) if (fr.ok or fr.content) else None,
        "score": sc,
        "findings": [finding_to_dict(f) for f in findings],
        "priority": prio,
    }


def analyze_page(url: str, ad: Optional[AdContext] = None, client: Optional[httpx.AsyncClient] = None,
                 deep: bool = False) -> dict:
    """抓取并分析单个页面，返回结构化报告片段（不含广告表现指标）。

    deep=True 时额外做站内相似度抽样（多抓最多 3 个同域页面），用于单 URL 检测；
    报表模式传 deep=False，避免抓取量随 URL 数放大。
    """
    async def _go():
        if client is not None:
            return await _analyze_page_async(url, ad, client, deep)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.settings.fetch_timeout),
            follow_redirects=False,
            headers={"User-Agent": config.settings.user_agent},
            verify=True,
        ) as own:
            return await _analyze_page_async(url, ad, own, deep)

    return _run(_go())


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已有循环中用 run_until_complete 不安全，改用新线程
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(1) as ex:
                return ex.submit(lambda: asyncio.new_event_loop().run_until_complete(coro)).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.new_event_loop().run_until_complete(coro)


async def analyze_report(parsed: dict, concurrency: int = 4) -> dict:
    """对报表聚合后的每个 URL 执行页面检测，结合广告指标计算优先级。"""
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.settings.fetch_timeout),
        follow_redirects=False,
        headers={"User-Agent": config.settings.user_agent},
        verify=True, limits=limits,
    ) as client:

        async def one(agg):
            async with sem:
                fr = await fetch_url(agg["final_url"], client)
                p = extract(agg["final_url"], fr.final_url or agg["final_url"],
                            fr.status_code, fr.content, fr.error, fr.error_type,
                            headers=fr.headers)
                if fr.ok:
                    await _check_robots(client, p, fr.final_url or agg["final_url"])
                    # 报表模式也做站内抽样（CONT-006）：每个 URL 额外抓最多 3 个同域内页
                    p.site_similarity, p.site_similarity_sample = await _sample_similarity(
                        client, p, fr.final_url or agg["final_url"])
                ad = AdContext(headlines=agg.get("headlines_sample", []),
                               descriptions=agg.get("descriptions_sample", []))
                findings = run_rules(p, ad)
                sc = score(findings)
                ad_metrics = {
                    "clicks": agg["clicks"], "cost": agg["cost"],
                    "conversions": agg["conversions"], "cpa": agg["cpa"],
                }
                prio = compute_priority(findings, ad_metrics)
                return {
                    "final_url": agg["final_url"],
                    "currency": agg["currency"],
                    "metrics": {k: agg[k] for k in ("clicks", "impressions", "cost",
                                                    "conversions", "ctr", "avg_cpc", "cpa", "conv_rate",
                                                    "campaign_count", "ad_group_count", "source_rows")},
                    "fetch": {"ok": fr.ok, "status_code": fr.status_code, "error": fr.error, "error_type": fr.error_type},
                    "page_summary": _page_summary(p) if (fr.ok or fr.content) else None,
                    "score": sc,
                    "findings": [finding_to_dict(f) for f in findings],
                    "priority": prio,
                }

        results = await asyncio.gather(*[one(a) for a in parsed["aggregated"]])

    # 项目汇总
    total_cost = sum((a["cost"] or 0) for a in parsed["aggregated"])
    total_clicks = sum((a["clicks"] or 0) for a in parsed["aggregated"])
    total_impr = sum((a["impressions"] or 0) for a in parsed["aggregated"])
    total_conv = sum((a["conversions"] or 0) for a in parsed["aggregated"])
    prio_counts = {}
    for r in results:
        prio_counts[r["priority"]["priority"]] = prio_counts.get(r["priority"]["priority"], 0) + 1
    policy_risks = [r["final_url"] for r in results if r["score"]["policy_risk"]["status"] == "risk_found"]

    summary = {
        "total_cost": round(total_cost, 2),
        "total_clicks": total_clicks,
        "total_impressions": total_impr,
        "total_conversions": total_conv,
        "aggregate_ctr": round(total_clicks / total_impr, 4) if total_impr else None,
        "priority_counts": prio_counts,
        "policy_risk_urls": policy_risks,
    }
    return {
        "type": "report",
        "preview": parsed["preview"],
        "warnings": parsed["warnings"],
        "summary": summary,
        "urls": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def analyze_page_with_input(url: str, inputs: dict) -> dict:
    """公开入口：单 URL 检测（供 API 调用）。"""
    return _single_report(url, inputs)


async def analyze_pages(urls: list, ad: Optional[AdContext], concurrency: int, deep: bool) -> list:
    """并发抓取并分析多个页面，返回与 _analyze_page_async 同构的结果列表。"""
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.settings.fetch_timeout),
        follow_redirects=False,
        headers={"User-Agent": config.settings.user_agent},
        verify=True, limits=limits,
    ) as client:
        async def one(u):
            async with sem:
                return await _analyze_page_async(u, ad, client, deep)
        return await asyncio.gather(*[one(u) for u in urls])


async def analyze_url_list(urls: list, inputs: dict, concurrency: int = 4) -> dict:
    """多条 URL 批量检测：统一可选广告上下文，逐一抓取分析并汇总概览。

    - 少量 URL（≤5）开启站内相似度抽样（CONT-006），与单 URL 检测同口径；
      量大时关闭抽样以提速（与报表模式一致）。
    - 不聚合广告花费指标（那属于报表模式），每条 URL 独立评分与优先级。
    """
    ad = None
    if inputs.get("ad_headlines") or inputs.get("ad_descriptions") or inputs.get("keywords"):
        ad = AdContext(
            headlines=inputs.get("ad_headlines") or [],
            descriptions=inputs.get("ad_descriptions") or [],
            keywords=inputs.get("keywords") or [],
        )
    deep = len(urls) <= 5
    pages = await analyze_pages(urls, ad, max(1, min(concurrency, len(urls))), deep)
    scs = [p["score"]["overall_score"] for p in pages
           if (p.get("score") or {}).get("overall_score") is not None]
    summary = {
        "total": len(pages),
        "fetch_ok": sum(1 for p in pages if (p.get("fetch") or {}).get("ok")),
        "avg_score": round(sum(scs) / len(scs), 1) if scs else None,
        "grade_counts": {},
        "prio_counts": {},
    }
    for p in pages:
        lv = ((p.get("score") or {}).get("grade") or {}).get("level")
        if lv:
            summary["grade_counts"][lv] = summary["grade_counts"].get(lv, 0) + 1
        pr = (p.get("priority") or {}).get("priority")
        if pr:
            summary["prio_counts"][pr] = summary["prio_counts"].get(pr, 0) + 1
    return {
        "type": "batch",
        "urls": pages,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _single_report(url: str, inputs: dict) -> dict:
    ad = None
    if inputs.get("ad_headlines") or inputs.get("ad_descriptions") or inputs.get("keywords"):
        ad = AdContext(
            headlines=inputs.get("ad_headlines") or [],
            descriptions=inputs.get("ad_descriptions") or [],
            keywords=inputs.get("keywords") or [],
        )
    # 单 URL 检测开启 deep：额外做站内相似度抽样（CONT-006）
    page = analyze_page(url, ad, deep=True)
    page["input"] = {
        "url": url,
        "industry": inputs.get("industry"),
        "country": inputs.get("country"),
        "language": inputs.get("language"),
        "goal": inputs.get("goal"),
        "product": inputs.get("product"),
        "keywords": inputs.get("keywords"),
        "ad_headlines": inputs.get("ad_headlines"),
        "ad_descriptions": inputs.get("ad_descriptions"),
    }
    page["type"] = "single_url"
    page["generated_at"] = datetime.now(timezone.utc).isoformat()
    return page
