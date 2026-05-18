@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM —— 找 Python：优先项目 .venv，其次全局 Python 3.12，最后 PATH 上的 python ——
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if "%PYTHON_EXE%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"

if not exist "feishu_bot.py" (
    echo [错误] feishu_bot.py 不在当前目录
    pause
    exit /b 1
)

if not exist "%APPDATA%\baokuan-rewrite\.env" (
    echo [错误] 凭证文件不存在: %APPDATA%\baokuan-rewrite\.env
    echo        飞书是可选功能。如果你要用：
    echo          1. 创建目录 %APPDATA%\baokuan-rewrite\
    echo          2. 在里面新建 .env，填入：
    echo             FEISHU_APP_ID / FEISHU_APP_SECRET / DEEPSEEK_API_KEY
    echo          3. 详见 docs\飞书集成可选.md
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
echo ============================================================
echo  启动飞书机器人 - 爆款文案改写
echo  Python:   %PYTHON_EXE%
echo  凭证来源: %%APPDATA%%\baokuan-rewrite\.env (自动加载)
echo  日志:     logs\feishu_chat.log + logs\feishu_tasks.log
echo  停止:     Ctrl+C 或 关闭这个窗口
echo ============================================================
echo.

"%PYTHON_EXE%" feishu_bot.py
echo.
echo [bot 进程退出码: %ERRORLEVEL%]
pause
