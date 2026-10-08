# Image with headless Chromium, so JavaScript-rendered pages can be crawled too.
# Used by Render (Docker runtime) and by docker-compose.yml for running locally.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
WORKDIR /app
# Optional PyPI mirror for faster builds, e.g. https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=""
COPY requirements.txt .
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+-i "$PIP_INDEX_URL"} -r requirements.txt playwright==1.49.0
COPY . .
ENV PORT=10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
