FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_DEBUG=false \
    DJANGO_DB_PATH=/app/data/db.sqlite3 \
    DJANGO_MEDIA_ROOT=/app/media \
    DJANGO_STATIC_ROOT=/app/staticfiles

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r /app/requirements.txt

COPY backend/ /app/
COPY docker/entrypoint.sh /usr/local/bin/synthlab-entrypoint

RUN chmod 0755 /usr/local/bin/synthlab-entrypoint && \
    mkdir -p /app/data /app/media /app/staticfiles && \
    DJANGO_SECRET_KEY=build-only-not-used python manage.py collectstatic --noinput && \
    useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app /usr/local/bin/synthlab-entrypoint

USER appuser
EXPOSE 8000

ENTRYPOINT ["synthlab-entrypoint"]
