/* Google Ads 落地页质量诊断工具 - 前端逻辑 */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/* ---------- API 基址解析：优先用当前页面自己的源（后端与静态页同端口服务），
   仅当页面不是从本地后端打开（file:// / 预览代理）时才回连 :8000 ---------- */
const API_CANDIDATES = (() => {
  const { protocol, hostname, port } = window.location;
  const list = [];
  if (protocol.startsWith("http")) {
    list.push(""); // 同源优先：页面由谁服务就用谁的 API（含局域网 IP / 域名部署），不写死端口
  }
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    // 本机回退：仅当确实在本机访问时才尝试 8000
    list.push("http://127.0.0.1:8000", "http://localhost:8000");
  }
  return list;
})();
let _apiBase = null;
async function apiFetch(path, opts) {
  const bases = _apiBase != null ? [_apiBase] : API_CANDIDATES;
  let lastErr;
  for (const base of bases) {
    try {
      const res = await fetch(base + path, opts);
      _apiBase = base; // 网络层成功即锁定该基址（HTTP 4xx/5xx 也算后端可达）
      return res;
    } catch (e) { lastErr = e; }
  }
  _apiBase = null;
  throw lastErr;
}

const STATUS_TXT = { pass: "通过", fail: "未达标", not_detected: "需人工核对", not_applicable: "不适用" };
const SEV_TXT = { critical: "紧急", high: "高", medium: "中", low: "低" };

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
/* ---------- 扁平化线性图标库 ----------
   统一 1.7 线宽、圆角端点、currentColor 继承文字色，无渐变无阴影。
   注意：内联 SVG 必须写显式 width/height，只给 viewBox 会尺寸算 0 不显示。 */
const ICONS = {
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  chart: '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
  clipboard: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  trend: '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
  compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
  table: '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  chevR: '<polyline points="9 18 15 12 9 6"/>',
};
function icon(name, size = 16) {
  const p = ICONS[name];
  return p ? `<svg class="ico" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>` : "";
}

/* 徽章内容为已组装好的 HTML（可能含 SVG 图标），故此处不转义；
   调用方对自己拼入的动态文本自行 esc()。 */
