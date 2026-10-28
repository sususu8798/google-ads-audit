"""规则引擎与评分测试（使用合成 HTML，避免网络依赖）。"""
from src import html_extract, rules, scorer

GOOD_HTML = b"""
<html lang="en">
<head>
  <title>Industrial Molecular Sieve 3A Supplier</title>
  <meta name="description" content="High quality 3A molecular sieve for PSA nitrogen generation. Factory price, ISO certified.">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="canonical" href="https://example.com/p1">
</head>
<body>
  <h1>3A Molecular Sieve</h1>
  <p>Our 3A molecular sieve offers pore size 3 angstrom, used in PSA nitrogen. ISO 9001 certified. Size 1.6mm, capacity 22% wt.</p>
  <p>Contact us for quote and OEM service. Get a free sample.</p>
  <a href="mailto:sales@example.com">Email</a>
  <p>Phone +86 571 8888 8888. About our company founded in 2005.</p>
  <form><input name="email"><input name="name"><button type="submit">Get Quote</button></form>
  <img src="x.png" alt="3A molecular sieve picture">
</body>
</html>
"""

BAD_HTML = b"""
<html>
<head></head>
<body>
  <p>Under construction</p>
</body>
</html>
"""


def _find(findings, rid):
    return next(f for f in findings if f.rule_id == rid)


def test_good_page_passes_core_rules():
    p = html_extract.extract("https://example.com/p1", "https://example.com/p1", 200, GOOD_HTML)
    f = rules.run_rules(p)
    assert _find(f, "TECH-001").status == "pass"   # title present
    assert _find(f, "CONT-001").status == "pass"    # h1 present
    assert _find(f, "CONV-002").status == "pass"    # form present
    assert _find(f, "TECH-006").status == "pass"    # alt present
    assert _find(f, "MOB-001").status == "pass"     # viewport


def test_bad_page_fails_core_rules():
    p = html_extract.extract("https://example.com/bad", "https://example.com/bad", 200, BAD_HTML)
    f = rules.run_rules(p)
    assert _find(f, "TECH-001").status == "fail"    # no title
    assert _find(f, "CONT-001").status == "fail"    # no h1
    assert _find(f, "CONV-002").status == "fail"    # no form
    assert _find(f, "ACC-002").status == "fail"     # blank-ish content


def test_ad_relevance_not_applicable_without_ad():
    p = html_extract.extract("https://example.com/p1", "https://example.com/p1", 200, GOOD_HTML)
    f = rules.run_rules(p)
    for rid in ("AD-001", "AD-002", "AD-003"):
        assert _find(f, rid).status == "not_applicable"


def test_canonical_self_points_pass():
    p = html_extract.extract("https://example.com/p1", "https://example.com/p1", 200, GOOD_HTML)
    assert _find(rules.run_rules(p), "TECH-004").status == "pass"


def test_canonical_points_elsewhere_fails():
    html = GOOD_HTML.replace(b'<link rel="canonical" href="https://example.com/p1">',
                             b'<link rel="canonical" href="https://example.com/other">')
    p = html_extract.extract("https://example.com/p1", "https://example.com/p1", 200, html)
    r = _find(rules.run_rules(p), "TECH-004")
    assert r.status == "fail"
    assert "其他页面" in r.evidence[0]["text"]


def test_canonical_missing_fails():
    html = GOOD_HTML.replace(b'<link rel="canonical" href="https://example.com/p1">', b"")
    p = html_extract.extract("https://example.com/p1", "https://example.com/p1", 200, html)
    assert _find(rules.run_rules(p), "TECH-004").status == "fail"


def test_tech005_removed():
    p = html_extract.extract("https://example.com/p1", "https://example.com/p1", 200, GOOD_HTML)
    ids = [f.rule_id for f in rules.run_rules(p)]
    assert "TECH-005" not in ids
    assert all("html lang" not in f.title for f in rules.run_rules(p))


def test_score_computes_dimensions():
    p = html_extract.extract("https://example.com/p1", "https://example.com/p1", 200, GOOD_HTML)
    f = rules.run_rules(p)
    sc = scorer.score(f)
    assert sc["dimensions"]["accessibility"]["score"] is not None
    # 无广告数据，相关性维度应标记为缺少投放数据
    assert sc["dimensions"]["ad_relevance"]["score"] is None
    assert sc["dimensions"]["ad_relevance"].get("note") == "缺少投放数据"


def test_priority_p0_on_unreachable():
    p = html_extract.extract("https://example.com/x", "https://example.com/x", None, b"", error="connection failed", error_type="http")
    f = rules.run_rules(p)
    prio = scorer.compute_priority(f)
    assert prio["priority"] == "P0"


# ---------- 评分等级与维度否决 ----------
def _dims(**kw):
    base = {
        "accessibility": {"label": "可访问性与技术稳定性", "score": 90.0},
        "ad_relevance": {"label": "广告—页面相关性", "score": None},
        "content": {"label": "内容与产品信息", "score": 80.0},
        "conversion": {"label": "询盘转化体验", "score": 90.0},
        "mobile_perf": {"label": "移动端与性能", "score": 90.0},
        "trust": {"label": "信任与透明度", "score": 90.0},
    }
    base.update(kw)
    return base


def test_grade_all_healthy_is_good():
    from src.scorer import grade_of
    g = grade_of(88.0, _dims())
    assert g["level"] == "good" and g["label"] == "良好"
    assert g["capped_by"] == []


def test_grade_veto_by_medium_dimension():
    """综合 81 但内容/信任仅 50 → 等级压到待优化，并记录被谁压的。"""
    from src.scorer import grade_of
    g = grade_of(81.1, _dims(content={"label": "内容与产品信息", "score": 50.0},
                            trust={"label": "信任与透明度", "score": 50.0}))
    assert g["level"] == "mid" and g["label"] == "待优化"
    assert set(g["capped_by"]) == {"内容与产品信息", "信任与透明度"}


