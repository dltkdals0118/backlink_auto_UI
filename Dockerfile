# Playwright + Chromium 포함 이미지 (자동 등록 브라우저 자동화용)
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 클라우드에서 외부 접속 허용
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["python", "web_app.py"]