function badge(cls, txt) { return `<span class="badge ${cls}">${txt}</span>`; }
function statusBadge(s) { return badge(s, STATUS_TXT[s] || s); }
function severityBadge(s) { return badge(s, SEV_TXT[s] || s); }
/* 整改责任人徽章：网建人员 / 优化师 用不同色区分，便于分工时一眼分派 */
function ownerBadge(o) {
  const cls = (o === "优化师") ? "owner-ads" : "owner-web";
  return badge(cls, icon("user", 13) + " " + esc(o || "网建人员"));
}
/* 评分等级：优先用后端 grade（含维度否决），无则按综合分兜底 */
function gradeBadge(sc) {
  const g = sc && sc.grade;
  const lv = g && g.level;
  const cls = lv === "good" ? "grade-good" : lv === "mid" ? "grade-mid" : lv === "bad" ? "grade-bad" : "grade-none";
  const txt = (g && g.label) || gradeOfScore(sc && sc.overall_score);
  return badge("grade " + cls, txt);
}
function gradeOfScore(score) {
  if (score == null) return "无法评分";
  if (score >= 80) return "良好";
  if (score >= 60) return "待优化";
  return "亟需整改";
}
function policyBadge(p) {
  if (p.status === "risk_found") return badge("policy-risk", icon("alert", 13) + " " + esc(p.label));
  if (p.status === "no_risk_detected") return badge("policy-ok", icon("check", 13) + " " + esc(p.label));
  return badge("policy-none", esc(p.label));
}
function fmtNum(n, d = 0) { return n == null ? "N/A" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: 0 }); }
function fmtMoney(n, cur) { return n == null ? "N/A" : (cur ? cur + " " : "") + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function pct(n) { return n == null ? "N/A" : (n * 100).toFixed(2) + "%"; }

/* ---------- Tabs ---------- */
$$(".tab").forEach(t => t.addEventListener("click", () => {
  $$(".tab").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  const tab = t.dataset.tab;
  $("#single").classList.toggle("hidden", tab !== "single");
  $("#report").classList.toggle("hidden", tab !== "report");
  $("#batch").classList.toggle("hidden", tab !== "batch");
}));

/* ============================================================
   单 URL 检测
============================================================ */
function scoreRing(overall, complete) {
  const r = 74, c = 2 * Math.PI * r;
  const val = overall == null ? 0 : overall;
  const off = c * (1 - val / 100);
  const band = val >= 80 ? "good" : val >= 60 ? "mid" : "bad";
  const color = band === "good" ? "var(--green-chart)" : band === "mid" ? "var(--amber-chart)" : "var(--red-chart)";
  const track = band === "good" ? "#e3f2e9" : band === "mid" ? "#fbf0da" : "#fae8e8";
  const label = overall == null ? "—" : Math.round(overall);
  return `<div class="ring-wrap">
    <div class="ring">
      <svg width="168" height="168">
        <circle cx="84" cy="84" r="${r}" fill="none" stroke="${track}" stroke-width="14"/>
        <circle cx="84" cy="84" r="${r}" fill="none" stroke="${color}" stroke-width="14" stroke-linecap="round"
          stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"/>
      </svg>
      <div class="val"><b style="color:${color}">${label}</b><span>页面质量分</span></div>
    </div>
    <div class="ring-legend">
      <span class="lg lg-tri">0–59</span>
      <span class="lg lg-sq">60–79</span>
      <span class="lg lg-ci">80–100</span>
    </div>
  </div>`;
}
function dimBars(dimensions) {
  const sorted = Object.values(dimensions).slice().sort((a, b) => (b.weight || 0) - (a.weight || 0));
  return `<div class="dim-list">` + sorted.map(d => {
    if (d.score == null) {
      return `<div class="dim-row"><div class="dim-head"><span class="name">${esc(d.label)}</span><span class="num dim-warn">${esc(d.note || "未评估")}</span></div>
        <div class="bar"><i style="width:0%"></i></div><div class="dim-note dim-warn">权重 ${d.weight}% · 暂无可评估项</div></div>`;
    }
    const color = d.score >= 80 ? "var(--green-chart)" : d.score >= 60 ? "var(--amber-chart)" : "var(--red-chart)";
    return `<div class="dim-row"><div class="dim-head"><span class="name">${esc(d.label)}</span></div>
      <div class="bar"><i style="width:${d.score}%;background:${color}"></i></div>
      <div class="dim-note">权重 ${d.weight}% · 通过 ${d.passed} / 评估 ${d.applicable} · 需人工核对 ${d.not_detected}</div></div>`;
  }).join("") + `</div>`;
}

function findingCard(f) {
  // 证据只展示内容本身；来源标签（TITLE/REDIRECT 等）不展示，避免噪音。
  // 位置仅在是 URL 时展示（如 HTTP 状态对应的地址）；"body" 这类内部标记对读者无意义，不显示。
  const ev = (f.evidence || []).map(e => {
    const loc = (e.location || "").trim();
    const showLoc = /^https?:\/\//i.test(loc);
    return `<div class="f-ev">${showLoc ? `<div class="loc">${esc(loc)}</div>` : ""}<div>${esc(e.text)}</div></div>`;
  }).join("");
  const rec = (f.recommendation || []).map(r => `<li>${esc(r)}</li>`).join("");
  return `<div class="finding s-${f.status}">
    <div class="f-top">
      <span class="f-title">${esc(f.title)}</span>
      ${severityBadge(f.severity)} ${statusBadge(f.status)}${ownerBadge(f.owner)}
    </div>
    <div class="f-meta"><span class="muted-block">依据类型：${esc(f.basis_label)}</span><span class="muted-block">设备：${esc(f.device === "both" ? "桌面+移动" : f.device === "mobile" ? "移动端" : "桌面端")}</span><span class="muted-block">整改责任人：${esc(f.owner || "网建人员")}</span></div>
    ${ev ? `<div class="f-ev-wrap">${ev}</div>` : ""}
    ${rec ? `<ul>${rec}</ul>` : ""}
    ${f.method ? `<div class="conf">检测方法：${esc(f.method)}</div>` : ""}
  </div>`;
}

/* 一键复制整改清单：把指定状态（可多个）的条目按责任人分组，生成可直接粘贴发给对应人员的纯文本 */
function buildCopyText(findings, statuses, pageUrl) {
  const statusArr = Array.isArray(statuses) ? statuses : String(statuses).split(",");
  const statusTxt = { fail: "未达标", not_detected: "需人工核对" };
  const items = findings.filter(f => statusArr.includes(f.status));
  if (!items.length) return "";
  const groups = {};
  items.forEach(f => {
    const owner = f.owner || "网建人员";
    (groups[owner] = groups[owner] || []).push(f);
  });
  const ownerOrder = ["网建人员", "优化师"];
  const owners = Object.keys(groups).sort((a, b) => {
    const ia = ownerOrder.indexOf(a), ib = ownerOrder.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  const breakdown = statusArr.map(st => `${statusTxt[st] || st} ${items.filter(f => f.status === st).length} 项`).join(" · ");
  let out = `【落地页整改清单 · 共 ${items.length} 项（${breakdown}）】\n页面：${pageUrl || "（未提供）"}\n`;
  owners.forEach(owner => {
    out += `\n■ ${owner}（${groups[owner].length} 项）\n`;
    groups[owner].forEach((f, i) => {
      const ev = (f.evidence || []).map(e => e.text).join("；");
      const rec = (f.recommendation || []).join("；");
      out += `\n${i + 1}. 【${statusTxt[f.status] || f.status}】${f.title}\n问题：${ev || "（详见诊断报告）"}\n调整方案：${rec || "（详见诊断报告）"}\n负责人员：${owner}\n`;
    });
  });
  return out.trim();
}

async function copyTextToClipboard(text, btn) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch (e) {
    // 兜底：隐藏 textarea + execCommand（兼容非安全上下文）
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      ok = document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e2) { ok = false; }
  }
  if (btn) {
    const old = btn.textContent;
    btn.textContent = ok ? "已复制 ✓" : "复制失败，请手动选择";
    setTimeout(() => { btn.textContent = old; }, 1600);
  }
}

function findingsBlock(findings, mountId, filterEl, pageUrl) {
  const counts = { all: findings.length, fail: 0, pass: 0, not_detected: 0, not_applicable: 0 };
  findings.forEach(f => counts[f.status] = (counts[f.status] || 0) + 1);
  const copyBtn = (sts, label) => sts.some(st => counts[st] > 0)
    ? `<button class="btn ghost copy-btn" data-copy="${sts.join(",")}" style="margin-left:auto">${label}</button>` : "";
  const toolbar = `<div class="findings-toolbar">
    <span class="chip active" data-f="all">全部 ${counts.all}</span>
    <span class="chip" data-f="pass">通过 ${counts.pass}</span>
    <span class="chip" data-f="fail">未达标 ${counts.fail}</span>
    <span class="chip" data-f="not_detected">需人工核对 ${counts.not_detected}</span>
    <span class="chip" data-f="not_applicable">不适用 ${counts.not_applicable}</span>
    ${copyBtn(["fail", "not_detected"], icon("clipboard", 15) + " 复制整改项")}
  </div>`;
  const list = `<div class="flist">${findings.map(findingCard).join("") || '<div class="empty">无规则结果</div>'}</div>`;
  $(mountId).innerHTML = toolbar + list;
  $(mountId).querySelectorAll(".chip").forEach(chip => chip.addEventListener("click", () => {
    $(mountId).querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    const f = chip.dataset.f;
    $$(mountId + " .finding").forEach(el => {
      const st = el.className.match(/s-(\w+)/)[1];
      el.style.display = (f === "all" || f === st) ? "" : "none";
    });
  }));
  // 默认隐藏「不适用」项，减少噪声
  $$(mountId + " .finding.s-not_applicable").forEach(el => el.style.display = "none");
  // 一键复制整改清单（未达标 / 需人工核对）
  $(mountId).querySelectorAll(".copy-btn").forEach(btn => btn.addEventListener("click", () => {
    const text = buildCopyText(findings, btn.dataset.copy, pageUrl);
    if (text) copyTextToClipboard(text, btn);
  }));
}

function pageSummaryHTML(ps) {
  if (!ps) return `<div class="notice warn">页面未成功抓取，无法生成页面质量评分与证据（详见抓取状态）。</div>`;
  const rows = [
    ["页面标题", ps.title || "—"],
    ["H1", (ps.h1 || []).join(" / ") || "—"],
    ["Meta 描述", ps.meta_description ? (ps.meta_description.length > 80 ? ps.meta_description.slice(0, 80) + "…" : ps.meta_description) : "—"],
    ["Canonical", ps.canonical ? `<a href="${esc(ps.canonical)}" target="_blank" rel="noopener" title="${esc(ps.canonical)}">${esc(ps.canonical)}</a>` : "—", true],
    ["Viewport", ps.viewport || "—"],
    ["图片 ALT", (() => {
      const withAlt = ps.images_with_alt || 0;
      const missing = ps.images_missing_alt || 0;
      const content = withAlt + missing;            // 被认定为内容图的数量
      const total = ps.images_total || 0;
      const decor = ps.images_decorative || 0;
      const empty = ps.images_empty_src || 0;
      if (content > 0) return `内容图 ${withAlt}/${content} 有 ALT（缺失 ${missing}）`;
      if (total === 0) return `页面无 <img> 标签`;
      return `内容图 0 张可评（页面 img 共 ${total}：装饰/图标 ${decor}、空占位 ${empty}；JS 注入的图片静态抓取不可见）`;
    })()],
    ["表单", ps.forms ? `表单 ${ps.forms} 个，输入 ${ps.form_inputs} 项，含提交：${ps.form_has_submit ? "是" : "否"}` : "无"],
    ["链接", `内 ${ps.links_internal} / 外 ${ps.links_external}`],
    ["正文量", `${fmtNum(ps.word_count)} 词/字`],
    ["电话", (ps.phones || []).join(", ") || "—"],
    ["邮箱", (ps.emails || []).join(", ") || "—"],
    ["认证", (ps.certs || []).join(", ") || "—"],
    ["规格参数", (ps.specs || []).join(", ") || "—"],
    ["页面体积", `${(ps.page_bytes / 1024).toFixed(1)} KB`],
  ];
  return `<div class="kv">${rows.map(([k, v, isHtml]) => `<div class="item"><span class="k">${esc(k)}</span><span class="v">${isHtml ? v : esc(v)}</span></div>`).join("")}</div>`;
}

function renderSingle(r) {
  const box = $("#su-result");
  const f = r.fetch || {};
  const sc = r.score || {};
  const adOn = !!(r.input && (r.input.ad_headlines && r.input.ad_headlines.length || r.input.ad_descriptions && r.input.ad_descriptions.length));
  const recs = (r.records || []).length;

  box.innerHTML = `
  <div class="panel">
    <div class="section-title">${icon("clipboard", 17)} 检测报告</div>
    <div class="section-sub">输入 URL：${esc(r.input && r.input.url || r.url)}</div>
    <div class="stat-grid">
      <div class="stat"><div class="k">抓取状态</div><div class="v">${f.ok ? icon("checkCircle", 14) + " 成功" : icon("alert", 14) + " " + esc(f.error || ("HTTP " + (f.status_code ?? "失败")))}</div></div>
      <div class="stat"><div class="k">HTTP 状态</div><div class="v">${f.status_code ?? "—"}</div></div>
      <div class="stat"><div class="k">最终 URL</div><div class="v" style="font-size:12px;word-break:break-all">${esc(f.final_url || r.url)}</div></div>
      <div class="stat"><div class="k">耗时</div><div class="v">${(f.elapsed_ms || 0)}<small> ms</small></div></div>
    </div>
    ${f.error ? `<div class="notice error">抓取错误：${esc(f.error)}</div>` : ""}
    ${f.redirect_chain && f.redirect_chain.length > 1 ? `<div class="notice info">跳转链：${f.redirect_chain.map(esc).join(" → ")}</div>` : ""}
    <div class="divider"></div>
    <div class="score-hero">
      ${scoreRing(sc.overall_score, sc.score_complete)}
      ${dimBars(sc.dimensions)}
    </div>
  </div>

  <details class="panel fold">
    <summary class="section-title">${icon("compass", 17)} 页面概览</summary>
    <div class="section-sub" style="margin-top:6px">${adOn ? "已提供广告上下文，已启用「广告—页面相关性」联合诊断。" : "未提供广告数据，广告—页面相关性维度显示「缺少投放数据」，不参与总分。"}</div>
    ${pageSummaryHTML(r.page_summary)}
    <div class="muted-block" style="margin-top:10px">注：电话 / 邮箱 / 认证 / 规格为<b>自动识别</b>，建议人工核对；未识别到不代表页面绝对缺失（<b>JS 异步加载的表格、图片中的信息无法读取</b>）。</div>
  </details>

  <div class="panel">
    <div class="section-title">${icon("search", 17)} 问题清单与证据</div>
    <div id="su-findings"></div>
  </div>`;
  findingsBlock(r.findings || [], "#su-findings", null, (r.fetch && r.fetch.final_url) || (r.input && r.input.url) || r.url || "");
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

$("#su-submit").addEventListener("click", async () => {
  const url = $("#su-url").value.trim();
  if (!url) { alert("请填写落地页 URL"); return; }
  const payload = {
    url,
    industry: $("#su-industry").value.trim() || null,
    country: $("#su-country").value.trim() || null,
    language: $("#su-language").value.trim() || null,
    goal: $("#su-goal").value.trim() || null,
    product: $("#su-product").value.trim() || null,
    keywords: $("#su-keywords").value.split(",").map(s => s.trim()).filter(Boolean) || null,
    ad_headlines: $("#su-headlines").value.split("\n").map(s => s.trim()).filter(Boolean) || null,
    ad_descriptions: $("#su-descriptions").value.split("\n").map(s => s.trim()).filter(Boolean) || null,
  };
  $("#su-result").innerHTML = `<div class="panel"><div class="loading"><div class="spinner"></div>正在安全抓取并分析页面…</div></div>`;
  try {
    const res = await apiFetch("/api/check-url", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "检测失败");
    renderSingle(data);
  } catch (e) {
    $("#su-result").innerHTML = `<div class="panel"><div class="notice error">${fetchErrMsg(e)}</div></div>`;
  }
});

$("#su-clear").addEventListener("click", () => {
  ["su-url", "su-industry", "su-country", "su-language", "su-goal", "su-product", "su-keywords", "su-headlines", "su-descriptions"].forEach(id => $("#" + id).value = "");
  $("#su-result").innerHTML = "";
});

/* ============================================================
   报表分析
============================================================ */
let selectedFile = null;

const dz = $("#dz");
const fileInput = $("#file-input");
dz.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });
["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) setFile(f); });

function setFile(f) {
  const ok = /\.(csv|xlsx|xls)$/i.test(f.name);
  if (!ok) { alert("仅支持 CSV / XLSX 文件"); return; }
  selectedFile = f;
  $("#rp-submit").disabled = false;
  dz.querySelector("h3").textContent = "已选择：" + f.name;
  dz.querySelector("p").textContent = `大小 ${(f.size / 1024).toFixed(1)} KB`;
  $("#rp-preview").innerHTML = "";
  $("#rp-result").innerHTML = "";
}

function previewHTML(p, warnings) {
  /* 正常时返回空（页面保持干净）；仅字段缺失 / 解析警告时显示提示 */
  const parts = [];
  if (p && p.missing_fields && p.missing_fields.length)
    parts.push(`<div class="notice warn">字段未识别：${esc(p.missing_fields.join(", "))}，相关诊断项可能不准确</div>`);
  if (warnings && warnings.length)
    parts.push(warnings.map(w => `<div class="notice warn">${esc(w)}</div>`).join(""));
  return parts.join("");
}

const COLS = [
  ["final_url", "落地页 URL", "url"], ["cost", "花费", "money"],
  ["clicks", "点击", "num"], ["impressions", "展示", "num"], ["conversions", "转化", "num"],
  ["ctr", "CTR", "pct"], ["avg_cpc", "平均 CPC", "money2"], ["cpa", "CPA", "cpa"],
  ["campaign_count", "Campaign", "num"], ["ad_group_count", "AdGroup", "num"],
  ["page_score", "页面分", "score"], ["status", "抓取", "status"]
];

let reportUrls = [];
let sortKey = "cost", sortDir = -1;

function renderTable() {
  const urls = reportUrls;
  const head = `<tr>${COLS.map(c => `<th data-k="${c[0]}">${c[1]} ${sortKey === c[0] ? (sortDir < 0 ? "▼" : "▲") : ""}</th>`).join("")}</tr>`;
  const body = urls.map((u, i) => {
    const m = u.metrics || {};
    const sc = (u.score && u.score.overall_score != null) ? Math.round(u.score.overall_score) : "—";
    const scCls = u.score && u.score.overall_score != null ? (u.score.overall_score >= 80 ? "pass" : u.score.overall_score >= 60 ? "medium" : "fail") : "not_applicable";
    const status = u.fetch && u.fetch.ok ? icon("checkCircle", 14) : icon("alert", 14);
    return `<tr data-i="${i}">
      <td class="url-cell"><div class="url-wrap">
        <span class="row-arrow" data-i="${i}" title="展开明细">${icon("chevR", 13)}</span>
        <span class="url-link" title="${esc(u.final_url)}" data-i="${i}">${esc(u.final_url)}</span>
        <a class="open-link" href="${esc(u.final_url)}" target="_blank" rel="noopener" title="在新标签页打开该落地页" onclick="event.stopPropagation()">打开 ↗</a>
        <a class="open-link copy-link" data-copy-url="${esc(u.final_url)}" title="复制完整链接" onclick="event.stopPropagation()">复制</a>
      </div></td>
      <td class="nowrap">${fmtMoney(m.cost, u.currency)}</td>
      <td class="nowrap">${fmtNum(m.clicks)}</td>
      <td class="nowrap">${fmtNum(m.impressions)}</td>
      <td class="nowrap">${fmtNum(m.conversions)}</td>
      <td class="nowrap">${pct(m.ctr)}</td>
      <td class="nowrap">${m.avg_cpc == null ? "N/A" : fmtMoney(m.avg_cpc, u.currency)}</td>
      <td class="nowrap">${m.cpa == null ? "N/A" : fmtMoney(m.cpa, u.currency)}</td>
      <td class="nowrap">${fmtNum(m.campaign_count)}</td>
      <td class="nowrap">${fmtNum(m.ad_group_count)}</td>
      <td class="nowrap">${badge(scCls, sc)}</td>
      <td class="nowrap">${status}</td>
    </tr>
    <tr class="expand-row hidden" data-exp="${i}"><td colspan="${COLS.length}"><div class="expand-inner" id="exp-${i}"></div></td></tr>`;
  }).join("");
  $("#rp-table").innerHTML = `<div class="table-wrap"><table>${head}${body}</table></div>`;
  $$("#rp-table th").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = -1; }
    sortUrls(); renderTable();
  }));
  $$("#rp-table .url-link, #rp-table .row-arrow").forEach(el => el.addEventListener("click", () => {
    const i = el.dataset.i;
    const row = $(`#rp-table tr[data-i="${i}"]`);
    const exp = $(`#rp-table .expand-row[data-exp="${i}"]`);
    const inner = $(`#exp-${i}`);
    const isHidden = exp.classList.contains("hidden");
    // 手风琴：先收起其他已展开的行
    $$("#rp-table .expand-row").forEach(o => {
      if (o !== exp && !o.classList.contains("hidden")) {
        o.classList.add("hidden");
        const orow = $(`#rp-table tr[data-i="${o.dataset.exp}"]`);
        if (orow) orow.classList.remove("open");
      }
    });
    if (isHidden) {
      exp.classList.remove("hidden");
      row.classList.add("open");
      renderExpand(inner, reportUrls[i], i);
    } else { exp.classList.add("hidden"); row.classList.remove("open"); }
  }));
  $$("#rp-table .copy-link").forEach(el => el.addEventListener("click", () => {
    copyTextToClipboard(el.dataset.copyUrl, el);
  }));
}

