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

RUN npm config set fetch-retries 5 \
    && npm config set fetch-retry-factor 2 \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && cd /app/browser_runner \
    && if [ -d node_modules ]; then \
        echo "Using browser_runner/node_modules from build context"; \
    else \
        for attempt in 1 2 3; do \
            npm ci --omit=dev --prefer-offline --no-audit --no-fund && exit 0; \
            if [ "$attempt" -eq 3 ]; then exit 1; fi; \
            npm cache clean --force; \
            sleep 5; \
        done; \
    fi

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
