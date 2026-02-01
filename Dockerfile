FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y curl gosu && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g @steipete/bird@0.8.0 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . .

RUN useradd -m botuser && \
    mkdir -p /app/data && \
    chown -R botuser:botuser /app && \
    chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