function renderExpand(el, u, idx) {
  el.innerHTML = `<div style="padding:18px">
    <details class="fold fold-inline">
      <summary class="subhead">页面概览</summary>
      ${pageSummaryHTML(u.page_summary)}
      <div class="muted-block" style="margin-top:10px">注：电话 / 邮箱 / 认证 / 规格为自动识别，建议人工核对；未识别到不代表页面绝对缺失（JS 异步加载的表格、图片中的信息无法读取）。</div>
    </details>
    <div class="divider"></div>
    <div class="subhead">检测结果（${u.findings.length} 项）</div>
    <div id="exp-findings-${idx}"></div>
  </div>`;
  findingsBlock(u.findings, `#exp-findings-${idx}`, null, u.final_url || "");
}

function sortUrls() {
  const k = sortKey;
  reportUrls.sort((a, b) => {
    let va, vb;
    if (k === "page_score") { va = a.score && a.score.overall_score != null ? a.score.overall_score : -1; vb = b.score && b.score.overall_score != null ? b.score.overall_score : -1; }
    else if (k === "status") { va = a.fetch && a.fetch.ok ? 1 : 0; vb = b.fetch && b.fetch.ok ? 1 : 0; }
    else if (k === "final_url") { va = a.final_url; vb = b.final_url; return sortDir * String(va).localeCompare(String(vb)); }
    else { va = (a.metrics && a.metrics[k]) ?? -1; vb = (b.metrics && b.metrics[k]) ?? -1; }
    return sortDir * (va - vb);
  });
}

