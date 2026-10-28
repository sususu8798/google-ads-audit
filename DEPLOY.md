# 部署到云端（免费）

本工具是单进程 FastAPI（自带托管前端），部署到支持 Python 的云平台几乎零配置：
已内置 `Procfile`（`web: python app.py`）、`runtime.txt`（Python 3.12，Render 自动识别）、`.gitignore`；
`app.py` 会自动读取环境变量 `PORT`（云平台注入的随机端口）和 `HOST`（默认 `0.0.0.0`）。

（各平台是否需要绑定支付卡见下表。）

### 绑卡要求速查

| 平台 | 是否绑卡 | 关键说明 |
|---|---|---|
| **Render** | ❌ 不绑卡 | 免费层无需信用卡；有 15 分钟无流量休眠，再访问慢几秒 |
| **Hugging Face Spaces** | ❌ 不绑卡 | 免费账号即可，需用 Docker 方式部署 |
| **Railway** | ⚠️ 需绑卡验证 | 免费额度内不扣费，但不绑卡很多功能受限 |
| **PythonAnywhere** | ❌ 不绑卡 | ⚠️ 免费版只允许访问白名单域名，抓取任意落地页会失败，不适合本工具 |
| **内网穿透（cloudflared）** | ❌ 不绑卡 | 零云账号；依赖你的 Mac 一直开着服务 |

> 想要**不绑卡**且**不注册任何云账号**：直接用本机 **cloudflared 内网穿透**（见文末）。想要**不绑卡但有固定公网地址**：选 **Render**（路径 B）。

下面两条主力免费路径二选一（更多不绑卡方案见文末）。

---

## 路径 A：Railway（免 GitHub，几分钟上线）⚠️ 需绑卡

Railway 的 CLI 可以直接上传本地文件夹部署，**不需要 GitHub 仓库**。

1. 注册免费账号：https://railway.app （Hobby 免费额度，需绑定支付方式做验证，但免费额度内不扣费）
2. 安装 Railway CLI：
   ```bash
   # macOS
   brew install railwayapp/railway/railway
   # 或用 npm（本机已有 node）
   npm i -g @railway/cli
   ```
3. 在项目目录登录并部署：
   ```bash
   cd google_ads_audit
   railway login          # 浏览器登录你的账号
   railway init           # 新建一个项目，选 "Empty Project"
   railway up             # 上传当前文件夹并部署（Railway 会读 Procfile 自动启动 python app.py）
   ```
4. 生成公网域名：
   ```bash
   railway domain         # 分配一个 *.railway.app 的公网地址
   ```
5. 打开该地址即可使用。同事直接访问这个链接。

> 免费额度说明：Hobby 计划每月有免费额度，超出后停服而非扣费；若不绑卡，部分功能受限。

---

## 路径 B：Render（✅ 不绑卡首选，需要 GitHub 仓库）

Render 免费层无需信用卡，但有**冷启动**（15 分钟无流量会休眠，下次访问慢几秒），每月 750 小时额度。

> ⚠️ **本机 git 不可用怎么办？**（常见于 macOS 升级后 `xcrun` 缺失，报错 `invalid active developer path`）
> 这条路径需要把代码推到 GitHub，而本机的 `/usr/bin/git` 依赖系统 CommandLineTools，若它损坏则 git 完全用不了。两种零成本解法：
> 1. **（推荐）GitHub Desktop**：从 https://desktop.github.com 下载安装，它**自带独立的 git**，不依赖系统工具。打开后「Add / Create」指向本项目文件夹 → 自动初始化仓库 → 填写提交说明 → 点「Publish」直接推到 GitHub（无需敲任何 git 命令）。
> 2. **修复系统 git**：在终端跑 `xcode-select --install`（会联网下载 CommandLineTools，约几百 MB），装完 `git` 即可恢复正常。
> 下面的命令行步骤假设 git 已可用；用 GitHub Desktop 的话，第 1–2 步的命令行可以全部用桌面端界面代替。

