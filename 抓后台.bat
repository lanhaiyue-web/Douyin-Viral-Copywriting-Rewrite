@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM —— 找 Python：优先项目 .venv，其次全局 Python 3.12，最后 PATH 上的 python ——
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if "%PYTHON_EXE%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"

set "PYTHONUTF8=1"
echo ============================================================
echo  抓抖音创作者中心后台 → 写入 context\my-history-backend.md
echo  Python: %PYTHON_EXE%
echo
echo  没登录或 session 过期：先双击 扫码登录抖音.bat
echo ============================================================
echo.

"%PYTHON_EXE%" tools\fetch_douyin_backend.py %*

echo.
echo [退出码: %ERRORLEVEL%]
pause