function renderReport(data) {
  $("#rp-preview").innerHTML = previewHTML(data.preview, data.warnings);
  $("#rp-result").innerHTML = `
    <div class="panel">
      <div class="section-title">${icon("target", 17)} URL 机会排序</div>
      <div class="section-sub">按花费、转化、页面评分排序。点击 URL 展开明细（证据 / 页面概览 / 问题清单）。</div>
      <div class="table-tools">
        <input type="text" class="search-input" id="rp-search" placeholder="搜索 URL…">
        <span class="muted-block" id="rp-count"></span>
      </div>
      <div id="rp-table"></div>
      <div class="export-bar">
        <button class="btn secondary" id="rp-export-csv">导出问题清单 (CSV)</button>
      </div>
    </div>`;
  reportUrls = data.urls || [];
  sortUrls(); renderTable();
  $("#rp-count").textContent = `共 ${reportUrls.length} 个 URL`;
  $("#rp-search").addEventListener("input", applyFilters);
  $("#rp-export-csv").addEventListener("click", () => exportCSV(data));
  $("#rp-result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function applyFilters() {
  const q = ($("#rp-search").value || "").toLowerCase();
  $$("#rp-table tbody tr").forEach(tr => {
    if (tr.classList.contains("expand-row")) return;
    const i = tr.dataset.i;
    const u = reportUrls[i];
    const hit = !q || u.final_url.toLowerCase().includes(q);
    tr.style.display = hit ? "" : "none";
  });
}

function exportCSV(data) {
  const rows = [["URL", "币种", "花费", "点击", "展示", "转化", "CPA", "页面分", "规则ID", "标题", "严重度", "依据类型", "状态", "整改责任人", "证据", "修复建议"]];
  (data.urls || []).forEach(u => {
    const sc = u.score && u.score.overall_score != null ? Math.round(u.score.overall_score) : "N/A";
    (u.findings || []).forEach(f => {
      const ev = (f.evidence || []).map(e => `${e.source}: ${e.text}`).join(" | ");
      const rec = (f.recommendation || []).join("; ");
      rows.push([u.final_url, u.currency, u.metrics.cost, u.metrics.clicks, u.metrics.impressions,
        u.metrics.conversions, u.metrics.cpa == null ? "N/A" : u.metrics.cpa, sc,
        f.rule_id, f.title, f.severity, f.basis_label, STATUS_TXT[f.status] || f.status, f.owner || "网建人员", ev, rec]);
    });
  });
  const csv = rows.map(r => r.map(c => {
    const s = String(c == null ? "" : c);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }).join(",")).join("\n");
  // CSV 注入防护：以 = + - @ 开头的内容转义
  const safe = csv.replace(/^([=+\-@])/gm, "'\$1");
  const blob = new Blob(["\ufeff" + safe], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "落地页诊断问题清单.csv";
  a.click();
}

$("#rp-submit").addEventListener("click", async () => {
  if (!selectedFile) return;
  $("#rp-preview").innerHTML = `<div class="panel"><div class="loading"><div class="spinner"></div>正在解析报表并对每个 URL 执行安全抓取与诊断…（URL 较多时可能需要数十秒）</div></div>`;
  $("#rp-result").innerHTML = "";
  const fd = new FormData();
  fd.append("file", selectedFile);
  try {
    const res = await apiFetch("/api/analyze-report", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "解析失败");
    if (data.parse_only) {
      $("#rp-preview").innerHTML = previewHTML(data.preview, data.warnings) +
        `<div class="notice error">页面抓取阶段异常：${esc(data.error || "")}，仅展示解析结果。</div>`;
      return;
    }
    renderReport(data);
  } catch (e) {
    $("#rp-preview").innerHTML = `<div class="panel"><div class="notice error">${fetchErrMsg(e)}</div></div>`;
  }
});

/* ============================================================
   多条 URL 批量检测
============================================================ */
const COLS_BATCH = [
  ["final_url", "落地页 URL", "url"], ["page_score", "页面分", "score"],
  ["status", "抓取", "status"], ["priority", "优先级", "priority"]
];
let batchUrls = [];
let batchSortKey = "page_score", batchSortDir = -1;

function prioBadge(p) {
  if (!p) return badge("P3", "—");
  return badge(p.priority || "P3", esc(p.label || p.priority));
}

function batchSort() {
  const k = batchSortKey;
  const rk = { "P0": 4, "P1": 3, "P2": 2, "P3": 1 };
  batchUrls.sort((a, b) => {
    let va, vb;
    if (k === "page_score") { va = a.score && a.score.overall_score != null ? a.score.overall_score : -1; vb = b.score && b.score.overall_score != null ? b.score.overall_score : -1; }
    else if (k === "status") { va = a.fetch && a.fetch.ok ? 1 : 0; vb = b.fetch && b.fetch.ok ? 1 : 0; }
    else if (k === "priority") { va = (a.priority && rk[a.priority.priority]) || 0; vb = (b.priority && rk[b.priority.priority]) || 0; }
    else { va = a.final_url; vb = b.final_url; return batchSortDir * String(va).localeCompare(String(vb)); }
    return batchSortDir * (va - vb);
  });
}

function renderBatchTable() {
  const urls = batchUrls;
  const head = `<tr>${COLS_BATCH.map(c => `<th data-k="${c[0]}">${c[1]} ${batchSortKey === c[0] ? (batchSortDir < 0 ? "▼" : "▲") : ""}</th>`).join("")}</tr>`;
  const body = urls.map((u, i) => {
    const sc = (u.score && u.score.overall_score != null) ? Math.round(u.score.overall_score) : "—";
    const scCls = u.score && u.score.overall_score != null ? (u.score.overall_score >= 80 ? "pass" : u.score.overall_score >= 60 ? "medium" : "fail") : "not_applicable";
    const status = u.fetch && u.fetch.ok ? icon("checkCircle", 14) : icon("alert", 14);
    return `<tr data-i="${i}">
      <td class="url-cell"><div class="url-wrap">
        <span class="row-arrow" data-i="${i}" title="展开明细">${icon("chevR", 13)}</span>
        <span class="url-link" title="${esc(u.final_url)}" data-i="${i}">${esc(u.final_url)}</span>
        <a class="open-link" href="${esc(u.final_url)}" target="_blank" rel="noopener" title="在新标签页打开该落地页" onclick="event.stopPropagation()">打开 ↗</a>
        <a class="open-link copy-link" data-copy-url="${esc(u.final_url)}" title="复制完整链接" onclick="event.stopPropagation()">复制</a>
      </div></td>
      <td class="nowrap">${badge(scCls, sc)}</td>
      <td class="nowrap">${status}</td>
      <td class="nowrap">${prioBadge(u.priority)}</td>
    </tr>
    <tr class="expand-row hidden" data-exp="${i}"><td colspan="${COLS_BATCH.length}"><div class="expand-inner" id="bt-exp-${i}"></div></td></tr>`;
  }).join("");
  $("#bt-table").innerHTML = `<div class="table-wrap"><table>${head}${body}</table></div>`;
  $$("#bt-table th").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (batchSortKey === k) batchSortDir *= -1; else { batchSortKey = k; batchSortDir = -1; }
    batchSort(); renderBatchTable();
  }));
  $$("#bt-table .url-link, #bt-table .row-arrow").forEach(el => el.addEventListener("click", () => {
    const i = el.dataset.i;
    const row = $(`#bt-table tr[data-i="${i}"]`);
    const exp = $(`#bt-table .expand-row[data-exp="${i}"]`);
    const inner = $(`#bt-exp-${i}`);
    const isHidden = exp.classList.contains("hidden");
    $$("#bt-table .expand-row").forEach(o => {
      if (o !== exp && !o.classList.contains("hidden")) {
        o.classList.add("hidden");
        const orow = $(`#bt-table tr[data-i="${o.dataset.exp}"]`);
        if (orow) orow.classList.remove("open");
      }
    });
    if (isHidden) {
      exp.classList.remove("hidden");
      row.classList.add("open");
      renderExpand(inner, batchUrls[i], i);
    } else { exp.classList.add("hidden"); row.classList.remove("open"); }
  }));
  $$("#bt-table .copy-link").forEach(el => el.addEventListener("click", () => {
    copyTextToClipboard(el.dataset.copyUrl, el);
  }));
}

