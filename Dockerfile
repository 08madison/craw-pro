# Optional image with headless Chromium for JavaScript-rendered pages.
# Render's native Python runtime (render.yaml) is enough if you don't need that.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright==1.49.0
COPY . .
ENV PORT=10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