1. 注册：https://render.com
2. 把项目推到 GitHub（二选一）：
   - **命令行**：在本项目目录执行
     ```bash
     cd google_ads_audit
     git init
     git add .
     git commit -m "init google ads audit tool"
     # 到 GitHub 新建一个空仓库，复制它的地址，然后：
     git remote add origin <你的仓库地址>
     git branch -M main
     git push -u origin main
     ```
   - **GitHub Desktop**（git 不可用时首选）：打开 GitHub Desktop → File → Add Local Repository → 选本项目文件夹 → Create / Publish → 填仓库名 → Publish Repository（设为 Public）。
3. 在 Render 控制台 → New → Web Service → 连你的 GitHub 账号并选刚才的仓库。
4. 设置（Render 多数会自动识别，按需核对）：
   - **Runtime**: Python 3（会读 `runtime.txt` 里的 `python-3.12`）
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
   - **Instance Type**: Free
   - **Health Check Path**（可选）: `/api/health`
5. 点 Create Web Service，等构建完成（首次装 pandas 等依赖可能要几分钟）。完成后 Render 会给一个 `*.onrender.com` 公网地址。

---

## 部署后验证

打开公网地址，应该能看到页面。点「单 URL 检测」输入任意一个落地页，确认能出六维评分和证据。
也可用健康检查接口：`https://<你的域名>/api/health` 应返回服务状态。

---

## ⚠️ 安全提醒（强烈建议上线前确认）

公网部署后，**任何人都能提交 URL 让你的服务器去抓取页面**（等于一台开放爬虫，可能被滥用或用于探测内网）。
本项目已为分享场景做了前端同源优先改造，但**没有访问口令**。建议上线前加上一层简单防护：

- 给工具加一个访问口令（分享码），同事凭码进入；或
- 在平台防火墙/网络层限制来源 IP。

> 需要的话，我可以给 `app.py` 加一个轻量的口令校验中间件（环境变量 `ACCESS_TOKEN` 控制），改动很小。

---

## 更多不绑卡方案

### 路径 C：Hugging Face Spaces（✅ 不绑卡，需 Docker）

Hugging Face 账号免费、Spaces 免费基础版无需绑卡，支持用 Docker 镜像跑任意服务（包括 FastAPI）。

1. 注册 https://huggingface.co 并进入 Spaces → New Space。
2. 选 **Docker** SDK，可见性 Public 或 Private 均可。
3. 把本项目的 `Dockerfile` 推上去（需要我先为你补一个，会 `EXPOSE` 对应端口并以 `python app.py` 启动）。
4. HF 注入 `PORT` 并分配 `*.hf.space` 地址。

> 限制：免费 tier 的 CPU/内存额度有限，抓取任务较重时可能偏慢，适合轻量 / 低频使用。

### 路径 D：本机内网穿透（✅ 不绑卡 · 零云账号）

如果你**不想注册任何云平台**，也可以不部署，而是把现在这台 Mac 上跑的服务临时暴露到公网：

```bash
# 二选一（都免费、不绑卡）
brew install cloudflared && cloudflared tunnel --url http://localhost:8011
# 或
npm i -g ngrok && ngrok http 8011
```

它们会吐一个 `https://xxxx.trycloudflare.com` 或 `https://xxxx.ngrok.io` 公网链接，直接发给外网的人即可。
**前提**：你的 Mac 要一直开着、8011 服务在跑（双击「启动诊断工具.command」即可自起）。适合临时演示，不适合长期。

> 注意：内网穿透走的是**出站隧道**，不需要在 macOS 防火墙里放行 8011 端口（比局域网分享更省事）；但链接每次重启会变，且依赖你本机不关机。

---

## 不推荐：Cloud Studio 静态部署

Cloud Studio 的「静态站点部署」只起静态文件服务器，**跑不了 Python 后端**，部署上去只能看到前端壳、真实抓取会全部失败。
若要用腾讯云系，请使用 Cloud Studio 的「云端工作区」（带终端的云主机），在终端里：
```bash
pip install -r requirements.txt
python app.py   # 保持终端/进程常驻
```
