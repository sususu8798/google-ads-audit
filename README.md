# Google Ads 落地页质量诊断工具（MVP）

依据《AI Google Ads 落地页质量诊断与优化平台 PRD V1.0》实现的**可真实运行**的检测工具：不是静态原型，所有结论都来自真实抓取证据与可复算的指标聚合。

## 快速开始

```bash
cd google_ads_audit
python3 -m venv .venv && source .venv/bin/activate   # 或使用已有环境
pip install -r requirements.txt
python app.py                 # 启动后访问 http://localhost:8000
```

- 打开 `http://localhost:8000` → 「单 URL 检测」或「广告报表分析」
- 想直接看效果：双击打开项目根目录的 **`sample_report.html`**（自包含演示报告，内嵌一次真实抓取结果，无需启动服务）

## 服务怎么才能「永远开着」（重要）

后台服务进程活不过终端会话，这是 macOS 的进程模型决定的。三种方式按彻底程度排列：

| 方式 | 操作 | 效果 |
|---|---|---|
| **① 永久自启（推荐，一次搞定）** | 双击 **`安装永久自启.command`** | 注册为 macOS 登录项：开机/登录自动启动，进程崩溃 10 秒内自动重启。以后不用再管 |
| ② 临时启动 | 双击 **`启动诊断工具.command`** | 本次开机内后台启动并打开页面；重启电脑后需再双击 |
| ③ 完全不起服务 | 双击 **`sample_report.html`** | 离线报告，单文件自包含，无需服务 |

卸载永久自启（终端执行）：

```bash
launchctl unload ~/Library/LaunchAgents/com.workbuddy.googleadsaudit.plist
rm ~/Library/LaunchAgents/com.workbuddy.googleadsaudit.plist
```

> 前端页面在连不上后端时，顶部状态灯会变红并给出上述三种处理方式的指引。

## 已实现（MVP，全部真实检测）

| 模块 | 说明 |
|---|---|
| 单 URL 检测 | SSRF 安全抓取 → 内容提取 → 34 条规则 → 分项评分 + 优先级 + 证据化问题清单 |
| 报表解析 | CSV/XLSX，自动跳过前置元数据行、识别 60 列表头、字段映射、去重、汇总行识别 |
| URL 聚合 | 相同 URL 按正确粒度聚合，重算 CTR/CPC/CPA；零转化 CPA=N/A，零展示不开算 CTR；多币种分开汇总 |
| 联合诊断 | 每个聚合 URL 抓取页面 → 广告文案—页面匹配（AD-001~003）→ 结合花费/转化计算 P0–P3 优先级 |
| 报告输出 | 分项评分环 + 覆盖率、政策风险独立标识、可排序/筛选/展开明细的 URL 表、CSV 问题清单导出、打印导出 PDF |

### 评分口径（PRD 4.8）

可访问性与技术 15% ｜ 广告—页面相关性 15% ｜ 内容与产品信息 25% ｜ 询盘转化体验 10% ｜ 移动端与性能 10% ｜ 信任与透明度 25%

- 每条规则输出 **通过 / 未达标 / 未检测 / 不适用**；未检测不计入分子分母，覆盖率单独展示
- 无广告数据时「广告—页面相关性」显示**缺少投放数据**，不参与总分，评分标记「不完整」
- 政策风险（official_policy 类规则失败）独立展示，**不可被高分抵消**
- 广告投放指标（花费/点击/转化）仅用于列表排序与优先级，不计入页面质量分

### 优先级（PRD 4.7，规则透明可解释）

- **P0 紧急**：页面不可达 / 跳转到无关域名 / 政策风险线索 / 表单存在但提交路径故障
- **P1 高**：高费用且零转化 + 有可修复问题；或广告—页面严重不匹配
- **P2 中**：存在内容/CTA/移动/信任改进机会（影响待验证）
- **P3 观察**：样本不足（点击 < SMALL_SAMPLE_CLICKS）或无明显问题

### 依据类型（PRD 4.5）

`official_policy` 官方政策 ｜ `official_recommendation` 官方建议 ｜ `optimizer_recommendation` CRO/优化经验 ｜ `technical_check` 技术检测 ｜ `industry_guidance` 行业建议 ｜ `manual_review` 需人工核对

工具**不冒充 Google 官方结论**；无法确认的项标为「未检测 / 需人工核对」，不虚构证据。

## 安全（PRD 第 10 节）

- SSRF 防护：仅 http/https；DNS 解析后拦截私网/回环/链路本地/云元数据地址；**每次跳转重新校验**
- 超时、最大跳转次数、最大响应体限制；抓取失败输出明确原因
- 上传仅接受 .csv/.xlsx；CSV 导出对 `= + - @` 开头内容做注入转义
- 不绕过反爬/验证码/登录墙；受限场景标注「需人工核对」

## 测试

```bash
python -m pytest tests/ -q     # 18 项：表头识别、78行/10URL/14Campaign/9AdGroup、
                               # 聚合复算 296/3844/3440.36/8、零分母 N/A、多币种、
                               # 去重、SSRF 拦截、规则状态、评分与优先级
```

示例报表 `tests/fixtures/sample_google_ads.csv` 按 PRD 第 5 节结构生成（前两行元数据 + 60 列表头）。

## 配置

复制 `.env.example` 为 `.env` 可调整：抓取超时/跳转/响应体上限、六维权重、P1 费用阈值、小样本点击阈值等。

## 未实现（PRD 后续阶段，当前 MVP 不含）

- 登录 / 多用户 / 项目权限隔离（当前为单机内部工具，无鉴权）
- PostgreSQL 持久化、任务队列、复测与历史版本对比
- 真实浏览器渲染的移动端/性能检测（LCP/CLS/INP 需接入 PageSpeed/Lighthouse）
- Google Ads API 接入、搜索词/设备/地域维度分析
- LLM 语义级诊断（当前广告匹配为规则启发式；接入后按 PRD 第 9 节 JSON Schema 输出）
- 任务分派工作流、Excel/PDF 服务端导出（当前为 CSV 导出 + 浏览器打印）

## 目录结构

```
google_ads_audit/
├─ app.py                 # FastAPI 入口（API + 静态托管）
├─ src/
│  ├─ config.py           # 环境变量配置（权重/阈值/抓取限制）
│  ├─ fetcher.py          # SSRF 安全抓取
│  ├─ html_extract.py     # HTML 内容提取
│  ├─ rules.py            # 34 条规则引擎（依据类型/严重度/证据/建议/置信度）
│  ├─ scorer.py           # 分项评分 + 优先级
│  ├─ csv_parser.py       # 报表解析与 URL 聚合
│  └─ audit.py            # 编排：单 URL / 报表联合诊断
├─ static/                # 前端（原生 HTML/CSS/JS，中文界面）
├─ tests/                 # pytest + 示例报表
├─ gen_sample.py          # 生成自包含演示报告 sample_report.html
└─ sample_report.html     # 演示样本（双击即可打开）
```

## 部署到云端（免费）

详见 [DEPLOY.md](./DEPLOY.md)：已内置 `Procfile` / `runtime.txt` / `.gitignore`，推荐 Railway（免 GitHub，CLI 直接上传文件夹）或 Render（需 GitHub）免费部署，自动读取 `$PORT`。**上线前建议加访问口令**（见 DEPLOY.md 安全提醒），否则公网任意人均可提交 URL 让服务器抓取。
