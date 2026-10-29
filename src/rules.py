"""规则引擎。

依据类型（basis_type）对应 PRD 第 4.5 节分类：
  A official_policy           官方政策/要求
  B official_recommendation   官方建议
  C optimizer_recommendation  CRO/优化经验
  D technical_check           技术检测
  E industry_guidance         行业/目标市场建议
  F manual_review             需人工核对

状态（status）：pass / fail / not_detected / not_applicable
严重级别（severity）：critical / high / medium / low
每条规则产出：evidence（可复核证据）、recommendation（具体修复步骤）、confidence（置信度）
"""
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional
from urllib.parse import urlsplit

from .html_extract import PageData

# 广告上下文：可选，提供后启用广告—页面相关性维度
@dataclass
class AdContext:
    headlines: List[str] = field(default_factory=list)
    descriptions: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


@dataclass
class Finding:
    rule_id: str
    title: str
    basis_type: str
    basis_label: str
    dimension: str
    device: str
    severity: str
    status: str
    method: str
    evidence: List[dict] = field(default_factory=list)
    recommendation: List[str] = field(default_factory=list)
    confidence: float = 0.0
    version: str = "1.0"
    # 整改责任人：这条规则查出的问题该由谁去改
    owner: str = "网建人员"


BASIS_LABELS = {
    "official_policy": "官方政策/要求",
    "official_recommendation": "官方建议",
    "optimizer_recommendation": "CRO/优化经验",
    "technical_check": "技术检测",
    "industry_guidance": "行业/目标市场建议",
    "manual_review": "需人工核对",
}

DIMENSION_LABELS = {
    "accessibility": "可访问性与技术稳定性",
    "ad_relevance": "广告—页面相关性",
    "content": "内容与产品信息",
    "conversion": "询盘转化体验",
    "mobile_perf": "移动端与性能",
    "trust": "信任与透明度",
}

# 整改责任人：按维度默认归属，个别规则可用 OWNER_OVERRIDE 精确覆盖。
# 网站 / SEO / 内容 / 转化 / 性能类问题由网建人员整改；
# 广告与页面匹配类问题由优化师整改（改广告投放侧或推动页面配合）。
OWNER_BY_DIM = {
    "accessibility": "网建人员",
    "content": "网建人员",
    "conversion": "网建人员",
    "mobile_perf": "网建人员",
    "trust": "网建人员",
    "ad_relevance": "优化师",
}

# 需要单独指定责任人的规则（键为规则 ID）
OWNER_OVERRIDE = {
    # 例：某条内容规则想改派给运营，写 "CONT-002": "运营",
}


def owner_of(rule_id: str, dimension: str) -> str:
    return OWNER_OVERRIDE.get(rule_id) or OWNER_BY_DIM.get(dimension, "网建人员")


def ev(source: str, text: str, location: str = "") -> dict:
    return {"source": source, "text": text, "location": location}


# ----------------------------------------------------------------------------
# 规则检测函数：返回 (status, evidence, recommendation, confidence)
# ----------------------------------------------------------------------------

def _r_reachable(p: PageData, ad: Optional[AdContext]):
    if p.error and p.error_type == "ssrf":
        return "fail", [ev("fetch", p.error)], ["目标地址被安全策略拦截，请确认 URL 是否属于客户自有站点并符合内网访问规范"], 0.95
    if p.error:
        return "fail", [ev("fetch", p.error, p.error_type or "")], ["检查目标站点可用性、网络连通性；若为反爬/验证码请人工核对"], 0.9
    if p.status_code is None:
        return "not_detected", [ev("fetch", "未获取到状态码")], ["重新抓取页面以确认可访问性"], 0.5
    if 200 <= p.status_code < 300:
        return "pass", [ev("http_status", str(p.status_code), p.final_url)], ["无需处理"], 0.95
    if 300 <= p.status_code < 400:
        return "fail", [ev("http_status", str(p.status_code), p.final_url)], ["检查跳转目标是否正确可达；避免循环或错误跳转"], 0.9
    return "fail", [ev("http_status", str(p.status_code), p.final_url)], ["修复服务器错误；确认页面在投放国家/地区可正常访问"], 0.9


def _r_not_blank(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("content", "页面未成功获取，无法判断内容完整性")], ["成功抓取后再评估内容"], 0.5
    sample = f"；内容开头：「{p.text_sample}」" if p.text_sample else ""
    note = "（不含导航/页脚/表单等模板文字）"
    if p.word_count >= 200:
        return "pass", [ev("content", f"正文约 {p.word_count} 词/字{note}{sample}", "body")], ["保持内容充实"], 0.8
    if p.word_count >= 50:
        return "fail", [ev("content", f"正文仅约 {p.word_count} 词/字，内容偏少{note}{sample}", "body")], ["补充产品说明、参数、应用场景、案例等实质内容"], 0.75
    return "fail", [ev("content", f"可读正文极少（约 {p.word_count} 词/字，不含模板文字），疑似空白页、仅有图片或内容由脚本动态加载{sample}", "body")], ["排查页面渲染/内容加载问题，补充可读文字内容"], 0.8


