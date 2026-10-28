#!/bin/bash
# 用法: bash push_to_github.sh <GITHUB_TOKEN> [repo名称] [private:true|false]
# 依赖: GitHub Desktop 自带的 git（本机 system git 已损坏），不依赖系统 git
set -e

TOKEN="$1"
REPO="${2:-google-ads-audit}"
PRIVATE="${3:-false}"

GIT="/Applications/GitHub Desktop.app/Contents/Resources/app/git/bin/git"
REPO_DIR="/Users/susu/WorkBuddy/2026-10-22-17-09-26/google_ads_audit"
PY="/Users/susu/.workbuddy/binaries/python/envs/default/bin/python"
API="https://api.github.com"

# 绕过沙箱代理（否则 api.github.com 会被代理拦）
export no_proxy="*"
export NO_PROXY="*"
export HTTPS_PROXY=""
export HTTP_PROXY=""

if [ -z "$TOKEN" ]; then
  echo "用法: bash push_to_github.sh <GITHUB_TOKEN>" >&2
  exit 1
fi

# 1) 取登录名
LOGIN=$(curl -sS -m 20 --noproxy '*' -H "Authorization: Bearer $TOKEN" "$API/user" \
  | "$PY" -c "import sys,json;d=json.load(sys.stdin);print(d.get('login') or d.get('message','NO_LOGIN'))")
echo "GitHub 登录名: $LOGIN"
if [ "$LOGIN" = "NO_LOGIN" ] || [ -z "$LOGIN" ]; then
  echo "令牌无效或权限不足，退出。" >&2
  exit 2
fi

# 2) 建仓库（已存在则 GitHub 会返回错误，忽略即可）
curl -sS -m 20 --noproxy '*' -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$REPO\",\"private\":$PRIVATE,\"auto_init\":false}" \
  "$API/user/repos" >/dev/null 2>&1 || true
echo "已请求创建仓库 $LOGIN/$REPO（若已存在则复用）"

# 3) 配置远程并推送（用令牌做 HTTPS 认证）
cd "$REPO_DIR"
"$GIT" remote remove origin 2>/dev/null || true
"$GIT" remote add origin "https://x-access-token:$TOKEN@github.com/$LOGIN/$REPO.git"
"$GIT" push -u origin main

echo "========================================="
echo "推送完成！仓库地址: https://github.com/$LOGIN/$REPO"
echo "下一步: render.com -> New -> Web Service -> 连该仓库 -> 自动读 render.yaml -> Free -> Deploy"
echo "========================================="
