# Multi-stage Docker build for JobSentry
FROM python:3.10-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Create dummy package file structure
RUN mkdir -p job_sentry && touch job_sentry/__init__.py

RUN pip install --no-cache-dir --user .[dashboard]

# Final runner stage
FROM python:3.10-slim AS runner

WORKDIR /app

COPY --from=builder /root/.local /root/.local
COPY job_sentry/ job_sentry/

# Install playwright system browsers inside the final image
RUN pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
EXPOSE 8501

CMD ["python", "-m", "uvicorn", "job_sentry.app:app", "--host", "0.0.0.0", "--port", "8000"]