def _r_https(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("protocol", "未获取最终 URL")], ["抓取成功后评估协议安全性"], 0.4
    if p.final_url.startswith("https://"):
        return "pass", [ev("final_url", p.final_url)], ["保持全站 HTTPS"], 0.9
    return "fail", [ev("final_url", p.final_url or p.url)], ["启用 HTTPS 以避免浏览器标记“不安全”并提升信任"], 0.85


def _r_redirect_chain(p: PageData, ad: Optional[AdContext]):
    if p.error_type == "redirect":
        return "fail", [ev("redirect", "跳转次数超过限制")], ["精简跳转链，直达落地页"], 0.8
    return "pass", [ev("redirect", "跳转链长度正常")], ["保持跳转简洁"], 0.7


def _r_unrelated_redirect(p: PageData, ad: Optional[AdContext]):
    from urllib.parse import urlparse
    if not p.final_url or not p.url:
        return "not_detected", [ev("redirect", "缺少跳转信息")], ["确认最终落地地址"], 0.4
    h1 = (urlparse(p.url).hostname or "").lower().replace("www.", "")
    h2 = (urlparse(p.final_url).hostname or "").lower().replace("www.", "")
    if h1 and h2 and h1 != h2:
        return "fail", [ev("redirect", f"从 {p.url} 跳转到不同域名 {p.final_url}")], ["确认该跳转是否符合预期；跳转到无关域名会分散转化并触发核对"], 0.85
    return "pass", [ev("redirect", f"最终地址与输入同域：{p.final_url}")], ["无需处理"], 0.8


def _r_title(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("title", "未获取页面")], ["抓取后检查 <title>"], 0.4
    if p.title:
        return "pass", [ev("title", p.title[:120])], ["保持标题与页面主题一致"], 0.9
    return "fail", [ev("title", "页面缺少 <title> 标签")], ["补充准确描述页面内容的 <title>，利于检索与用户识别"], 0.9


def _r_title_len(p: PageData, ad: Optional[AdContext]):
    if not p.title:
        return "not_applicable", [ev("title", "无标题，已由标题缺失规则处理")], ["先补充标题"], 0.6
    n = len(p.title)
    if 10 <= n <= 70:
        return "pass", [ev("title", f"标题长度 {n} 字符")], ["保持标题精炼"], 0.7
    if n < 10:
        return "fail", [ev("title", f"标题过短（{n} 字符）：{p.title}")], ["补充更具描述性的标题"], 0.7
    return "fail", [ev("title", f"标题过长（{n} 字符），搜索结果可能被截断")], ["精简标题至 60 字符内并前置核心信息"], 0.7


def _r_meta_desc(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("meta", "未获取页面")], ["抓取后检查 meta description"], 0.4
    if p.meta_description and len(p.meta_description) >= 20:
        return "pass", [ev("meta", p.meta_description[:120])], ["保持描述与广告承诺、页面内容一致"], 0.85
    if p.meta_description:
        return "fail", [ev("meta", f"描述过短（{len(p.meta_description)} 字符）")], ["补充 70–160 字、包含价值主张与关键词的描述"], 0.8
    return "fail", [ev("meta", "缺少 meta description")], ["补充 meta description，提升搜索结果点击率与相关性信号"], 0.85


