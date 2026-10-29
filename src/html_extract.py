"""从 HTML 中提取落地页可诊断信息。"""
import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s().]{6,}\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 认证/资质关键词。注意：API 必须后跟「字母+数字」或数字（如 API 5L / API Q1 / API 11D1），
# 否则会误把正文里的 "REST API" / "API key" 当成认证；ISO 同样要求后跟数字。
CERT_RE = re.compile(
    r"\b(ISO\s?\d{3,}(?::\d{1,4})?|CE|RoHS|FDA|UL|FCC|REACH|GMP|SGS|MSDS|API\s?[A-Z]?\d{1,3}[A-Z]?)\b",
    re.I,
)
# 规格只认无歧义的明确单位（去掉 m/g/t/L/V/W/A/% 等极易误配正文与日期的单字母）；
# 且只在「参数表 / 规格语境」里提取，避免把正文句子里的数字碎片当规格。
SPEC_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?\s?(?:g/ml|g/mL|mm|cm|km|kg|mg|ml|°C|MPa|kPa|GPa|μm|µm|nm|ppm|mesh|inch|Hz|kHz|MHz|kW|kV))(?![\w])",
    re.I,
)
# 规格语境：参数表、定义列表，或含关键词的标题所在区块
SPEC_SECTION_RE = re.compile(
    r"specification|specs?\b|technical\s+(?:data|parameter)s?|product\s+(?:data|parameter)s?|properties|参数|规格|技术指标|性能特点",
    re.I,
)
# 单元格整体就是一个「纯单位」（用于识别带独立 Unit 列的参数表）。
# 只收多字符/符号单位，刻意排除 m/g/s/h/A/W/V/N 等单字母（S/M/L 尺码、A/B/C 等级误判风险高）。
PURE_UNIT_RE = re.compile(
    r"^(?:wt\.?\s?%|%|°\s?C|℃|nm|mm|cm|km|kg|mg|μg|ug|ml|kPa|MPa|GPa|Pa|Hz|kHz|MHz|kW|kV|"
    r"mesh|ppm|psi|bar|rpm|dB|RH|inch|pcs|件|个|台|只|米|厘米|毫米|微米|千克|克|升|毫升|摄氏度)$",
    re.I,
)
# 只有标点/占位符的单元格（如 "/"、"-"、"——"）应视为空
PUNCT_ONLY_RE = re.compile(r"^[\s/\-–—_,;:、，。.]+$")
# 装饰/图标/logo 类图片判定：src/alt/class/id 命中下列关键词，即视为非内容图（社交图标、站标、分享按钮等）。
# 这类图不计入「内容图片」，避免把 footer 社交图标、站标当成产品/场景图抬高评分或误导证据。
DECOR_IMG_RE = re.compile(
    r"(?:facebook|linkedin|twitter|\bx\.com\b|t\.co|instagram|instgram|pinterest|youtube|"
    r"whatsapp|telegram|wechat|weixin|weibo|tiktok|snapchat|reddit|\bvk\.com\b|line\.me|"
    r"social|share|logo|brand|symbol|emblem|icon|badge|banner|favicon|avatar|"
    r"qr|qrcode|menu|toggle|hamburger|cart|search|arrow|chevron|spinner|loader|"
    r"placeholder|spacer|pixel|tracking|ad-|promo|payment|pay\b|currency|flag|store)",
    re.I,
)
# 外层 <a> 链接指向社交域名 → 该 img 判为社交图标（装饰图）。
# 比 alt/src 关键词更可靠：图床 URL 和 "iglobalwin X" 这类 alt 没有关键词，但 <a href> 暴露真实用途。
SOCIAL_LINK_RE = re.compile(
    r"(?:facebook\.com|linkedin\.com|twitter\.com|\bx\.com\b|instagram\.com|pinterest\.com|"
    r"youtube\.com|youtu\.be|wa\.me|whatsapp\.com|t\.me|weixin\.qq\.com|weibo\.com|tiktok\.com)",
    re.I,
)
# 模板/导航类容器判定：class 或 id 命中即整块剔除，不计入正文词数。
# 套壳模板站的导航/页脚常由 div 搭建（无语义标签），只能靠命名特征 + 链接密度兜底。
NAVLIKE_RE = re.compile(
    r"nav|menu|footer|header|sidebar|breadcrumb|crumb|copyright|social|topbar|pagination|lang|currency",
    re.I,
)
# 参数表表头关键词（用于判断一张表是不是规格表）
SPEC_TABLE_HEADER_RE = re.compile(
    r"specification|specs?\b|technical\s+(?:data|parameter)s?|propert|parameter|unit|单位|参数|规格|技术指标|型号|性能|项目|data",
    re.I,
)
# 正文中的「标签: 值」型规格字段（Formula / CAS No. / National standard / 型号 ...）。
# 这是 JS 动态渲染规格表的页面里唯一可读的参数来源，必须抓出来。
# 值部分允许小数点（2765.1-2005），但遇到「句号+空白」即停止，避免一句话吞掉后续字段。
KV_SPEC_RE = re.compile(
    r"(?<![\w])(Formula|CAS(?:\s?No\.?)?|National\s?standard|Standard|Model(?:\s?No\.?)?|Material|Purity|Grade|"
    r"Capacity|Voltage|Power|Weight|Dimension|Specification|Indicator|Application|"
    r"型号|材质|容量|电压|功率|重量|尺寸|纯度|规格|标准)\s*[:：]\s*((?:[^\n;。.]|\.(?!\s)){1,80})",
    re.I,
)
# 日期形如 2023-06-29 / 2023.06 / 2023年6月 —— 不应被当电话
DATE_LIKE_RE = re.compile(r"^(?:19|20)\d{2}[-/.年]\s?\d{1,2}(?:[-/.月]\s?\d{1,2})?日?$")
# 极端/无法验证承诺用语。命中只代表「出现这类措辞」，需人工判断是否构成夸大或违法宣传，
# 因此证据引用原文片段，规则状态也明确标注需人工确认。
EXTREME_CLAIM_RE = re.compile(
    r"(?:全球领先|世界领先|行业第一|全国第一|销量第一|第一名|最好|最佳|最强|最优|"
    r"100\s?%|百分百|绝对|保证|终身|永久|永不|无敌|治愈|根治|疗效|"
    r"无效退款|假一赔|最低价|最便宜|价格最低|全网最低|唯一|独家|首创|零风险|无风险|"
    r"史上|极限|极致|顶级|至尊|王牌|神器|秒杀|暴涨)",
    re.I,
)


