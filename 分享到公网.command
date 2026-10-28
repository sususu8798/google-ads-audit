#!/bin/bash
# Google Ads 落地页诊断工具 —— 一键分享到公网（零账号 / 临时）
# 作用：确保本地诊断服务在跑，再用 cloudflared 建立公网隧道，
#       终端会显示 https://xxxx.trycloudflare.com 的公网地址，发给外部人员即可。
# 注意：保持此窗口打开 = 持续分享；关闭窗口 = 停止分享。链接每次重开都会变。

DIR="/Users/susu/WorkBuddy/2026-10-22-17-09-26/google_ads_audit"
PY="/Users/susu/.workbuddy/binaries/python/envs/default/bin/python"
PORT=8011
cd "$DIR" || { echo "找不到项目目录：$DIR"; exit 1; }

# 1) 确保诊断服务在运行
if ! curl -s --noproxy '*' -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then
  echo "🚀 启动诊断服务…"
  HOST=0.0.0.0 PORT=$PORT nohup "$PY" app.py >/tmp/gaa_server.log 2>&1 &
  disown
  for i in $(seq 1 12); do
    curl -s --noproxy '*' -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null && break
    sleep 1
  done
fi

if ! curl -s --noproxy '*' -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then
  echo "⚠️ 诊断服务启动失败，请先双击『启动诊断工具.command』再试。日志：/tmp/gaa_server.log"
  sleep 3; exit 1
fi

echo "✅ 诊断服务已就绪（本地 http://localhost:$PORT）"
echo "🌐 正在建立公网隧道…… 稍候终端会显示一行 https://xxxx.trycloudflare.com 的公网地址"
echo "   把这个地址发给外部人员即可访问。保持此窗口打开 = 持续分享；关闭窗口 = 停止分享。"
echo "----------------------------------------------------------------"

# 2) 建立临时公网隧道（quick tunnel，无需账号）
exec ./tools/cloudflared tunnel --url "http://127.0.0.1:$PORT"
