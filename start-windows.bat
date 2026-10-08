@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Craw Pro

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有找到 Python。请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/
  echo        安装时请勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  echo 已创建 .env 配置文件，请用记事本打开它，填写 LLM_API_KEY 后保存，然后重新运行本脚本。
  notepad .env
  pause
  exit /b 0
)

if not exist .venv (
  echo 正在创建运行环境（只需一次）...
  python -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat
echo 正在安装/更新依赖...
python -m pip install -q --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt || goto :fail

echo.
echo  Craw Pro 已启动：http://localhost:8000
echo  关闭本窗口即可停止服务。
echo.
start "" http://localhost:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
exit /b 0

:fail
echo [错误] 安装失败，请把上面的错误信息截图发给开发者。
pause
exit /b 1