def _clean_phone(candidate: str) -> Optional[str]:
    s = candidate.strip()
    if not s:
        return None
    if DATE_LIKE_RE.match(s):
        return None
    # 以年份起始的碎片（如 "2023-06-29 3"：正则跨过日期吞了后续数字）一律排除
    if re.match(r"^(?:19|20)\d{2}\s?[-/.年]", s):
        return None
    # 含小数点的是参数区间（如粒径 "1.6-2.5 3.0-5.0"），不是电话
    if re.search(r"\d\.\d", s):
        return None
    # CAS 号（化学品登记号，如 1318-02-1）
    if re.match(r"^\d{2,7}-\d{2}-\d$", s):
        return None
    # 标准号尾部年份（如 GB 2690-2012）
    m = re.search(r"-(\d{4})$", s)
    if m and m.group(1)[:2] in ("19", "20"):
        return None
    digits = re.sub(r"\D", "", s)
    # 形如 2024029616 的备案号/流水号：纯数字且以 19/20 开头的 9 位以上串，排除
    if s.isdigit() and len(digits) >= 9 and digits[:2] in ("19", "20"):
        return None
    if len(digits) < 7:
        return None
    return s


def _table_grid(table) -> List[List[str]]:
    """把 table 展开成矩形文本网格，正确处理 rowspan / colspan。

    规格表常用跨行跨列（如「吸附容量」跨 4 行、Unit 列跨多行），
    直接 get_text 会把单位与数值拆散，导致「2-3」与「nm」无法配对。
    """
    raw_rows: List[List[tuple]] = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"], recursive=False):
            txt = cell.get_text(" ", strip=True)
            try:
                rs = max(1, int(cell.get("rowspan", 1) or 1))
            except (TypeError, ValueError):
                rs = 1
            try:
                cs = max(1, int(cell.get("colspan", 1) or 1))
            except (TypeError, ValueError):
                cs = 1
            cells.append((txt, rs, cs))
        if cells:
            raw_rows.append(cells)

    grid: List[List[str]] = []
    pending: dict = {}  # col -> (text, remaining_rows)
    for cells in raw_rows:
        row: List[str] = []
        col = 0
        for txt, rs, cs in cells:
            while col in pending:
                t, rem = pending.pop(col)
                row.append(t)
                if rem > 1:
                    pending[col] = (t, rem - 1)
                col += 1
            for k in range(cs):
                row.append(txt)
                if rs > 1:
                    pending[col + k] = (txt, rs - 1)
            col += cs
        while col in pending:
            t, rem = pending.pop(col)
            row.append(t)
            if rem > 1:
                pending[col] = (t, rem - 1)
            col += 1
        grid.append(row)
    return grid


