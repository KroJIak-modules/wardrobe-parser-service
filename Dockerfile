FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    nodejs \
    npm \
    chromium \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY browser_runner ./browser_runner

RUN cd /app/browser_runner && npm ci --omit=dev

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
