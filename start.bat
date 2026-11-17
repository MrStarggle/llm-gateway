@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found. Install Python 3.10+ and enable "Add Python to PATH".
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set "PYTHON=py -3"
)

%PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required.
    %PYTHON% --version
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo [2/3] Installing dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check your network and retry.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [3/3] Generating .env (default admin / admin; change it before public deployment)
    copy ".env.example" ".env" >nul
) else (
    echo [3/3] .env already exists, skipping
)

if "%PORT%"=="" (
    if exist ".env" (
        for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
            if /i "%%A"=="PORT" set "PORT=%%B"
        )
    )
)
if "%PORT%"=="" set "PORT=9010"
if "%HOST%"=="" set "HOST=127.0.0.1"

echo.
echo Admin console: http://127.0.0.1:%PORT%/
echo Listening: %HOST%:%PORT% (set HOST=0.0.0.0 for external access)
echo Default account: admin / admin
echo Press Ctrl+C to stop
echo.
start "" "http://127.0.0.1:%PORT%/"
python -m uvicorn main:app --host %HOST% --port %PORT%
pause