def _specs_from_table(table, add, note_image_table) -> None:
    """从单张表提取规格。

    - 规格表（表头含 Unit/Specification/参数…或存在 ≥2 个纯单位单元格）→ 按行取「标签: 数值 单位」
    - 普通表 → 仍扫描内联「数值+单位」（如 5mm）
    - 整张表只有图片没有文本 → 回调 note_image_table（规格被做成图片，需人工核对）
    """
    grid = _table_grid(table)
    if not grid:
        return
    flat = " ".join(" ".join(r) for r in grid).strip()
    if not flat:
        if table.find("img"):
            note_image_table()
        return

    unit_cells = sum(1 for r in grid for c in r if c and PURE_UNIT_RE.match(c))
    header = " ".join(grid[0])
    is_spec_table = bool(SPEC_TABLE_HEADER_RE.search(header)) or unit_cells >= 2
    if not is_spec_table:
        for m in SPEC_RE.finditer(flat):
            add(m.group(1))
        return

    # 表头行无数值 → 视为表头跳过；否则第一行也是数据
    start = 0 if any(ch.isdigit() for ch in header) else 1
    for r in grid[start:]:
        cells = [c for c in r if c and not PUNCT_ONLY_RE.match(c)]
        if len(cells) < 2:
            continue
        if not any(ch.isdigit() for c in cells for ch in c):
            continue
        label = cells[0][:40]
        rest = " ".join(cells[1:])[:70]
        add(f"{label}: {rest}")


def _specs_from_dl(dl, add) -> None:
    """定义列表 <dt>名称</dt><dd>值</dd> 也是常见规格载体。"""
    for dt in dl.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        k = dt.get_text(" ", strip=True)
        v = dd.get_text(" ", strip=True)
        if k and v and any(ch.isdigit() for ch in v):
            add(f"{k[:40]}: {v[:70]}")


def _trim_kv(v: str) -> str:
    v = v.strip().rstrip(".。")
    if len(v) > 60:
        cut = max(v.rfind(",", 0, 60), v.rfind(" ", 0, 60))
        v = (v[:cut] if cut > 12 else v[:60]).rstrip(" ,;，、")
    return v


def _extract_specs(soup: BeautifulSoup, text: str):
    """提取规格参数。返回 (specs, image_tables)。

    specs 来源按可信度排序：
    1. 参数表 / 定义列表（结构化，最可靠）
    2. 正文「Formula: SiO₂」「CAS No.: 7631-86-9」这类标签值字段
    3. 规格关键词标题所在区块的内联「数值+单位」

    只从上述语境提取，绝不扫全文，避免把正文句子里的数字碎片当规格。
    image_tables = 整张表只有图片、没有文本的表格数（规格被做成图片，文本层读不到）。
    """
    found: List[str] = []
    seen: set = set()
    image_tables = 0

    def add(s: str) -> None:
        s = s.strip().strip(":：,，")
        if s and s not in seen:
            seen.add(s)
            found.append(s)

    def note_image_table() -> None:
        nonlocal image_tables
        image_tables += 1

    for t in soup.find_all(["table", "dl"]):
        if t.name == "table":
            _specs_from_table(t, add, note_image_table)
        else:
            _specs_from_dl(t, add)
        if len(found) >= 15:
            break

    # 正文 KV 型规格字段（JS 渲染规格表的页面上这是唯一可读来源）
    if len(found) < 15:
        for m in KV_SPEC_RE.finditer(text or ""):
            add(f"{m.group(1).strip()}: {_trim_kv(m.group(2))}")
            if len(found) >= 15:
                break

    # 规格关键词标题所在区块
    if len(found) < 15:
        blocks: List[str] = []
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "summary"]):
            try:
                ht = h.get_text(" ", strip=True)
            except Exception:  # noqa: BLE001
                continue
            if not (ht and SPEC_SECTION_RE.search(ht)):
                continue
            parent = h.find_parent(["section", "div", "article", "details", "td", "li"])
            if parent is not None:
                blocks.append(parent.get_text(" ", strip=True))
            else:
                parts: List[str] = []
                for sib in h.next_siblings:
                    name = getattr(sib, "name", None)
                    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                        break
                    parts.append(sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib))
                    if sum(len(p) for p in parts) > 4000:
                        break
                if parts:
                    blocks.append(" ".join(parts))
        for blk in blocks:
            for m in SPEC_RE.finditer(blk):
                add(m.group(1))
            if len(found) >= 15:
                break

    # 仅含图片的表格数量一并返回，由 extract() 写入 PageData
    return found[:15], image_tables


