"""认证/规格与电话提取的防误报回归测试。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.html_extract import _extract_specs, _clean_phone
from bs4 import BeautifulSoup


def _soup(html):
    s = BeautifulSoup(html, "html.parser")
    for tag in s(["script", "style", "noscript"]):
        tag.decompose()
    return s


def test_specs_from_table_extracted():
    html = """
    <p>White silica gel is non-toxic, containing about 12-15% Al2O3 typically.</p>
    <table>
      <tr><th>Bulk density</th><td>0.75 kg/L</td></tr>
      <tr><th>Pore size</th><td>2.5 nm</td></tr>
      <tr><th>Particle size</th><td>2-5 mm</td></tr>
      <tr><th>Mesh</th><td>3-8 mesh</td></tr>
    </table>
    """
    specs, _ = _extract_specs(_soup(html), "")
    assert "2.5 nm" in specs
    assert "3-8 mesh" in specs or "8 mesh" in specs
    # 正文中的 15%（百分比已从单位表移除）不应出现
    assert "15%" not in specs


def test_specs_not_from_prose():
    html = """
    <h1>White Silica Gel 2023-06-29 White silica gel is a non-toxic and odorless
    desiccant containing at least 3% Al2O3 and about 12-15% Al2O3 typically.</h1>
    <p>It will selectively adsorb molecules smaller than 3 angstroms. Inquire now.</p>
    """
    assert _extract_specs(_soup(html), "")[0] == []


def test_specs_from_keyword_section():
    html = """
    <h3>Technical Parameters</h3>
    <div><p>Granularity: 1.6-2.5 mm; Loose bulk density: 0.75 g/ml</p></div>
    <p>Unrelated paragraph mentioning 29 watts and 04 litres.</p>
    """
    specs, _ = _extract_specs(_soup(html), "")
    assert any("mm" in s for s in specs)
    assert not any("watt" in s.lower() for s in specs)


def test_phone_filters_dates_and_serials():
    text = ("Call +86 182 7937 0572 or 0572-6666455. Posted 2023-06-29. Reg 2024029616. "
            "CAS 1318-02-1. Standard GB 2690-2012. Size 1.6-2.5 3.0-5.0 mm.")
    import re
    from src.html_extract import PHONE_RE
    phones = []
    for m in PHONE_RE.finditer(text):
        c = _clean_phone(m.group(0))
        if c and c not in phones:
            phones.append(c)
    joined = " | ".join(phones)
    assert "+86 182 7937 0572" in joined or "182 7937 0572" in joined
    assert "2023-06-29" not in joined
    assert "2024029616" not in joined
    assert "1318-02-1" not in joined
    assert "2690-2012" not in joined
    assert "3.0-5.0" not in joined


def test_canonical_from_link_tag():
    from src.html_extract import extract
    html = (b'<html><head><title>T</title>'
            b'<link rel="canonical" href="https://www.example.com/p/x"></head>'
            b'<body><h1>H</h1><p>Enough words here to pass the blank check comfortably and some more text added.</p></body></html>')
    pd = extract("https://www.example.com/p/x", "https://www.example.com/p/x", 200, html)
    assert pd.canonical == "https://www.example.com/p/x"


def test_canonical_meta_fallback():
    from src.html_extract import extract
    html = (b'<html><head><title>T</title>'
            b'<meta rel="canonical" href="https://www.example.com/meta"></head>'
            b'<body><h1>H</h1><p>Enough words here to pass the blank check comfortably and some more text added.</p></body></html>')
    pd = extract("https://www.example.com/meta", "https://www.example.com/meta", 200, html)
    assert pd.canonical == "https://www.example.com/meta"


def test_cert_api_not_false_positive_but_real_detected():
    from src.html_extract import extract, CERT_RE
    html = b'<html><head><title>D</title></head><body><h1>Cloud API</h1><p>We provide a REST API and an API key for access.</p></body></html>'
    pd = extract("https://api.example.com", "https://api.example.com", 200, html)
    assert "API" not in pd.certs
    assert bool(CERT_RE.search("Certified to API 5L standard"))
    assert bool(CERT_RE.search("API Q1 system"))


def test_render_blocking_excludes_async_defer_module():
    from src.html_extract import extract
    html = (b'<html><head><title>x</title>'
            b'<script src="/a.js"></script>'
            b'<script src="/b.js" async></script>'
            b'<script src="/c.js" defer></script>'
            b'<script src="/d.js" type="module"></script>'
            b'<link rel="stylesheet" href="/s.css">'
            b'<link rel="stylesheet" href="/p.css" media="print">'
            b'<style>@media (max-width:600px){.x{color:red}}</style>'
            b'</head><body><h1>H</h1><p>Enough words here to pass the blank check comfortably and some more text added now.</p></body></html>')
    pd = extract("https://x.com", "https://x.com", 200, html)
    assert pd.render_blocking_scripts == 1
    assert pd.render_blocking_stylesheets == 1
    assert pd.external_css == 2
    assert pd.has_media_queries is True


def test_link_protocol_relative_not_internal():
    from src.html_extract import extract
    html = (b'<html><head><title>t</title></head><body><h1>H</h1>'
            b'<p>word word word word word word word word word word word word word word word word word.</p>'
            b'<a href="//other-site.com/x">ext</a><a href="/about">int</a></body></html>')
    pd = extract("https://www.example.com/p", "https://www.example.com/p", 200, html)
    assert pd.links_internal == 1
    assert pd.links_external == 1


def test_alt_all_lazy_is_not_detected():
    from src.rules import _r_alt
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200,
                  images_total=5, images_empty_src=5, images_with_alt=0, images_missing_alt=0)
    status, *_ = _r_alt(pd, None)
    assert status == "not_detected"


def test_responsive_external_css_mentions_unparsed():
    from src.rules import _r_responsive
    from src.html_extract import PageData
    pd = PageData(url="u", final_url="u", status_code=200, external_css=3)
    status, ev, *_ = _r_responsive(pd, None)
    assert status == "not_detected"
    assert "外部样式表" in ev[0]["text"]


def test_specs_from_unit_column_table_with_rowspan():
    """带独立 Unit 列 + rowspan 跨行的参数表：单位必须与数值正确配对。"""
    from src.html_extract import _extract_specs
    from bs4 import BeautifulSoup
    html = """
    <table>
      <tr><th>Properties</th><th>Unit</th><th>Data</th></tr>
      <tr><td>Color</td><td>-</td><td>Blue</td></tr>
      <tr><td>SiO2 content</td><td>wt%</td><td>&ge;98.5</td></tr>
      <tr><td>Average pore diameter</td><td>nm</td><td>2-3</td></tr>
      <tr><td>Size</td><td>mm</td><td>2~4, 2.2~5, 4~8</td></tr>
      <tr><td rowspan="2">Adsorption capacity</td><td>wt%</td><td>RH=20%</td><td>&ge;8</td><td>&ge;8</td></tr>
      <tr><td>wt%</td><td>RH=35%</td><td>&ge;13</td><td>&ge;13</td></tr>
    </table>"""
    soup = BeautifulSoup(html, "html.parser")
    specs, image_tables = _extract_specs(soup, soup.get_text(" ", strip=True))
    joined = " | ".join(specs)
    assert image_tables == 0
    assert any("SiO2 content" in s and "wt%" in s and "98.5" in s for s in specs)
    assert any("Average pore diameter" in s and "nm" in s and "2-3" in s for s in specs)
    assert any(s.startswith("Size:") and "mm" in s for s in specs)
    # rowspan 行标签必须出现在两行上
    assert sum(1 for s in specs if s.startswith("Adsorption capacity")) == 2
    # 无数字的行（Color: - Blue）不应成为规格
    assert "Color" not in joined


def test_specs_kv_fields_for_js_rendered_table():
    """规格表由 JS 动态渲染时，正文 Formula/CAS No./National standard 必须被抓到。"""
    from src.html_extract import extract
    html = (b"<html><head><title>blue silica gel</title></head><body><h1>Blue Silica Gel</h1>"
            b"<p>Formula: SiO\xe2\x82\x82. Indicator: Yes. CAS No.: 7631-86-9. "
            b"National standard: HG/T 2765.1-2005. Application: precision instruments.</p>"
            b"<p>word word word word word word word word word word word word.</p></body></html>")
    pd = extract("https://ex.com/p", "https://ex.com/p", 200, html)
    joined = " | ".join(pd.specs)
    assert "Formula: SiO" in joined
    assert "CAS No.: 7631-86-9" in joined
    assert "HG/T 2765.1-2005" in joined
    # 值不能被句号截断成 HG/T 2765
    assert "HG/T 2765.1-2005" in joined


def test_image_only_table_counted_for_manual_check():
    """整张表只有图片：文本层读不到，应计入 image_tables 供规则标记人工核对。"""
    from src.html_extract import _extract_specs, PageData
    from src.rules import _r_specs
    from bs4 import BeautifulSoup
    html = '<table><tr><td><img src="a.webp"></td><td><img src="b.webp"></td></tr></table>'
    soup = BeautifulSoup(html, "html.parser")
    specs, image_tables = _extract_specs(soup, soup.get_text(" ", strip=True))
    assert specs == []
    assert image_tables == 1
    pd = PageData(url="u", final_url="u", status_code=200, specs=[], certs=[], image_tables=1)
    status, ev, sug, _ = _r_specs(pd, None)
    assert status == "not_detected"
    assert "图片" in ev[0]["text"]
    assert "人工" in "".join(sug)


def test_specs_not_polluted_by_body_numbers():
    """正文里的普通数字句子不应被当规格（回归：12-15% Al2O3 噪声）。"""
    from src.html_extract import _extract_specs
    from bs4 import BeautifulSoup
    html = ("<div><p>Delivery in 12-15% days for 3-5 pcs orders. Posted 2023-06-29. "
            "Reg 2024029616 white.</p></div>")
    soup = BeautifulSoup(html, "html.parser")
    specs, image_tables = _extract_specs(soup, soup.get_text(" ", strip=True))
    assert specs == []
    assert image_tables == 0


def test_decorative_images_excluded_from_content():
    """回归：装饰/图标/站标/空 src 懒加载不应计入「内容图片」。

    复现 iglobalwinsite.cn/product/ce-shi-13 的结构：1 个头部站标图 +
    5 个 footer 社交图标 + 1 个空 src 懒加载图 —— 真实内容图为 0，
    旧逻辑会把这 7 个 img 全当成「图片数量 7」抬高评分并误导证据。
    """
    from src.html_extract import extract
    from src.rules import _r_img_count, _r_alt
    html = b"""
    <html><head><title>t</title></head><body>
      <header><img src="/logo.png" alt="Tools store"></header>
      <p>some text</p>
      <img class="sideImg" src="" data-src="">
      <footer>
        <img src="/fb.png" alt="facebook">
        <img src="/in.png" alt="LinkedIn">
        <img src="/x.png" alt="X">
        <img src="/ig.png" alt="instgram">
        <img src="/pin.png" alt="Pinterest">
      </footer>
    </body></html>
    """
    pd = extract("https://x.com/p", "https://x.com/p", 200, html)
    assert pd.images_total == 7
    assert pd.images_empty_src == 1
    assert pd.images_decorative == 6
    assert pd.images_with_alt == 0
    assert pd.images_missing_alt == 0
    # 没有可读内容图 -> 该规则判 fail，证据说明真实内容图为 0
    st, ev, *_ = _r_img_count(pd, None)
    assert st == "fail"
    assert "可读内容图片" in ev[0]["text"]
    assert "0" in ev[0]["text"]
    # ALT 规则不应因装饰图缺失而判 fail
    st2, *_ = _r_alt(pd, None)
    assert st2 in ("not_applicable", "not_detected")


def test_content_image_counted_despite_decoratives():
    """含 1 张真内容图 + 若干装饰图时，内容图应被正确计入且 ALT 覆盖率正常。"""
    from src.html_extract import extract
    from src.rules import _r_img_count, _r_alt
    html = b"""
    <html><head><title>t</title></head><body>
      <header><img src="/logo.png" alt="brand"></header>
      <img src="/product.jpg" alt="3A molecular sieve picture">
      <footer><img src="/fb.png" alt="facebook"></footer>
    </body></html>
    """
    pd = extract("https://x.com/p", "https://x.com/p", 200, html)
    assert pd.images_total == 3
    assert pd.images_decorative == 2
    assert pd.images_with_alt == 1
    assert pd.images_missing_alt == 0
    st, ev, *_ = _r_img_count(pd, None)
    # 新阈值：内容图 1 张 < 3 → 偏少判 fail（图文结合建议 3–20 张）
    assert st == "fail"
    assert "可读内容图片 1" in ev[0]["text"]
    assert "偏少" in ev[0]["text"]
    st2, ev2, *_ = _r_alt(pd, None)
    assert st2 == "pass"
    assert "内容图片 ALT 覆盖率 100%" in ev2[0]["text"]


def test_social_icon_via_link_href_is_decorative():
    """回归（iglobalwin「iglobalwin X」漏网）：alt/src 无社交关键词的社交图标，
    外层 <a href> 指向社交域名 → 应判装饰图，不冒充内容图抬高 ALT 覆盖率到 100%。"""
    from src.html_extract import extract
    from src.rules import _r_img_count
    html = b"""
    <html><head><title>t</title></head><body>
      <header><img src="https://cdn.example.com/a%2F" alt="Tools store"></header>
      <div class="ImageCollectCell">
        <a href="https://www.facebook.com/iglobalwin"><img src="https://cdn.example.com/b%2F" alt="iglobalwin facebook"></a>
        <a href="https://x.com/iglobalwin"><img src="https://cdn.example.com/b%2F" alt="iglobalwin X"></a>
      </div>
      <img src="/product.jpg" alt="product photo">
    </body></html>
    """
    pd = extract("https://x.com/p", "https://x.com/p", 200, html)
    # Tools store 命中 store 关键词 + 2 个社交图标（facebook alt 命中、X 靠外链 href）→ 3 装饰
    assert pd.images_decorative == 3
    assert pd.images_with_alt + pd.images_missing_alt == 1  # 仅 product.jpg
    st, ev, *_ = _r_img_count(pd, None)
    assert st == "fail"  # 内容图 1 张 < 3 → 偏少
    assert "可读内容图片 1" in ev[0]["text"]
    assert "偏少" in ev[0]["text"]


def test_img_count_reasonable_range():
    """新阈值：内容图 3–20 张为 pass，<3 偏少 fail，>20 偏多 fail。"""
    from src.html_extract import extract
    from src.rules import _r_img_count

    def imgs(n):
        return b"".join(b'<img src="/p%d.jpg" alt="p">' % i for i in range(n))

    for n, expected in [(3, "pass"), (20, "pass"), (2, "fail"), (21, "fail")]:
        html = b"<html><head><title>t</title></head><body>" + imgs(n) + b"</body></html>"
        pd = extract("https://x.com/p", "https://x.com/p", 200, html)
        st, ev, *_ = _r_img_count(pd, None)
        assert st == expected, f"content={n}: {st}"
        if expected == "pass":
            assert "合理区间 3–20" in ev[0]["text"]
        elif n < 3:
            assert "偏少" in ev[0]["text"]
        else:
            assert "偏多" in ev[0]["text"]


def test_word_count_excludes_template_boilerplate():
    """回归：导航/页脚/表单/SVG 模板文字不计入正文词数。

    复现 iglobalwinsite.cn/product/ce-shi-13 的「正文约 230 词/字」假象：
    实际全是导航菜单、页脚公司信息、表单标签和 Sketch 导出的 SVG 噪声，
    剥离后真实正文仅几十词，ACC-002 应如实判「内容偏少」并引用内容开头片段。
    """
    from src.html_extract import extract
    from src.rules import _r_not_blank
    html = b"""
    <html><head><title>t</title></head><body>
      <div class="header"><svg><text>Created with Sketch.</text></svg> LOGO
        <a href="/">HOME</a> <a href="/p">PRODUCT</a> <a href="/c">Contact</a></div>
      <div class="main">
        <h1>Product Type Twos3</h1>
        <p>s f f</p>
        <form><label>Name</label><input><label>Message</label><button>Send Inquiry Now</button></form>
      </div>
      <div class="footer">
        <a href="/a">fb</a><a href="/b">in</a><a href="/c">x</a><a href="/d">ig</a><a href="/e">pin</a>
        <p>Shanghai xx Technology Co., Ltd sales@x.com Tel:+86 131 0000 2223</p>
      </div>
    </body></html>
    """
    pd = extract("https://x.com/p", "https://x.com/p", 200, html)
    # 模板文字（HOME/PRODUCT/表单标签/页脚公司信息/SVG）全部不计入正文
    assert pd.word_count < 20
    assert "Product" in pd.text_sample and "s f f" in pd.text_sample
    st, ev, *_ = _r_not_blank(pd, None)
    assert st == "fail"
    assert "内容开头" in ev[0]["text"]
    # 证据里能看到剔除模板文字的说明
    assert "模板" in ev[0]["text"]



def test_missing_alt_lists_all_image_urls():
    """ALT 缺失时证据应列出全部缺失地址（绝对地址），不再是「仅列前 8 张」。"""
    from src.html_extract import extract
    from src.rules import _r_alt
    html = b"""
    <html><head><title>t</title></head><body>
      <header><img src="/logo.png" alt="brand"></header>
      <img src="/img/a.jpg">
      <img src="/img/b.jpg">
      <img src="/img/c.jpg">
      <img src="/img/d.jpg">
      <img src="/img/e.jpg">
      <img src="/img/f.jpg">
      <img src="/img/g.jpg">
      <img src="/img/h.jpg">
      <img src="/img/i.jpg">
      <img src="/img/j.jpg">
      <footer><img src="/fb.png" alt="facebook"></footer>
    </body></html>
    """
    pd = extract("https://x.com/p", "https://x.com/p", 200, html)
    assert pd.images_missing_alt == 10
    assert pd.images_missing_alt_list == [f"https://x.com/img/{c}.jpg" for c in "abcdefghij"]
    st, evs, *_ = _r_alt(pd, None)
    assert st == "fail"
    joined = " ".join(e["text"] for e in evs)
    for c in "abcdefghij":
        assert f"https://x.com/img/{c}.jpg" in joined  # 10 张全部列出
    assert "仅列前" not in joined  # 不带截断说明
    assert "此处列出" not in joined  # 未触存储上限，也不带上限说明


def test_js_spec_tab_marked_not_detected():
    """选项卡头在静态 HTML、内容由 JS 注入：应记入 spec_tabs 供规则标记人工核对。"""
    from src.html_extract import extract, PageData
    from src.rules import _r_specs
    html = (
        '<div class="tab"><div class="tab_header">'
        '<div class="tab_header_btn active" title="Key Features">Key Features</div>'
        '<div class="tab_header_btn" title="Technical Specifications">Technical Specifications</div>'
        '</div><div class="tab_body"></div></div>'  # 内容 JS 注入，静态为空
    )
    pd = extract("u", "u", 200, html.encode())
    assert pd.specs == [] and pd.certs == []
    assert pd.spec_tabs == ["Technical Specifications"]
    status, ev, sug, _ = _r_specs(pd, None)
    assert status == "not_detected"
    assert "JS" in ev[0]["text"] or "动态" in ev[0]["text"]
    assert "人工" in "".join(sug)


def test_static_spec_table_still_passes():
    """规格表就在静态 HTML 里时应照常 pass，不受 spec_tabs 影响。"""
    from src.html_extract import extract
    html = (
        '<table><tr><th>Item</th><th>Parameter</th></tr>'
        '<tr><td>Packing Speed</td><td>30-80 packs/min</td></tr></table>'
    )
    pd = extract("u", "u", 200, html.encode())
    assert pd.specs, "静态规格表应提取到参数"
    assert pd.spec_tabs == []
