"""robots.txt 匹配与三层屏蔽信号检测的单元测试。"""
import sys

sys.path.insert(0, ".")


def test_robots_disallow_star_group():
    from src.robots import disallows
    txt = "User-agent: *\nDisallow: /admin/\nDisallow: /private\n"
    assert disallows(txt, "/private/x") is True
    assert disallows(txt, "/admin/panel") is True
    assert disallows(txt, "/public/page") is None   # 无匹配规则 → 无法判断
    assert disallows(txt, "/adminabc") is None      # 前缀不匹配（/admin/ 带斜杠）


def test_robots_disallow_root_blocks_all():
    from src.robots import disallows
    txt = "User-agent: *\nDisallow: /\n"
    assert disallows(txt, "/anything") is True


def test_robots_allow_overrides_shorter_disallow():
    from src.robots import disallows
    txt = "User-agent: *\nDisallow: /\nAllow: /public/\n"
    # 最长匹配优先：/public/  Allow 比 / Disallow 更长 → 允许
    assert disallows(txt, "/public/page") is False


def test_robots_adsbot_specific_group():
    from src.robots import disallows
    txt = "User-agent: *\nDisallow:\n\nUser-agent: AdsBot\nDisallow: /no-ads/\n"
    assert disallows(txt, "/no-ads/x", agent="AdsBot") is True
    assert disallows(txt, "/no-ads/x", agent="*") is None


def test_robots_wildcard_and_end_anchor():
    from src.robots import disallows
    txt = "User-agent: *\nDisallow: /*.pdf$\n"
    assert disallows(txt, "/files/doc.pdf") is True
    assert disallows(txt, "/files/doc.pdfx") is None


def test_robots_none_when_missing():
    from src.robots import disallows
    assert disallows(None, "/x") is None


def test_robots_empty_disallow_means_allow_all():
    from src.robots import disallows
    txt = "User-agent: *\nDisallow:\n"
    # 空 Disallow = 允许全部，且没有任何有效规则 → None（无法判断）
    assert disallows(txt, "/x") is None


def test_r_robots_meta_noindex_fails():
    from src.rules import _r_robots
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, meta_robots="noindex, nofollow")
    status, ev, sug, _ = _r_robots(pd, None)
    assert status == "fail"
    assert "meta robots" in ev[0]["text"]


def test_r_robots_x_robots_tag_header_fails():
    """noindex 走响应头时 meta 查不到，必须能从 X-Robots-Tag 发现。"""
    from src.rules import _r_robots
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, meta_robots="", x_robots_tag="noindex")
    status, ev, sug, _ = _r_robots(pd, None)
    assert status == "fail"
    assert "X-Robots-Tag" in ev[0]["text"]


def test_r_robots_all_clean_passes():
    from src.rules import _r_robots
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, meta_robots="index, follow",
                  x_robots_tag="", robots_disallow=False)
    status, ev, sug, _ = _r_robots(pd, None)
    assert status == "pass"
    assert "robots.txt 允许抓取" in ev[0]["text"]
    assert "Search Console" in "".join(sug)


def test_r_robots_txt_disallow_fails():
    from src.rules import _r_robots
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, meta_robots="", robots_disallow=True)
    status, ev, sug, _ = _r_robots(pd, None)
    assert status == "fail"
    assert "robots.txt" in ev[0]["text"]


def test_r_exaggeration_quotes_matched_phrases():
    from src.rules import _r_exaggeration
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200,
                  extreme_claims=["全球领先", "100%", "保证"])
    status, ev, sug, _ = _r_exaggeration(pd, None)
    assert status == "not_detected"  # 命中≠违规，交人工核对而非未达标
    joined = "".join(e["text"] for e in ev)
    assert "全球领先" in joined and "100%" in joined
    assert "人工" in "".join(sug)


def test_r_exaggeration_lists_sentence_context():
    """TRUST-004 命中时逐条列出证据并附所在原文句子，便于定位。"""
    from src.rules import _r_exaggeration
    from src.html_extract import extract, PageData
    pd = PageData(url="u", final_url="u", status_code=200,
                  extreme_claims=["100%｜所在句子：Labeling accuracy up to 100% for carton boxes"])
    status, ev, sug, _ = _r_exaggeration(pd, None)
    assert status == "not_detected"  # 命中≠违规，交人工核对而非未达标
    joined = "".join(e["text"] for e in ev)
    assert "所在句子" in joined
    assert "Labeling accuracy up to 100%" in joined
    # 真实 HTML 提取也应带出句子上下文
    html = "<p>Our labeling machine achieves 100% accuracy on cartons.</p>".encode()
    pd2 = extract("u", "u", 200, html)
    assert pd2.extreme_claims and "所在句子" in pd2.extreme_claims[0]
    assert "accuracy" in pd2.extreme_claims[0]


def test_r_exaggeration_clean_passes():
    from src.rules import _r_exaggeration
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, extreme_claims=[])
    status, ev, sug, _ = _r_exaggeration(pd, None)
    assert status == "pass"
    assert "仅覆盖常见" in "".join(sug)


def test_r_unique_sampled_high_similarity_fails():
    from src.rules import _r_unique
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, site_similarity=0.87, site_similarity_sample=3)
    status, ev, sug, _ = _r_unique(pd, None)
    assert status == "fail"
    assert "87%" in ev[0]["text"]
    assert "抽样估算" in ev[0]["text"]


def test_r_unique_sampled_low_similarity_passes_with_caveat():
    from src.rules import _r_unique
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, site_similarity=0.31, site_similarity_sample=2)
    status, ev, sug, _ = _r_unique(pd, None)
    assert status == "pass"
    assert "跨站" in "".join(sug)


def test_r_unique_unsampled_is_not_detected():
    from src.rules import _r_unique
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, site_similarity=None)
    status, ev, sug, _ = _r_unique(pd, None)
    assert status == "not_detected"


def test_extreme_claim_regex_matches_common_phrases():
    from src.html_extract import EXTREME_CLAIM_RE
    text = "我们全球领先，保证100%有效，无效退款，行业第一的品质，价格最低。"
    hits = [m.group(0) for m in EXTREME_CLAIM_RE.finditer(text)]
    assert "全球领先" in hits
    assert "保证" in hits
    assert "100%" in hits
    assert "无效退款" in hits
    assert "行业第一" in hits
    assert "价格最低" in hits


def test_extreme_claim_regex_no_false_positive_on_normal_text():
    from src.html_extract import EXTREME_CLAIM_RE
    text = "本产品采用高纯度二氧化硅，粒径 2-4mm，符合 HG/T 2765.1-2005 标准，支持定制。"
    assert EXTREME_CLAIM_RE.findall(text) == []
