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

if [ ! -d ".venv" ]; then
    echo "[1/3] 创建虚拟环境..."
    "$PYTHON" -m venv .venv
fi

echo "[2/3] 安装依赖..."
. .venv/bin/activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

if [ ! -f ".env" ]; then
    echo "[3/3] 生成 .env（默认管理员 admin / admin，公网部署前请修改）"
    cp .env.example .env
else
    echo "[3/3] 已存在 .env，跳过"
fi

echo ""
echo "管理台: http://127.0.0.1:9010/"
echo "默认账号: admin / admin"
echo "按 Ctrl+C 停止服务"
echo ""
python -m uvicorn main:app --host 127.0.0.1 --port 9010
