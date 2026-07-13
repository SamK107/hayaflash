# ── Stage 1 : builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dépendances système pour psycopg2 + Pillow + argon2-cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    libwebp-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Installer les dépendances Python
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install -r requirements.txt


# ── Stage 2 : runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

# Libs runtime seulement (pas build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    libwebp7 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier les packages Python depuis le builder
COPY --from=builder /install /usr/local

# Copier le code source
COPY . .

# Créer les dossiers nécessaires et un user non-root
RUN groupadd -r hayaflash && useradd -r -g hayaflash hayaflash && \
    mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R hayaflash:hayaflash /app

USER hayaflash

# Collecter les fichiers statiques à la construction
RUN python manage.py collectstatic --noinput --clear 2>/dev/null || true

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health/ || exit 1

# Gunicorn avec workers géo-précalculés (2*CPU + 1)
CMD ["sh", "-c", "gunicorn config.wsgi:application \
  --bind 0.0.0.0:${PORT} \
  --workers ${GUNICORN_WORKERS:-3} \
  --threads ${GUNICORN_THREADS:-2} \
  --worker-class sync \
  --timeout 120 \
  --keep-alive 5 \
  --log-level info \
  --access-logfile - \
  --error-logfile -"]