@dataclass
class PageData:
    url: str
    final_url: str
    status_code: Optional[int]
    title: str = ""
    h1_list: List[str] = field(default_factory=list)
    meta_description: str = ""
    canonical: str = ""
    meta_robots: str = ""
    viewport: str = ""
    html_lang: str = ""
    # 资源
    images_total: int = 0
    images_with_alt: int = 0
    images_missing_alt: int = 0
    # 缺失 ALT 的内容图片绝对地址（列出全部，落地页通常 3–20 张；设 200 上限防 pathological 超大页）
    images_missing_alt_list: List[str] = field(default_factory=list)
    images_empty_src: int = 0
    images_decorative: int = 0  # 装饰/图标/logo 类图片（社交图标、站标、footer 内图片等，不计入内容图）
    links_total: int = 0
    links_internal: int = 0
    links_external: int = 0
    # 表单 / CTA
    forms: int = 0
    form_inputs: int = 0
    form_has_submit: bool = False
    cta_buttons: List[str] = field(default_factory=list)
    # 文本
    text_length: int = 0
    word_count: int = 0
    text_sample: str = ""  # 剔除模板噪声后的正文开头片段（供证据展示，便于人工核对实质内容）
    main_text: str = ""  # 剔除模板噪声后的主内容全文（供价值主张/公司信息等文本信号判定，避免页眉/页脚/表单标签误触发）
    text: str = ""
    # 信任信号
    phones: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    certs: List[str] = field(default_factory=list)
    specs: List[str] = field(default_factory=list)
    # 整张表只有图片、没有文本的表格数（规格表被做成图片时文本层读不到，需人工核对）
    image_tables: int = 0
    # HTTP 响应头 X-Robots-Tag（noindex 也可通过响应头设置，meta 里查不到）
    x_robots_tag: str = ""
    # robots.txt 是否禁止抓取该路径：None=未检查/无法判断，True=禁止，False=允许
    robots_disallow: Optional[bool] = None
    # 站内抽样相似度（0~1）与抽样页数；None=未抽样
    site_similarity: Optional[float] = None
    site_similarity_sample: int = 0
    # 同域内页链接（供相似度抽样使用，最多 20 条）
    internal_links: List[str] = field(default_factory=list)
    # 命中的极端/无法验证承诺用语原文片段
    extreme_claims: List[str] = field(default_factory=list)
    # 性能
    page_bytes: int = 0
    render_blocking_scripts: int = 0
    render_blocking_stylesheets: int = 0
    external_css: int = 0
    has_media_queries: bool = False
    # 原始
    error: Optional[str] = None
    error_type: Optional[str] = None


def _count_words(text: str) -> int:
    # 中文按字符粗略计，英文按词计
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]+", text))
    return cjk + en


def _cls_id(el) -> str:
    """取元素 class+id 签名；decompose 后的残留节点 attrs 为 None，须防御。"""
    try:
        if el.attrs is None:
            return ""
        c = el.get("class") or []
        c = " ".join(c) if isinstance(c, list) else str(c)
        return (c + " " + (el.get("id") or "")).strip()
    except Exception:  # noqa: BLE001
        return ""


# 联系动作链接：mailto / tel / WhatsApp（含 api.whatsapp.com 跳转与 wa.me 短链）。
# 这些是「联系销售」动作入口而非页面导航，统计链接密度时应剔除。
CONTACT_LINK_RE = re.compile(r"^(?:mailto:|tel:|whatsapp://)|(?:^|//|@)(?:wa\.me/|api\.whatsapp\.com|chat\.whatsapp\.com)", re.I)


def _is_contact_link(a) -> bool:
    try:
        href = a.get("href") or ""
        return bool(CONTACT_LINK_RE.search(href))
    except Exception:  # noqa: BLE001
        return False


