# ---- build stage ----
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY database ./database
COPY tests ./tests

# Non-root runtime user; uploads volume must be writable by it
RUN useradd --create-home --uid 10001 taskflex \
    && mkdir -p /app/uploads \
    && chown -R taskflex:taskflex /app
USER taskflex

ENV UPLOAD_DIR=/app/uploads

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

ENTRYPOINT ["docker-entrypoint.sh"]
