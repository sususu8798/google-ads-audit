"""分项评分与优先级。

评分口径（PRD 第 4.8 节）：
- 每个维度内，按已评估（pass/fail）规则计算得分 = 通过数 / (通过+失败) × 100
- not_detected / not_applicable 不计入分子也不计入分母（覆盖率单独展示）
- 广告—页面相关性维度在无广告数据时标记为“缺少投放数据”，不参与总分
- 政策风险单独展示，不可被高分抵消
"""
from typing import List, Optional

from . import config
from .rules import DIMENSION_LABELS, Finding


def score(findings: List[Finding]) -> dict:
    dims = {key: {"label": label, "weight": w} for key, label, w in config.settings.dimensions}
    for d in dims.values():
        d.update(passed=0, failed=0, applicable=0, not_detected=0, score=None, coverage=0.0)

    policy_fail = False
    policy_present = False

    for f in findings:
        d = dims.get(f.dimension)
        if not d:
            continue
        if f.basis_type == "official_policy":
            if f.status in ("pass", "fail"):
                policy_present = True
            if f.status == "fail":
                policy_fail = True
        if f.status == "pass":
            d["passed"] += 1
            d["applicable"] += 1
        elif f.status == "fail":
            d["failed"] += 1
            d["applicable"] += 1
        elif f.status == "not_detected":
            d["not_detected"] += 1

    overall_num = 0.0
    overall_den = 0.0
    for key, d in dims.items():
        total_rules = d["passed"] + d["failed"] + d["not_detected"]
        # 该维度是否有任何可评估规则
        if d["applicable"] > 0:
            d["score"] = round(d["passed"] / d["applicable"] * 100, 1)
            d["coverage"] = round(d["applicable"] / total_rules * 100, 1) if total_rules else 0.0
            overall_num += d["score"] * d["weight"]
            overall_den += d["weight"]
        else:
            # 全部 not_detected / not_applicable
            d["score"] = None
            d["coverage"] = 0.0
            d["note"] = "缺少投放数据" if key == "ad_relevance" else "需人工核对"

    overall = round(overall_num / overall_den, 1) if overall_den > 0 else None
    complete = overall_den >= sum(w for _, _, w in config.settings.dimensions) - 0.01

    if policy_fail:
        policy = {"status": "risk_found", "label": "发现风险线索"}
    elif policy_present:
        policy = {"status": "no_risk_detected", "label": "未发现已检测风险"}
    else:
        policy = {"status": "not_checked", "label": "未完成检测"}

    return {
        "dimensions": dims,
        "overall_score": overall,
        "score_complete": complete,
        "policy_risk": policy,
        "grade": grade_of(overall, dims),
    }


# ---------------------------------------------------------------------------
# 评分等级：综合分三档 + 维度否决
# ---------------------------------------------------------------------------
GRADE_LABELS = {"good": "良好", "mid": "待优化", "bad": "亟需整改"}
_GRADE_RANK = {"good": 3, "mid": 2, "bad": 1}


def _base_level(score: Optional[float]) -> Optional[str]:
    """按分数定档：≥80 良好 / 60-79 待优化 / <60 亟需整改。"""
    if score is None:
        return None
    if score >= 80:
        return "good"
    if score >= 60:
        return "mid"
    return "bad"


def _veto_level(score: Optional[float]) -> Optional[str]:
    """维度否决档：任一维度 <40 一票压到红；<60 最高只能黄；否则不触发。"""
    if score is None:
        return None
    if score < 40:
        return "bad"
    if score < 60:
        return "mid"
    return None


def grade_of(overall: Optional[float], dimensions: dict) -> dict:
    """综合分档与最差维度取更严的一档。

    解决「技术/转化拿满分、内容与信任崩塌却仍报良好」的虚高问题：
    一个维度明显不及格时，整体等级不得好于该维度对应的档位。
    """
    base = _base_level(overall)
    level = base
    capped_by: List[str] = []
    if base is not None:
        for key, d in (dimensions or {}).items():
            s = d.get("score")
            if s is None:
                continue
            v = _veto_level(s)
            if v is None:
                continue
            capped_by.append(d.get("label") or key)
            if _GRADE_RANK[v] < _GRADE_RANK[level]:
                level = v
    return {
        "level": level,
        "label": GRADE_LABELS.get(level, "无法评分"),
        "base_level": base,
        "base_label": GRADE_LABELS.get(base, "无法评分"),
        "capped_by": capped_by,
    }


def compute_priority(findings: List[Finding], ad_metrics: dict = None) -> dict:
    """规则驱动的机会优先级（PRD 第 4.7 节），透明可解释。"""
    reasons = []
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    # 收集失败/未检测规则
    fails = [f for f in findings if f.status == "fail"]
    # P0：可访问性严重问题 / 政策风险 / 表单“存在但”关键路径故障
    p0_rules = {"ACC-001", "ACC-005"}
    policy_fail = any(f.basis_type == "official_policy" and f.status == "fail" for f in findings)
    form_present = any(f.rule_id == "CONV-002" and f.status == "pass" for f in findings)
    form_broken = any(f.rule_id == "CONV-004" and f.status == "fail" for f in findings)
    if any(f.rule_id in p0_rules and f.status == "fail" for f in findings):
        reasons.append("页面无法访问或跳转到无关域名")
    if policy_fail:
        reasons.append("存在官方政策风险线索")
    if form_present and form_broken:
        reasons.append("表单存在但提交路径故障")

    if reasons:
        return {"priority": "P0", "label": "紧急", "reasons": reasons}

    # P1：高费用无转化 / CPA 明显偏高 + 具体可修复问题；或广告—页面严重不匹配
    ad = ad_metrics or {}
    cost = ad.get("cost")
    conversions = ad.get("conversions")
    cpa = ad.get("cpa")
    has_fixable = len(fails) > 0
    high_cost_zero_conv = (cost is not None and conversions == 0 and cost >= config.settings.p1_min_cost)
    if high_cost_zero_conv and has_fixable:
        reasons.append(f"费用 {cost} 且无转化，且发现 {len(fails)} 项可修复问题")
    elif any(f.rule_id in {"AD-001", "AD-002", "AD-003"} and f.status == "fail" for f in findings):
        reasons.append("广告与页面严重不匹配")
    if reasons:
        return {"priority": "P1", "label": "高", "reasons": reasons}

    # P2：存在改进机会但影响未证实
    if fails:
        reasons.append(f"发现 {len(fails)} 项页面/内容/体验改进机会（影响待验证）")
        return {"priority": "P2", "label": "中", "reasons": reasons}

    # P3：样本少或无明显问题
    if ad and (ad.get("clicks") is not None and ad.get("clicks") < config.settings.small_sample_clicks):
        reasons.append(f"广告样本量较小（点击 {ad.get('clicks')}），结论置信度有限")
        return {"priority": "P3", "label": "观察", "reasons": reasons}
    reasons.append("未发现明显页面问题")
    return {"priority": "P3", "label": "观察", "reasons": reasons}
