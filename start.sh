#!/usr/bin/env bash
# Run Craw Pro locally on macOS / Linux without Docker.
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "请先安装 Python 3.10+：https://www.python.org/downloads/"; exit 1; }
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已创建 .env 配置文件，请填写 LLM_API_KEY 后重新运行：./start.sh"
  exit 0
fi
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q --disable-pip-version-check -i "${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}" -r requirements.txt
echo "正在启动 Craw Pro，启动后会自动打开 http://localhost:8000 （按 Ctrl+C 停止）"
export OPEN_BROWSER=http://localhost:8000
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --http h11 --ws none --loop asyncio