def _content_text(soup) -> str:
    """主内容文本：剔除 SVG 图标、表单、导航/页眉/页脚类模板块与高链接密度区块。

    与整页 get_text 的区别：导航菜单、页脚公司信息、表单标签、「Created with Sketch」
    这类模板噪声不计入正文词数，避免套壳模板页靠模板文字凑出「内容充实」的假象。
    在重新解析的副本上操作，不影响原 soup 的规格表提取。
    """
    s = BeautifulSoup(str(soup), "html.parser")
    for t in s(["svg", "form", "nav", "footer", "header", "aside", "head"]):
        t.decompose()
    for t in s.find_all(True):
        if t.decomposed:
            continue
        sig = _cls_id(t).lower()
        if sig and NAVLIKE_RE.search(sig):
            try:
                t.decompose()
            except Exception:  # noqa: BLE001
                pass
    # 链接密度：≥5 个链接且链接文字占块内文字 ≥60% → 导航/链接列表
    for t in s.find_all(["div", "section", "ul"]):
        try:
            if t.decomposed:
                continue
            # 只统计「真实页面链接」：排除联系动作链接（mailto:/tel:/WhatsApp）与
            # 非导航占位链接（空 href / javascript: / #）——建站工具常把大段联系文本
            # 包在 javascript:; 假链接里，不排除会把「Online Inquiry」询价区块整块误删
            links = []
            for a in t.find_all("a"):
                href = (a.get("href") or "").strip()
                if not href or href.startswith(("javascript:", "#")) or _is_contact_link(a):
                    continue
                links.append(a)
            if len(links) >= 5:
                total = _count_words(t.get_text(" ", strip=True))
                in_links = _count_words(" ".join(a.get_text(" ", strip=True) for a in links))
                if total and in_links / total >= 0.6:
                    t.decompose()
        except Exception:  # noqa: BLE001
            pass
    return s.get_text(" ", strip=True)


