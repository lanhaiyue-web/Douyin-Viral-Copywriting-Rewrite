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
echo  抖音创作者中心 扫码登录
echo  Python: %PYTHON_EXE%
echo
echo  会弹出一个 Chromium 窗口
echo  用手机抖音扫窗口里的二维码登录
echo  登录成功后 cookies 会写入 .auth\
echo
echo  注意：内置的 ensure_login 检测 cookie 名 sessionid，
echo  实测扫码后 cookie 名可能不同会触发 timeout 提示，
echo  但 cookies 已经写盘，关掉窗口直接跑 抓后台.bat 验证即可。
echo ============================================================
echo.

"%PYTHON_EXE%" tools\douyin_session\crawler.py

echo.
echo [扫码流程结束] 现在双击 抓后台.bat 验证登录态
pause
