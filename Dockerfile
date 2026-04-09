FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

ENV ARIA_QUEUE_DIR=/data/config
VOLUME ["/data/config", "/data/downloads"]

EXPOSE 8000

CMD ["ariaflow-server", "serve", "--host", "0.0.0.0", "--port", "8000"]
