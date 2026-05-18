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
echo  启动本地网页 - 爆款文案改写
echo  Python: %PYTHON_EXE%
echo  浏览器会自动打开 http://localhost:8501
echo ============================================================
echo.

"%PYTHON_EXE%" -m streamlit run app.py
pause