def _r_canonical(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("canonical", "未获取页面")], ["抓取后检查 canonical"], 0.4
    if not p.canonical:
        return "fail", [ev("canonical", "缺少 <link rel=canonical>")], ["添加指向自身的 canonical，聚合重复页面权重，避免站内相似页互相竞争收录"], 0.7
    base = p.final_url or p.url
    def _norm(u):
        s = urlsplit(u)
        host = (s.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return (host, s.path.rstrip("/"))
    if _norm(p.canonical) == _norm(base):
        return "pass", [ev("canonical", p.canonical[:160])], ["保持 canonical 指向自身"], 0.8
    return "fail", [ev("canonical", f"canonical 指向其他页面：{p.canonical[:160]}")], ["canonical 指向别页等于告诉 Google 不要收录本页；若本页要投广告，改为指向自身或删除该标签"], 0.75


def _r_alt(p: PageData, ad: Optional[AdContext]):
    if p.error or p.images_total == 0:
        return "not_applicable", [ev("images", "页面无图片或无数据")], ["如有图片请补充 ALT"], 0.5
    # 仅内容图片纳入 ALT 覆盖率分母，装饰/图标图（社交图标、站标等）通常无需 ALT
    content = p.images_total - p.images_empty_src - p.images_decorative
    if content == 0:
        if p.images_empty_src > 0:
            return "not_detected", [ev("images", f"{p.images_empty_src} 张图片缺少 src（疑似懒加载，无法核对 ALT）")], ["确认懒加载触发后图片可被抓取且含 ALT"], 0.4
        return "not_applicable", [ev("images", "无有效内容图片（其余为装饰/图标图，通常无需 ALT）")], [""], 0.5
    total = p.images_with_alt + p.images_missing_alt
    coverage = p.images_with_alt / total if total else 0
    # 小样本提示：内容图 <3 张时覆盖率统计意义有限，需人工核对（避免 1/1=100% 造成“已达标”错觉）
    note = "；内容图样本过小，建议人工核对" if total < 3 else ""
    conf = 0.4 if total < 3 else 0.8
    if coverage >= 0.9:
        return "pass", [ev("images", f"内容图片 ALT 覆盖率 {coverage*100:.0f}%（{p.images_with_alt}/{total}）{note}")], ["保持图片 ALT 描述准确"], conf
    evs = [ev("images", f"内容图片 ALT 缺失 {p.images_missing_alt}/{total}（覆盖率 {coverage*100:.0f}%）{note}")]
    if p.images_missing_alt_list:
        if p.images_missing_alt != len(p.images_missing_alt_list):
            suffix = f"（共 {p.images_missing_alt} 张，此处列出 {len(p.images_missing_alt_list)} 张）"
        else:
            suffix = ""
        evs.append(ev("images", f"缺失 ALT 的图片地址{suffix}：" + "；".join(p.images_missing_alt_list)))
    return "fail", evs, ["为重要图片补充描述性 ALT，兼顾可访问性与图片检索相关性"], conf


def _r_robots(p: PageData, ad: Optional[AdContext]):
    """TECH-007：检查三层可确定的屏蔽信号。

    ① <meta name="robots">  ② 响应头 X-Robots-Tag  ③ robots.txt 是否禁止该路径
    三层都查不到屏蔽才判通过；「Google 实际是否已收录」仍需 Search Console，工具不冒充官方结论。
    """
    if p.error:
        return "not_detected", [ev("robots", "未获取页面")], ["抓取后检查屏蔽信号"], 0.4

    blockers: List[str] = []
    if p.meta_robots and ("noindex" in p.meta_robots.lower() or "nofollow" in p.meta_robots.lower()):
        blockers.append(f"meta robots: {p.meta_robots}")
    if p.x_robots_tag and ("noindex" in p.x_robots_tag.lower() or "nofollow" in p.x_robots_tag.lower()):
        blockers.append(f"X-Robots-Tag 响应头: {p.x_robots_tag}")
    if p.robots_disallow is True:
        blockers.append("robots.txt 禁止抓取该路径")

    if blockers:
        return (
            "fail",
            [ev("robots", "检测到屏蔽信号：" + "；".join(blockers))],
            ["移除 noindex/nofollow 或放开 robots.txt 限制；改动后在 Search Console 验证收录状态"],
            0.8,
        )

    checked = ["meta robots 无屏蔽"]
    if p.x_robots_tag:
        checked.append(f"X-Robots-Tag: {p.x_robots_tag}")
    else:
        checked.append("无 X-Robots-Tag 响应头")
    if p.robots_disallow is False:
        checked.append("robots.txt 允许抓取该路径")
    elif p.robots_disallow is None:
        checked.append("robots.txt 未取到或无相关规则")
    return (
        "pass",
        [ev("robots", "；".join(checked))],
        ["Google 实际收录/抓取状态请在 Search Console 核实（本工具不冒充官方抓取结论）"],
        0.7,
    )


def _r_h1(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("h1", "未获取页面")], ["抓取后检查 H1"], 0.4
    if not p.h1_list:
        return "fail", [ev("h1", "页面缺少 H1 标题")], ["添加清晰描述核心产品或服务的 H1"], 0.85
    if len(p.h1_list) == 1:
        return "pass", [ev("h1", p.h1_list[0][:120])], ["保持单一明确的主标题"], 0.8
    return "fail", [ev("h1", f"存在 {len(p.h1_list)} 个 H1，结构不清晰")], ["合并为单一主 H1，其余用 H2/H3 层级化"], 0.75


def _r_body_len(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("content", "未获取页面")], ["抓取后评估正文长度"], 0.4
    sample = f"；内容开头：「{p.text_sample}」" if p.text_sample else ""
    if p.word_count >= 300:
        return "pass", [ev("content", f"正文约 {p.word_count} 词/字（不含模板文字）{sample}")], ["可继续丰富细节与场景"], 0.75
    return "fail", [ev("content", f"正文约 {p.word_count} 词/字（不含模板文字），信息可能不足以支撑采购判断{sample}")], ["补充规格、应用场景、认证、案例、采购信息等高信息量内容"], 0.7


def _r_specs(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("content", "未获取页面")], ["抓取后评估具体参数"], 0.4
    if p.specs or p.certs:
        found = (p.specs[:5] if p.specs else []) + (p.certs[:5] if p.certs else [])
        return "pass", [ev("content", f"检测到具体参数/认证：{', '.join(found)}")], ["保持参数准确、单位清晰"], 0.7
    # 规格表被做成图片（或 JS 动态渲染）：文本层读不到，不能判「缺失」，只能标记需人工核对
    if p.image_tables:
        return (
            "not_detected",
            [ev("content", f"检测到 {p.image_tables} 个仅含图片的表格，规格/认证可能以图片形式呈现，文本层无法解析")],
            ["人工核对该图片表格中的参数；建议同时提供 HTML 文本版规格表（利于收录与转化）"],
            0.4,
        )
    # 规格选项卡头在静态 HTML、内容由 JS 异步注入：同样读不到，标需人工核对而非「缺失」
    if p.spec_tabs:
        return (
            "not_detected",
            [ev("content", f"检测到规格选项卡（{'、'.join(p.spec_tabs[:2])}），但其内容为 JS 动态渲染，静态抓取无法读取；规格参数可能存在，需人工核对")],
            ["人工核对该选项卡中的参数；建议同时提供 HTML 文本版规格表（利于收录与转化）"],
            0.4,
        )
    return "fail", [ev("content", "未检测到具体规格参数或认证信息")], ["补充具体型号、尺寸、参数、认证等可量化信息，提升专业度与可信度"], 0.7


def _r_value_prop(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("content", "未获取页面")], ["抓取后评估价值主张"], 0.4
    # 只在“正文主内容”中检索信号，页眉/页脚/导航/表单标签里的 contact/price 不算（避免模板站靠页脚联系信息误判通过）
    text = (p.main_text or p.text).lower()
    # 明确规则（数量与价值同一把尺子）：正文真实内容太少，谈不上“价值主张清晰”
    if p.word_count < 50:
        return "fail", [ev("content", f"正文真实内容过少（约 {p.word_count} 词/字），无法构成清晰的价值主张")], ["补充产品说明、报价/询价/定制等实质内容与行动召唤"], 0.6
    # 信号分级：强信号=实质动作/报价/定制/样品等（模板标配之外的价值点）；弱信号=仅价格标签或联系入口
    # inquir/enquir 用词干匹配 inquiry/inquire/inquiry-form 与 enquiry/enquire 等变体（B2B 英文站询价入口标准文案）
    signals = ["询价", "报价", "免费", "联系", "定制", "批发", "factory", "price", "quote", "quotation", "inquir", "enquir", "contact", "oem", "moq", "sample"]
    strong = {"询价", "报价", "免费", "定制", "批发", "quote", "quotation", "inquir", "enquir", "oem", "moq", "sample"}
    hits = [s for s in signals if s in text]
    strong_hits = [s for s in hits if s in strong]
    # 明确规则：价值主张清晰需 ①正文主内容出现 ≥2 个信号 ②其中至少 1 个为强信号（不能是“价格+联系”这种模板标配）
    if len(hits) >= 2 and len(strong_hits) >= 1:
        return "pass", [ev("content", f"正文主内容检测到价值主张/行动信号：{', '.join(hits[:6])}")], ["保持清晰的价值主张与下一步动作（询价/获取报价/联系销售）"], 0.6
    if len(hits) == 0:
        return "fail", [ev("content", "正文主内容未检测到任何价值主张或行动召唤信号（如报价/询价/定制/联系）")], ["在正文明确价值主张与下一步动作（询价/获取报价/联系销售）"], 0.6
    # 仅有弱信号（如仅 price/contact）或仅 1 个信号 → 不构成清晰价值主张
    return "fail", [ev("content", f"正文主内容仅检测到弱信号（{', '.join(hits[:4])}），缺乏报价/询价/定制/样品等实质价值点，价值主张不清晰")], ["在正文补充实质价值点：报价、询价入口、定制/OEM、样品/MOQ 等具体行动信号"], 0.6


def _r_contact_info(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("contact", "未获取页面")], ["抓取后评估联系方式"], 0.4
    if p.phones or p.emails:
        return "pass", [ev("contact", f"检测到联系方式：电话 {len(p.phones)} / 邮箱 {len(p.emails)}")], ["保持联系方式醒目且多渠道"], 0.75
    return "fail", [ev("contact", "未在页面文本中发现电话或邮箱")], ["提供电话/邮箱/表单等至少一种明确联系方式，降低用户联系门槛"], 0.75


def _r_unique(p: PageData, ad: Optional[AdContext]):
    """CONT-006：内容独特性。

    跨站/全网重复无法通过单次抓取判定，这部分永远留给人工。
    能做的是站内抽样：比对同域内页文本相似度，抓「整站套壳」这类可发现问题。
    结论明确标注为抽样估算，不当作确定性证据。
    """
    if p.error:
        return "not_detected", [ev("content", "未获取页面")], ["抓取后评估内容独特性"], 0.4
    if p.site_similarity is None:
        return (
            "not_detected",
            [ev("content", "未做站内抽样；内容独特性需对照站内/站外比较，无法仅通过单次抓取判定")],
            ["人工或借助内容相似度工具核对是否重复/采集内容"],
            0.3,
        )
    sim = p.site_similarity * 100
    if p.site_similarity >= 0.8:
        return (
            "fail",
            [ev("content", f"站内抽样 {p.site_similarity_sample} 页，文本相似度最高 {sim:.0f}%（词集合 Jaccard，"
                           f"含导航页脚等共用文本干扰，为抽样估算非精确结论）")],
            ["该页与站内其他页面高度相似，疑似模板套壳/单页重复；请人工核对是否为实质性独立内容"],
            0.6,
        )
    return (
        "pass",
        [ev("content", f"站内抽样 {p.site_similarity_sample} 页，文本相似度最高 {sim:.0f}%"
                       f"（抽样估算，不能排除跨站采集）")],
        ["跨站重复/采集仍需借助全网相似度工具或人工判断"],
        0.5,
    )


def _r_cta(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("cta", "未获取页面")], ["抓取后评估 CTA"], 0.4
    if p.cta_buttons or p.form_has_submit:
        return "pass", [ev("cta", f"检测到 CTA 元素（按钮/提交）样本：{', '.join(p.cta_buttons[:5])}")], ["确保主 CTA 在首屏可见且文案明确"], 0.8
    return "fail", [ev("cta", "未发现明确的行动按钮或提交元素")], ["添加醒目的主 CTA（如“获取报价”“立即咨询”），引导用户转化"], 0.8


def _r_form(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("form", "未获取页面")], ["抓取后评估表单"], 0.4
    if p.forms == 0:
        return "fail", [ev("form", "页面未发现询盘/联系表单")], ["添加询盘表单，降低转化门槛（尤其对 B2B 询盘目标）"], 0.8
    if p.form_has_submit and p.form_inputs >= 2:
        return "pass", [ev("form", f"表单数 {p.forms}，输入项 {p.form_inputs}，含提交按钮")], ["保持表单字段精简、必填项清晰"], 0.8
    return "fail", [ev("form", f"表单数 {p.forms}，但缺少提交按钮或输入项不足")], ["确保表单包含提交按钮与必要字段，并验证提交成功反馈"], 0.75


def _r_phone_email_cta(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("cta", "未获取页面")], ["抓取后评估多渠道转化"], 0.4
    has_form = p.forms > 0
    has_contact = bool(p.phones or p.emails)
    if has_form and has_contact:
        return "pass", [ev("cta", "同时存在表单与电话/邮箱多渠道转化路径")], ["保持多渠道可达"], 0.7
    return "fail", [ev("cta", "转化路径单一（仅表单或仅电话/邮箱）")], ["增加至少两种转化路径（表单 + 电话/邮箱/WhatsApp 等）覆盖不同用户偏好"], 0.65


def _r_form_submit(p: PageData, ad: Optional[AdContext]):
    if p.forms == 0:
        return "not_applicable", [ev("form", "无表单")], [""], 0.5
    if p.form_has_submit:
        return "pass", [ev("form", "表单含提交按钮")], ["验证提交后成功反馈"], 0.7
    return "fail", [ev("form", "表单缺少可识别的提交按钮")], ["为表单添加明确的提交按钮并测试提交流程"], 0.7


def _r_viewport(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("viewport", "未获取页面")], ["抓取后评估移动端视口"], 0.4
    if "width" in p.viewport.lower() and "device-width" in p.viewport.lower():
        return "pass", [ev("viewport", p.viewport)], ["保持移动端视口配置"], 0.85
    if p.viewport:
        return "fail", [ev("viewport", f"视口配置可能不利于移动端：{p.viewport}")], ["设置 viewport 为 width=device-width, initial-scale=1"], 0.7
    return "fail", [ev("viewport", "缺少 viewport meta 标签")], ["添加 <meta name=viewport content=\"width=device-width, initial-scale=1\"> 适配移动端"], 0.85


def _r_responsive(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("responsive", "未获取页面")], ["需真实渲染或 CSS 分析确认响应式"], 0.4
    if p.has_media_queries:
        return "pass", [ev("responsive", "检测到媒体查询（响应式信号）")], ["在真机/模拟器中进一步验证无横向溢出与遮挡"], 0.6
    if p.external_css > 0:
        return "not_detected", [ev("responsive", f"检测到 {p.external_css} 个外部样式表，但本工具不解析外部 CSS 内容，无法确认是否含响应式媒体查询")], ["用移动设备真机或浏览器设备模拟验证布局（本工具未做真实渲染）"], 0.4
    return "not_detected", [ev("responsive", "未发现响应式媒体查询；本工具未做真实浏览器渲染，需人工核对")], ["用移动设备真机或浏览器设备模拟验证布局"], 0.4


def _r_page_size(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("perf", "未获取页面")], ["抓取后评估体积"], 0.4
    mb = p.page_bytes / (1024 * 1024)
    # 体积下限感知：体积小 ≠ 合格。体积小 + 正文内容不足，是空壳页特征（内容缺失导致体积小），并非“轻量”优点
    if mb < 0.3 and p.word_count < 200:
        return "fail", [ev("perf", f"页面体积仅约 {mb:.2f} MB，且正文仅约 {p.word_count} 词/字——体积小源于内容缺失（空壳页），并非性能优点")], ["补充产品说明、图片、参数等实质内容；此时不应继续追求减体积"], 0.65
    # 健康区间以落地页质量为导向：理想 1–2MB；<1MB 偏轻量但内容充实也算正常；>2MB 偏大，>4MB 过大
    if mb <= 2:
        if mb < 1:
            note = "；体积偏小但内容充实，属轻量页（理想区间为 1–2MB）" if mb >= 0.3 else "；体积较小且内容充实，属正常轻量页（理想区间为 1–2MB）"
        else:
            note = "（处于健康区间 1–2MB）"
        return "pass", [ev("perf", f"页面体积约 {mb:.2f} MB{note}")], ["保持轻量；目标控制在 1–2MB 区间"], 0.7
    if mb <= 4:
        return "fail", [ev("perf", f"页面体积约 {mb:.2f} MB，偏大（高质量页面建议 HTML 文档控制在 2MB 内）")], ["压缩内联资源/图片、精简 DOM 与冗余标签"], 0.65
    return "fail", [ev("perf", f"页面体积约 {mb:.2f} MB，过大，严重影响移动端加载（建议 HTML 文档控制在 2MB 内）")], ["大幅优化资源：图片压缩/WebP、代码拆分、移除冗余"], 0.7


def _r_img_count(p: PageData, ad: Optional[AdContext]):
    if p.error or p.images_total == 0:
        return "not_applicable", [ev("perf", "无图片数据")], [""], 0.4
    content = p.images_total - p.images_empty_src - p.images_decorative
    note = ""
    if p.images_decorative or p.images_empty_src:
        note = (f"（共 {p.images_total} 个 img 标签，其中装饰/图标图 {p.images_decorative} 张、"
                f"空 src 懒加载 {p.images_empty_src} 张，已不计入内容图）")
    if content == 0:
        # 全是装饰/图标/懒加载图，页面没有可读内容图 —— 落地页缺图不利于转化
        return "fail", [ev("perf", f"可读内容图片 0 张{note}")], ["补充产品图、应用场景图或工厂实拍等内容图片，纯装饰/图标不利于转化"], 0.6
    if 3 <= content <= 20:
        return "pass", [ev("perf", f"可读内容图片 {content} 张（处于合理区间 3–20 张）{note}")], ["保持合理"], 0.6
    if content < 3:
        return "fail", [ev("perf", f"可读内容图片 {content} 张，偏少（建议 3–20 张，图文结合更利于转化与信任）{note}")], ["补充产品图、应用场景图、工厂/资质实拍等内容图片"], 0.6
    return "fail", [ev("perf", f"可读内容图片 {content} 张，偏多（建议控制在 3–20 张，图片过多影响加载）{note}")], ["非首屏图片懒加载/按需加载，合并或删减重复图片"], 0.6


def _r_render_block(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("perf", "未获取页面")], ["需 Lighthouse/PSI 等工具实测"], 0.4
    total = p.render_blocking_scripts + p.render_blocking_stylesheets
    if total <= 15:
        return "pass", [ev("perf", f"阻塞资源（脚本+样式）约 {total} 个")], ["保持合理"], 0.5
    return "fail", [ev("perf", f"阻塞资源较多（约 {total} 个）")], ["异步加载脚本、内联关键 CSS、减少第三方阻塞"], 0.55


def _r_company(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("trust", "未获取页面")], ["抓取后评估公司信息"], 0.4
    text = p.text.lower()
    signals = ["about", "company", "about us", "公司", "factory", "manufacturer", "established", "since", "founded"]
    hits = [s for s in signals if s in text]
    if hits:
        return "pass", [ev("trust", f"检测到公司/企业信息信号：{', '.join(hits[:5])}")], ["在关于页补充资质与实力"], 0.6
    return "fail", [ev("trust", "页面缺乏公司/企业背景信息")], ["补充公司简介、实力、资质，增强 B2B 采购信任"], 0.6


def _r_privacy(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("trust", "未获取页面")], ["抓取后评估政策信息"], 0.4
    text = p.text.lower()
    links = " ".join(p.cta_buttons).lower()
    signals = ["privacy", "privacypolicy", "隐私", "terms", "条款", "return", "退换", "refund", "退货", "policy"]
    hits = [s for s in signals if s in text or s in links]
    if len(hits) >= 1:
        return "pass", [ev("trust", f"检测到政策/保障信息信号：{', '.join(hits[:5])}")], ["完善隐私/退换/条款说明"], 0.55
    return "fail", [ev("trust", "未发现隐私/退换/条款等政策信息")], ["补充隐私政策、退换货与条款，降低采购顾虑"], 0.55


def _r_contact_transparency(p: PageData, ad: Optional[AdContext]):
    if p.error:
        return "not_detected", [ev("trust", "未获取页面")], ["抓取后评估联系透明度"], 0.4
    if p.phones and p.emails:
        return "pass", [ev("trust", f"电话与邮箱均可见（电话 {len(p.phones)} / 邮箱 {len(p.emails)}）")], ["保持信息真实可用"], 0.7
    if p.phones or p.emails:
        return "fail", [ev("trust", "仅提供单一联系方式，透明度有限")], ["同时提供电话与邮箱，并补充地址/地图提升可信度"], 0.65
    return "fail", [ev("trust", "页面未展示任何真实联系方式")], ["补充电话、邮箱、公司地址等真实联系信息"], 0.7


def _r_exaggeration(p: PageData, ad: Optional[AdContext]):
    """TRUST-004：极端/无法验证承诺用语筛查。

    不判定商业声明真假（那需要行业知识与证据），只把命中的原文片段列出来让人工核对。
    因此 fail 的建议里明确写「需人工确认」，不把命中直接等同于违规。
    """
    if p.error:
        return "not_detected", [ev("trust", "未获取页面")], ["抓取后筛查宣传用语"], 0.4
    if p.extreme_claims:
        joined = "、".join(p.extreme_claims[:6])
        return (
            "fail",
            [ev("trust", f"检测到 {len(p.extreme_claims)} 处极端/无法验证承诺用语：{joined}")],
            ["逐条人工确认这些表述是否有证据支撑；广告法禁用「最」「第一」「100%」等绝对化用语，"
             "无法验证的承诺建议改为可核实的具体参数或第三方证明"],
            0.6,
        )
    return (
        "pass",
        [ev("trust", "未发现常见极端承诺用语（最好/第一/100%/保证/根治/无效退款等）")],
        ["本项仅覆盖常见绝对化与无法验证措辞，行业特定表述仍需人工通读"],
        0.5,
    )


def _r_ad_headline(p: PageData, ad: Optional[AdContext]):
    if not ad or not ad.headlines:
        return "not_applicable", [ev("ad", "未提供广告标题，跳过广告—页面相关性检测")], ["在检测时补充广告标题/描述以启用联合诊断"], 0.3
    text = p.text.lower()
    matched, missing = [], []
    for h in ad.headlines:
        words = [w for w in re.findall(r"[\w\u4e00-\u9fff]{2,}", h.lower()) if len(w) >= 2]
        ok = any(w in text for w in words)
        (matched if ok else missing).append(h[:60])
    if matched:
        return "pass", [ev("ad_headline", f"以下广告标题关键词在页面找到对应：{'; '.join(matched[:3])}")], ["保持广告与页面主题一致"], 0.6
    return "fail", [ev("ad_headline", f"广告标题未在页面找到明显对应：{'; '.join(missing[:3])}")], ["使页面包含广告承诺的产品/服务关键词，或调整广告定向"], 0.6


def _r_ad_desc(p: PageData, ad: Optional[AdContext]):
    if not ad or not ad.descriptions:
        return "not_applicable", [ev("ad", "未提供广告描述")], ["补充广告描述以启用联合诊断"], 0.3
    text = p.text.lower()
    missing = []
    for d in ad.descriptions:
        words = [w for w in re.findall(r"[\w\u4e00-\u9fff]{2,}", d.lower()) if len(w) >= 2]
        if not any(w in text for w in words):
            missing.append(d[:60])
    if not missing:
        return "pass", [ev("ad_description", "广告描述承诺在页面中找到对应内容")], ["保持承诺可兑现"], 0.6
    return "fail", [ev("ad_description", f"广告描述未在页面找到对应：{'; '.join(missing[:3])}")], ["确保页面兑现广告描述中的具体承诺（规格/价格/交期/认证）"], 0.6


def _r_ad_product(p: PageData, ad: Optional[AdContext]):
    if not ad:
        return "not_applicable", [ev("ad", "未提供广告数据")], ["补充广告数据以启用联合诊断"], 0.3
    candidates = (ad.headlines + ad.descriptions + ad.keywords)
    text = (p.title + " " + " ".join(p.h1_list) + " " + p.text[:2000]).lower()
    overlap = 0
    for c in candidates:
        words = [w for w in re.findall(r"[\w\u4e00-\u9fff]{2,}", c.lower()) if len(w) >= 2]
        if any(w in text for w in words):
            overlap += 1
    if candidates and overlap >= max(1, len(candidates) // 3):
        return "pass", [ev("ad_product", f"广告与页面主题存在关键词重叠（{overlap}/{len(candidates)} 项样本）")], ["保持产品一致性"], 0.55
    return "fail", [ev("ad_product", "广告与页面主题重叠偏低，可能意图不匹配")], ["核对广告组定向的落地页是否为最相关产品/分类/方案页"], 0.55


RULES = [
    # 可访问性与技术稳定性
    dict(id="ACC-001", title="页面可正常访问（HTTP 2xx）", basis="official_policy", dim="accessibility",
         device="both", severity="critical", method="请求页面并记录 HTTP 状态码", check=_r_reachable),
    dict(id="ACC-002", title="页面非空白、含实质内容", basis="technical_check", dim="accessibility",
         device="both", severity="high", method="统计可见正文词/字数", check=_r_not_blank),
    dict(id="ACC-003", title="使用 HTTPS 安全协议", basis="official_recommendation", dim="accessibility",
         device="both", severity="medium", method="检查最终 URL 协议", check=_r_https),
    dict(id="ACC-004", title="跳转链简洁无异常", basis="technical_check", dim="accessibility",
         device="both", severity="low", method="记录跳转链长度", check=_r_redirect_chain),
    dict(id="ACC-005", title="未跳转到无关域名", basis="technical_check", dim="accessibility",
         device="both", severity="high", method="比对输入与最终 URL 主机名", check=_r_unrelated_redirect),
    dict(id="TECH-001", title="存在 <title> 标题", basis="official_recommendation", dim="accessibility",
         device="both", severity="medium", method="解析 <title>", check=_r_title),
    dict(id="TECH-002", title="标题长度合理（10–70 字符）", basis="technical_check", dim="accessibility",
         device="both", severity="low", method="统计 title 长度", check=_r_title_len),
    dict(id="TECH-003", title="存在 meta description", basis="official_recommendation", dim="accessibility",
         device="both", severity="medium", method="解析 meta description", check=_r_meta_desc),
    dict(id="TECH-004", title="canonical 规范链接指向自身", basis="official_recommendation", dim="accessibility",
         device="both", severity="medium", method="解析 canonical 并与落地 URL 比对", check=_r_canonical),
    dict(id="TECH-006", title="图片 ALT 文本覆盖率达标", basis="technical_check", dim="accessibility",
         device="both", severity="medium", method="统计带 ALT 的图片比例", check=_r_alt),
    dict(id="TECH-007", title="未被 noindex/nofollow 屏蔽", basis="technical_check", dim="accessibility",
         device="both", severity="medium",
         method="meta robots + X-Robots-Tag 响应头 + robots.txt 三层检查（实际收录状态需 Search Console）",
         check=_r_robots),
    # 内容与产品信息
    dict(id="CONT-001", title="存在且唯一的 H1 主标题", basis="official_recommendation", dim="content",
         device="both", severity="medium", method="解析 H1 数量与内容", check=_r_h1),
    dict(id="CONT-002", title="正文长度足以支撑采购判断", basis="optimizer_recommendation", dim="content",
         device="both", severity="medium", method="统计正文词/字数", check=_r_body_len),
    dict(id="CONT-003", title="包含具体规格/认证参数", basis="optimizer_recommendation", dim="content",
         device="both", severity="medium", method="正则识别规格单位与认证关键词", check=_r_specs),
    dict(id="CONT-004", title="首屏价值主张/行动信号清晰", basis="optimizer_recommendation", dim="content",
         device="both", severity="low", method="检测报价/询价/定制等信号词", check=_r_value_prop),
    dict(id="CONT-005", title="提供联系方式", basis="industry_guidance", dim="content",
         device="both", severity="medium", method="识别电话/邮箱", check=_r_contact_info),
    dict(id="CONT-006", title="内容独特性（站内抽样 + 跨站需人工）", basis="manual_review", dim="content",
         device="both", severity="low",
         method="抽样同域内页算文本相似度（估算）；跨站重复无法自动判定",
         check=_r_unique),
    # 询盘转化体验
    dict(id="CONV-001", title="存在明确 CTA 行动按钮", basis="optimizer_recommendation", dim="conversion",
         device="both", severity="high", method="检测按钮/提交元素", check=_r_cta),
    dict(id="CONV-002", title="存在询盘/联系表单", basis="optimizer_recommendation", dim="conversion",
         device="both", severity="high", method="解析 form 元素", check=_r_form),
    dict(id="CONV-003", title="多渠道转化路径（表单+联系）", basis="optimizer_recommendation", dim="conversion",
         device="both", severity="medium", method="判断表单与联系方式共存", check=_r_phone_email_cta),
    dict(id="CONV-004", title="表单含提交按钮", basis="technical_check", dim="conversion",
         device="both", severity="medium", method="检测表单提交按钮", check=_r_form_submit),
    # 移动端与性能
    dict(id="MOB-001", title="配置移动端 viewport", basis="official_recommendation", dim="mobile_perf",
         device="mobile", severity="high", method="解析 viewport meta", check=_r_viewport),
    dict(id="MOB-002", title="响应式布局信号", basis="technical_check", dim="mobile_perf",
         device="mobile", severity="medium", method="检测媒体查询", check=_r_responsive),
    dict(id="PERF-001", title="页面体积健康（理想 1–2MB）", basis="optimizer_recommendation", dim="mobile_perf",
         device="both", severity="medium", method="统计 HTML 文档体积（响应体）", check=_r_page_size),
    dict(id="PERF-002", title="图片数量合理", basis="optimizer_recommendation", dim="mobile_perf",
         device="both", severity="low", method="统计内容图片数量（合理区间 3–20 张）", check=_r_img_count),
    dict(id="PERF-003", title="阻塞渲染资源可控", basis="technical_check", dim="mobile_perf",
         device="both", severity="low", method="统计同步脚本/样式", check=_r_render_block),
    # 信任与透明度
    dict(id="TRUST-001", title="展示公司/企业背景", basis="industry_guidance", dim="trust",
         device="both", severity="medium", method="检测 about/company 等信号", check=_r_company),
    dict(id="TRUST-002", title="提供隐私/退换/条款政策", basis="industry_guidance", dim="trust",
         device="both", severity="low", method="检测政策关键词", check=_r_privacy),
    dict(id="TRUST-003", title="联系信息透明（电话+邮箱）", basis="industry_guidance", dim="trust",
         device="both", severity="medium", method="检测电话与邮箱共存", check=_r_contact_transparency),
    dict(id="TRUST-004", title="无夸大/无法验证声明（用语筛查）", basis="manual_review", dim="trust",
         device="both", severity="low",
         method="正则筛查极端/无法验证承诺用语并引用原文；是否违规需人工确认",
         check=_r_exaggeration),
    # 广告—页面相关性（仅当提供广告数据）
    dict(id="AD-001", title="广告标题关键词在页面有对应", basis="optimizer_recommendation", dim="ad_relevance",
         device="both", severity="medium", method="广告标题词与页面文本匹配", check=_r_ad_headline),
    dict(id="AD-002", title="广告描述承诺在页面可兑现", basis="optimizer_recommendation", dim="ad_relevance",
         device="both", severity="medium", method="广告描述词与页面文本匹配", check=_r_ad_desc),
    dict(id="AD-003", title="广告与页面产品/主题一致", basis="optimizer_recommendation", dim="ad_relevance",
         device="both", severity="medium", method="广告与标题/H1 关键词重叠分析", check=_r_ad_product),
]


def run_rules(page: PageData, ad: Optional[AdContext] = None) -> List[Finding]:
    findings = []
    for r in RULES:
        try:
            status, evidence, recs, conf = r["check"](page, ad)
        except Exception as e:  # noqa: BLE001
            status, evidence, recs, conf = ("not_detected",
                                            [ev("rule", f"规则执行异常：{e}")], ["重新运行检测"], 0.3)
        findings.append(Finding(
            rule_id=r["id"], title=r["title"], basis_type=r["basis"], basis_label=BASIS_LABELS[r["basis"]],
            dimension=r["dim"], device=r["device"], severity=r["severity"], status=status,
            method=r["method"], evidence=evidence, recommendation=recs, confidence=round(conf, 2),
            owner=owner_of(r["id"], r["dim"]),
        ))
    return findings