def test_grade_veto_under_40_forces_bad():
    from src.scorer import grade_of
    g = grade_of(85.0, _dims(trust={"label": "信任与透明度", "score": 35.0}))
    assert g["level"] == "bad" and g["label"] == "亟需整改"
    assert "信任与透明度" in g["capped_by"]


def test_grade_no_veto_when_dimension_at_60():
    from src.scorer import grade_of
    g = grade_of(81.0, _dims(content={"label": "内容与产品信息", "score": 62.0}))
    assert g["level"] == "good" and g["capped_by"] == []


def test_grade_none_when_no_score():
    from src.scorer import grade_of
    g = grade_of(None, {})
    assert g["level"] is None and g["label"] == "无法评分"


def test_grade_low_overall_stays_bad():
    from src.scorer import grade_of
    g = grade_of(55.0, _dims())
    assert g["level"] == "bad"


# ---------- CONT-004 价值主张：明确规则，不是“有内容就过” ----------
def _vp(html):
    p = html_extract.extract("https://example.com/vp", "https://example.com/vp", 200, html)
    return _find(rules.run_rules(p), "CONT-004")


# 正文铺垫段落（不含任何价值/行动信号词，仅用于满足“内容数量”门槛，隔离信号逻辑测试）
_BODY = ("This industrial product is widely used in air separation and gas drying processes. "
         "The spherical beads offer high crush strength and low dust generation during handling. "
         "Suitable for purification systems and dehydration of various gas streams. Stable performance "
         "under varying humidity conditions. Each batch is tested for adsorption capacity and particle "
         "size distribution before shipment to ensure consistent quality across orders.")


def test_value_prop_pass_with_two_signals_in_main_content():
    """正文主内容出现报价/询价/定制等强信号（≥2 个，含至少 1 强）→ 通过。"""
    html = (b"""
    <html><head><title>P</title></head><body>
      <h1>Product</h1>
      <p>""" + _BODY.encode() + b"""</p>
      <p>Factory price 10 USD. Contact us for quote and OEM service.</p>
      <footer>Copyright 2026</footer>
    </body></html>""")
    a = _vp(html)
    assert a.status == "pass"
    assert "报价" in a.evidence[0]["text"] or "quote" in a.evidence[0]["text"] or "price" in a.evidence[0]["text"]


def test_value_prop_fail_with_only_weak_signals():
    """正文仅价格/联系等弱信号（无报价/询价/定制等强信号）→ 不构成清晰价值主张。"""
    html = (b"""
    <html><head><title>P</title></head><body>
      <h1>Product</h1>
      <p>""" + _BODY.encode() + b"""</p>
      <p>Price 10 USD. This is a basic listing with little else.</p>
      <footer>Contact us via email</footer>
    </body></html>""")
    # footer 的 contact 在正文主内容之外；正文只剩 price 一个弱信号 → 失败
    a = _vp(html)
    assert a.status == "fail"
    assert "弱信号" in a.evidence[0]["text"] or "price" in a.evidence[0]["text"]


def test_value_prop_fail_with_no_signal():
    """正文无任何价值/行动信号 → 失败。"""
    html = (b"""
    <html><head><title>P</title></head><body>
      <h1>Product</h1>
      <p>""" + _BODY.encode() + b"""</p>
      <footer>Home About News</footer>
    </body></html>""")
    a = _vp(html)
    assert a.status == "fail"
    assert "未检测" in a.evidence[0]["text"] or "未出现" in a.evidence[0]["text"] or "任何" in a.evidence[0]["text"]


# ---------- PERF-001 页面体积：体积小 ≠ 合格 ----------
def _size(html):
    p = html_extract.extract("https://example.com/sz", "https://example.com/sz", 200, html)
    return _find(rules.run_rules(p), "PERF-001"), p


def test_page_size_small_but_thin_content_fails():
    """体积小 + 正文内容不足 → 空壳页特征，不应因“体积小”而通过。"""
    a, p = _size(b"""
    <html><head><title>P</title></head><body><h1>Product</h1><p>s f f</p></body></html>
    """)
    assert p.word_count < 200
    assert a.status == "fail"
    assert "内容缺失" in a.evidence[0]["text"]


def test_page_size_small_with_rich_content_passes():
    """体积小但正文充实 → 正常轻量页，通过并注明。"""
    body = ("<p>" + ("This industrial product line covers a wide range of specifications and applications. " * 20) + "</p>")
    a, p = _size((b"""
    <html><head><title>P</title></head><body><h1>Product</h1>""" + body.encode() + b"""</body></html>"""))
    assert p.word_count >= 200
    assert a.status == "pass"
    assert "正常轻量页" in a.evidence[0]["text"]


def test_page_size_oversized_fails():
    """HTML 文档 >2MB → 偏大/过大，建议控制在 2MB 内（直接构造 PageData，避免大负载解析）。"""
    from src.html_extract import PageData
    p = PageData(url="u", final_url="u", status_code=200, page_bytes=int(3.2 * 1024 * 1024), word_count=400)
    a = _find(rules.run_rules(p), "PERF-001")
    assert a.status == "fail"
    assert "2MB" in a.evidence[0]["text"]


def test_page_size_healthy_band_passes():
    """2MB 内的充实页面 → 处于健康区间，通过。"""
    from src.html_extract import PageData
    p = PageData(url="u", final_url="u", status_code=200, page_bytes=int(1.4 * 1024 * 1024), word_count=400)
    a = _find(rules.run_rules(p), "PERF-001")
    assert a.status == "pass"
    assert "健康区间" in a.evidence[0]["text"]