def extract(page_url: str, final_url: str, status_code, content: bytes, error=None, error_type=None,
            headers=None) -> PageData:
    pd = PageData(url=page_url, final_url=final_url, status_code=status_code,
                  error=error, error_type=error_type, page_bytes=len(content or b""))
    if error or not content:
        return pd

    try:
        soup = BeautifulSoup(content, "html.parser")
    except Exception:  # noqa: BLE001
        pd.error = "HTML 解析失败"
        return pd

    # title
    t = soup.find("title")
    pd.title = (t.get_text(strip=True) if t else "") or ""

    # h1
    pd.h1_list = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]

    # meta
    def meta_content(attr, val):
        m = soup.find("meta", attrs={attr: val})
        return m.get("content", "").strip() if m and m.get("content") else ""

    pd.meta_description = meta_content("name", "description")
    pd.meta_robots = meta_content("name", "robots")
    # canonical：标准写法是 <link rel="canonical" href>，优先取之；兜底 <meta rel="canonical">（URL 在 href）
    link_canon = soup.find("link", attrs={"rel": "canonical"})
    if link_canon and link_canon.get("href"):
        pd.canonical = link_canon.get("href").strip()
    else:
        meta_canon = soup.find("meta", attrs={"rel": "canonical"})
        pd.canonical = ((meta_canon.get("href") or meta_canon.get("content") or "").strip()
                        if meta_canon else "")
    pd.viewport = meta_content("name", "viewport")
    pd.html_lang = soup.find("html").get("lang", "").strip() if soup.find("html") else ""

    # images + alt（区分内容图 / 装饰图标 / 空 src 懒加载）
    imgs = soup.find_all("img")
    pd.images_total = len(imgs)
    for img in imgs:
        alt = img.get("alt")
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.strip() == "":
            pd.images_empty_src += 1
            continue
        cls = img.get("class")
        cls = " ".join(cls) if isinstance(cls, list) else (cls or "")
        sig = " ".join(filter(None, [src, alt or "", cls, img.get("id") or ""]))
        in_decor_container = img.find_parent(["footer", "header", "nav", "aside"]) is not None
        social_parent = img.find_parent("a", href=True)
        in_social_link = social_parent is not None and bool(SOCIAL_LINK_RE.search(social_parent.get("href") or ""))
        if DECOR_IMG_RE.search(sig) or in_decor_container or in_social_link:
            # 装饰/图标/logo 类图片：不计入内容图，也不纳入 ALT 覆盖率分母
            pd.images_decorative += 1
            continue
        # 内容图片：计入 ALT 覆盖率
        if alt and alt.strip():
            pd.images_with_alt += 1
        else:
            pd.images_missing_alt += 1
            if len(pd.images_missing_alt_list) < 200:
                try:
                    pd.images_missing_alt_list.append(urljoin(final_url, src.strip()))
                except ValueError:
                    pd.images_missing_alt_list.append(src.strip())

    # links
    base_host = urlparse(final_url).hostname or ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        pd.links_total += 1
        # 补全为绝对地址（含协议相对 //host）
        if href.startswith("http"):
            resolved = href
        elif href.startswith("//"):
            resolved = "https:" + href
        else:
            resolved = "http://" + base_host + href
        host = urlparse(resolved).hostname
        if host and host == base_host:
            pd.links_internal += 1
            # 保留同域内页链接（去重、去掉锚点、上限 20），供站内相似度抽样
            clean = resolved.split("#", 1)[0]
            if (clean and clean not in pd.internal_links and clean != final_url
                    and len(pd.internal_links) < 20):
                pd.internal_links.append(clean)
        else:
            pd.links_external += 1

    # forms / CTA
    forms = soup.find_all("form")
    pd.forms = len(forms)
    for f in forms:
        inputs = f.find_all(["input", "textarea", "select"])
        pd.form_inputs += len(inputs)
        if f.find(["button", "input"]):
            for el in f.find_all(["button", "input"]):
                ttype = (el.get("type") or "").lower()
                if el.name == "button" or ttype in ("submit", "image"):
                    pd.form_has_submit = True

    # CTA buttons (button/input submit/a with cta-like text)
    cta_texts = []
    for el in soup.find_all(["button", "a"]):
        txt = el.get_text(strip=True)
        if txt and len(txt) <= 40:
            cta_texts.append(txt)
    pd.cta_buttons = cta_texts[:20]

    # performance heuristics —— 必须在移除 script/style 之前计算
    def _blocking_script(el):
        t = (el.get("type") or "").lower()
        if t and "javascript" not in t and t != "text/ecmascript":
            return False
        # async / defer 是布尔属性（BS4 解析为空串），需用 has_attr 判断存在性
        if el.has_attr("async") or el.has_attr("defer") or t == "module":
            return False
        return True

    def _blocking_stylesheet(el):
        media = (el.get("media") or "").lower().strip()
        # 非屏幕媒体（print / handheld / speech 等）不阻塞首屏渲染
        if media and media not in ("all", "screen", ""):
            return False
        return True

    stylesheets = soup.find_all("link", rel="stylesheet")
    pd.render_blocking_scripts = sum(1 for s in soup.find_all("script", src=True) if _blocking_script(s))
    pd.render_blocking_stylesheets = sum(1 for l in stylesheets if _blocking_stylesheet(l))
    pd.external_css = len(stylesheets)
    # 响应式媒体查询信号：内联 style 属性 + <style> 块 + 外部样式表媒体声明
    css_text = " ".join(s.get("style", "") or "" for s in soup.find_all(style=True))
    style_blocks = " ".join((st.string or "") for st in soup.find_all("style"))
    ext_media = " ".join((l.get("media") or "") for l in stylesheets)
    all_css = (css_text + " " + style_blocks + " " + ext_media).lower()
    if "max-width" in all_css and "media" in all_css:
        pd.has_media_queries = True

    # text
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    pd.text = text
    pd.text_length = len(text)
    # 正文词数取剔除模板噪声后的主内容文本（在副本上剥离，不影响原 soup 的规格提取）
    main_text = _content_text(soup)
    pd.word_count = _count_words(main_text)
    pd.text_sample = main_text[:120]
    pd.main_text = main_text

    # trust signals
    pd.phones = []
    for m in PHONE_RE.finditer(text):
        cleaned = _clean_phone(m.group(0))
        if cleaned and cleaned not in pd.phones:
            pd.phones.append(cleaned)
        if len(pd.phones) >= 10:
            break
    pd.emails = list({m.group(0).lower() for m in EMAIL_RE.finditer(text)})[:10]
    pd.certs = list({m.group(0).upper() for m in CERT_RE.finditer(text)})[:10]
    pd.specs, pd.image_tables = _extract_specs(soup, text)

    # X-Robots-Tag 响应头（noindex 的第二种设置方式，meta 里看不到）
    if headers:
        xrt = headers.get("x-robots-tag") or headers.get("X-Robots-Tag") or ""
        pd.x_robots_tag = str(xrt).strip()

    # 极端/无法验证承诺用语：引用原文片段作证据
    claims: List[str] = []
    for m in EXTREME_CLAIM_RE.finditer(text):
        frag = m.group(0)
        if frag not in claims:
            claims.append(frag)
        if len(claims) >= 8:
            break
    pd.extreme_claims = claims

    return pd
