# Layout worker image. Runs on Render as a background worker, or on a Nebius
# instance for heavy autorouting; it only needs REDIS_URL to reach the queue.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY chatpcb ./chatpcb
COPY prompts ./prompts
COPY data ./data
RUN pip install --no-cache-dir ".[cloud]"

CMD ["python", "-m", "chatpcb.worker"]
