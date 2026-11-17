#!/usr/bin/env sh
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "[ERROR] 未找到 Python，请先安装 Python 3.10+"
    echo "https://www.python.org/downloads/"
    exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "[ERROR] 需要 Python 3.10+，当前版本：$("$PYTHON" --version 2>&1)"
    echo "https://www.python.org/downloads/"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[1/3] 创建虚拟环境..."
    "$PYTHON" -m venv .venv
fi

echo "[2/3] 安装依赖..."
. .venv/bin/activate
python -m pip install --upgrade pip --quiet
if ! pip install -r requirements.txt --quiet; then
    echo "[ERROR] 依赖安装失败，请检查网络后重试"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "[3/3] 生成 .env（默认管理员 admin / admin，公网部署前请修改）"
    cp .env.example .env
else
    echo "[3/3] 已存在 .env，跳过"
fi

# 监听地址和端口：环境变量优先，其次读 .env 的 PORT，默认仅本机
if [ -z "${PORT:-}" ] && [ -f ".env" ]; then
    PORT=$(sed -n 's/^PORT=\([0-9][0-9]*\).*/\1/p' .env | tail -n 1)
fi
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-9010}"

echo ""
echo "管理台: http://127.0.0.1:${PORT}/"
echo "监听: ${HOST}:${PORT}（设 HOST=0.0.0.0 可供局域网/公网访问）"
echo "默认账号: admin / admin"
echo "按 Ctrl+C 停止服务"
echo ""
python -m uvicorn main:app --host "$HOST" --port "$PORT"
