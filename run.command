#!/bin/bash
# 双击这个文件即可启动。首次运行会装依赖（几分钟），之后就很快了。
set -euo pipefail
cd "$(dirname "$0")"

PORT=8756
PY=.venv/bin/python

echo ""
echo "  video2text 正在启动…"
echo ""

# --- 检查前置依赖 ---
if ! command -v uv >/dev/null 2>&1; then
  echo "  ✗ 缺少 uv（Python 环境管理器）"
  echo "    装一下：brew install uv"
  echo ""
  read -n 1 -s -r -p "  按任意键关闭…"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "  ✗ 缺少 ffmpeg（转写和音频处理需要）"
  echo "    装一下：brew install ffmpeg"
  echo ""
  read -n 1 -s -r -p "  按任意键关闭…"
  exit 1
fi

# --- 准备虚拟环境 ---
if [ ! -x "$PY" ]; then
  echo "  → 首次运行，正在创建虚拟环境…"
  uv venv --python 3.12 .venv
fi

# requirements.txt 变了才重装，省得每次启动都等
STAMP=.venv/.requirements.sha
CURRENT=$(shasum -a 256 requirements.txt | awk '{print $1}')
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$CURRENT" ]; then
  echo "  → 正在安装依赖…（首次会下载模型相关包，请耐心等）"
  uv pip install --python "$PY" -r requirements.txt
  echo "$CURRENT" > "$STAMP"
fi

# --- 端口被占就换一个 ---
while lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; do
  echo "  ! 端口 $PORT 被占用，试 $((PORT + 1))"
  PORT=$((PORT + 1))
done

# --- 起服务，等端口通了再开浏览器 ---
"$PY" app.py --port "$PORT" 2>/dev/null &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
    open "http://127.0.0.1:$PORT"
    break
  fi
  sleep 0.5
done

echo ""
echo "  ────────────────────────────────────────"
echo "  已启动 → http://127.0.0.1:$PORT"
echo "  关掉这个窗口或按 Ctrl+C 即可停止"
echo "  ────────────────────────────────────────"
echo ""

wait $SERVER_PID