function batchApplyFilters() {
  const q = ($("#bt-search").value || "").toLowerCase();
  $$("#bt-table tbody tr").forEach(tr => {
    if (tr.classList.contains("expand-row")) return;
    const i = tr.dataset.i;
    const u = batchUrls[i];
    const hit = !q || (u.final_url || "").toLowerCase().includes(q);
    tr.style.display = hit ? "" : "none";
  });
}

function renderBatch(data) {
  const s = data.summary || {};
  const prioHi = (s.prio_counts && ((s.prio_counts.P0 || 0) + (s.prio_counts.P1 || 0))) || 0;
  $("#bt-result").innerHTML = `
    <div class="panel">
      <div class="section-title">${icon("target", 17)} 批量检测概览</div>
      <div class="section-sub">共提交 ${s.total} 个 URL，按页面分 / 优先级排序。点击 URL 展开明细（证据 / 页面概览 / 问题清单）。</div>
      <div class="stat-grid">
        <div class="stat"><div class="k">URL 数</div><div class="v">${s.total}</div></div>
        <div class="stat"><div class="k">抓取成功</div><div class="v">${s.fetch_ok ?? "—"}</div></div>
        <div class="stat"><div class="k">平均页面分</div><div class="v">${s.avg_score ?? "—"}</div></div>
        <div class="stat"><div class="k">紧急 / 高优先级</div><div class="v">${prioHi}</div></div>
      </div>
      <div class="table-tools">
        <input type="text" class="search-input" id="bt-search" placeholder="搜索 URL…">
        <span class="muted-block" id="bt-count"></span>
      </div>
      <div id="bt-table"></div>
      <div class="export-bar">
        <button class="btn secondary" id="bt-export-csv">导出问题清单 (CSV)</button>
      </div>
    </div>`;
  batchUrls = data.urls || [];
  batchSort(); renderBatchTable();
  $("#bt-count").textContent = `共 ${batchUrls.length} 个 URL`;
  $("#bt-search").addEventListener("input", batchApplyFilters);
  $("#bt-export-csv").addEventListener("click", () => exportBatchCSV(data));
  $("#bt-result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function exportBatchCSV(data) {
  const rows = [["URL", "页面分", "优先级", "规则ID", "标题", "严重度", "依据类型", "状态", "整改责任人", "证据", "修复建议"]];
  (data.urls || []).forEach(u => {
    const sc = u.score && u.score.overall_score != null ? Math.round(u.score.overall_score) : "N/A";
    const pr = (u.priority && u.priority.label) || "";
    (u.findings || []).forEach(f => {
      const ev = (f.evidence || []).map(e => `${e.source}: ${e.text}`).join(" | ");
      const rec = (f.recommendation || []).join("; ");
      rows.push([u.final_url, sc, pr, f.rule_id, f.title, f.severity, f.basis_label, STATUS_TXT[f.status] || f.status, f.owner || "网建人员", ev, rec]);
    });
  });
  const csv = rows.map(r => r.map(c => {
    const s = String(c == null ? "" : c);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }).join(",")).join("\n");
  const safe = csv.replace(/^([=+\-@])/gm, "'$1");
  const blob = new Blob(["\ufeff" + safe], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "落地页批量诊断问题清单.csv";
  a.click();
}

$("#bt-submit").addEventListener("click", async () => {
  const raw = $("#bt-urls").value.split("\n").map(s => s.trim()).filter(Boolean);
  if (!raw.length) { alert("请至少填写一个落地页 URL"); return; }
  const payload = {
    urls: raw,
    industry: $("#bt-industry").value.trim() || null,
    country: $("#bt-country").value.trim() || null,
    language: $("#bt-language").value.trim() || null,
    goal: $("#bt-goal").value.trim() || null,
    product: $("#bt-product").value.trim() || null,
    keywords: $("#bt-keywords").value.split(",").map(s => s.trim()).filter(Boolean) || null,
    ad_headlines: $("#bt-headlines").value.split("\n").map(s => s.trim()).filter(Boolean) || null,
    ad_descriptions: $("#bt-descriptions").value.split("\n").map(s => s.trim()).filter(Boolean) || null,
  };
  $("#bt-result").innerHTML = `<div class="panel"><div class="loading"><div class="spinner"></div>正在安全抓取并分析 ${raw.length} 个页面…（URL 较多时可能需要数十秒）</div></div>`;
  try {
    const res = await apiFetch("/api/check-urls", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "检测失败");
    renderBatch(data);
  } catch (e) {
    $("#bt-result").innerHTML = `<div class="panel"><div class="notice error">${fetchErrMsg(e)}</div></div>`;
  }
});

$("#bt-clear").addEventListener("click", () => {
  ["bt-urls", "bt-industry", "bt-country", "bt-language", "bt-goal", "bt-product", "bt-keywords", "bt-headlines", "bt-descriptions"].forEach(id => $("#" + id).value = "");
  $("#bt-result").innerHTML = "";
});

/* 网络层错误（Failed to fetch）多半是后端服务未启动或页面为旧缓存，给出明确指引 */
function fetchErrMsg(e) {
  setApiStatus(false);
  if (e instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(e.message || "")) {
    return `无法连接后端服务。<b>两种处理方式：</b><br>
      ① <b>一次性彻底解决</b>：在项目目录双击 <code>安装永久自启.command</code>，之后开机自启、崩溃自动重启，永久访问 localhost:8000；<br>
      ② <b>临时启动</b>：双击 <code>启动诊断工具.command</code>，然后<b>刷新本页面</b>再重试（当前页面可能是服务停止前打开的旧页面）。<br>
      ③ 不想起服务？直接双击 <code>sample_report.html</code> 查看离线报告。`;
  }
  return `请求失败：${esc(e.message)}`;
}

/* ---------- 后端连接状态指示灯 ---------- */
const STARTUP_HELP =
  "后端服务不可达。处理方式：\n" +
  "① 一次性彻底解决：双击项目里的「安装永久自启.command」，之后开机自启 + 崩溃自动重启；\n" +
  "② 临时启动：双击「启动诊断工具.command」，然后刷新本页面；\n" +
  "③ 不想起服务：直接双击 sample_report.html 看离线报告。";

function setApiStatus(ok) {
  const el = $("#api-status");
  if (!el) return;
  el.classList.toggle("ok", ok);
  el.classList.toggle("down", !ok);
  el.innerHTML = ok
    ? `<span class="dot"></span>后端已连接`
    : `<span class="dot"></span>后端未连接 · 点此查看处理方法`;
  el.title = ok ? "后端服务运行中，可正常检测" : STARTUP_HELP;
}
async function checkApiStatus() {
  try {
    const r = await apiFetch("/api/health", { cache: "no-store" });
    setApiStatus(r.ok);
  } catch {
    setApiStatus(false);
  }
}
const statusEl = $("#api-status");
if (statusEl) statusEl.addEventListener("click", () => {
  checkApiStatus().then(() => {
    if (!statusEl.classList.contains("ok")) alert(STARTUP_HELP);
  });
});
if (!window.__DEMO__ && !window.__DEMO_REPORT__) {
  checkApiStatus();
  setInterval(checkApiStatus, 15000);
} else if (statusEl) {
  statusEl.style.display = "none";
}

/* ---------- 演示模式：直接渲染内嵌 JSON，无需后端 ---------- */
if (window.__DEMO_REPORT__) {
  try {
    document.querySelector('.tab[data-tab="report"]').click();
    renderReport(window.__DEMO_REPORT__);
    document.querySelector(".badge-env").textContent = "演示样本 · 真实抓取";
  } catch (e) { console.error(e); }
} else if (window.__DEMO__) {
  try {
    document.querySelector('.tab[data-tab="single"]').click();
    renderSingle(window.__DEMO__);
    document.querySelector(".badge-env").textContent = "演示样本 · 真实抓取";
  } catch (e) { console.error(e); }
}
