@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+ 并勾选 "Add Python to PATH"
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

echo [2/3] 安装依赖...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)

if not exist ".env" (
    echo [3/3] 生成 .env（默认管理员 admin / admin，公网部署前请修改）
    copy ".env.example" ".env" >nul
) else (
    echo [3/3] 已存在 .env，跳过
)

echo.
echo 管理台: http://127.0.0.1:9010/
echo 默认账号: admin / admin
echo 按 Ctrl+C 停止服务
echo.
start "" "http://127.0.0.1:9010/"
python -m uvicorn main:app --host 127.0.0.1 --port 9010
pause
