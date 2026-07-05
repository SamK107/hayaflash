# Workflow P0 — Foundation & Qualité
> Phase 0 · Durée estimée : ~1 semaine  
> Exécuté par : Cowork (Claude)  
> Prérequis : aucun

---

## Objectif

Corriger les dettes techniques de configuration, installer Tailwind + Alpine.js sur `base.html`, configurer Celery, créer l'infrastructure Docker locale. Zéro code métier dans cette phase — uniquement fondations et qualité.

---

## Étape 0.1 — Corriger `requirements.txt`

**Fichier** : `requirements.txt`

Ajouter :
```
django[argon2]==5.2.13       # Argon2 password hasher
celery==5.4.0                # Tâches async
redis==5.2.1                 # Client Redis pour Celery
django-environ==0.12.0       # Env vars propres (optionnel, parallèle à python-dotenv)
sentry-sdk[django]==2.28.0  # Monitoring production
django-debug-toolbar==5.2.0  # Dev tooling
```

**Validation** : `pip install -r requirements.txt` sans erreur.

---

## Étape 0.2 — Corriger `config/settings/base.py`

**Modifications** :

```python
# Langue et fuseau horaire (contexte africain)
LANGUAGE_CODE = "fr-fr"        # était "en-us"
TIME_ZONE = "Africa/Bamako"    # était "UTC"

# Argon2 (plus robuste que PBKDF2)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Logging enrichi (DJANGO_REFERENCE)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "accounts": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "orders": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "flash_sales": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}

# Upload limits (photos produits 5 Mo)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Celery
CELERY_BROKER_URL = REDIS_URL or "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = REDIS_URL or "redis://localhost:6379/0"
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Africa/Bamako"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_BEAT_SCHEDULE = {
    "auto-open-scheduled-sales": {
        "task": "flash_sales.tasks.auto_open_scheduled_sales",
        "schedule": 60.0,
    },
    "auto-close-live-sales": {
        "task": "flash_sales.tasks.auto_close_live_sales",
        "schedule": 60.0,
    },
}
```

**Validation** : `python manage.py check` sans warning.

---

## Étape 0.3 — Créer `config/settings/test.py`

**Nouveau fichier** : `config/settings/test.py`

```python
"""Settings pour CI et tests locaux."""
from .base import *  # noqa: F403

SECRET_KEY = "django-insecure-test-key-not-for-production"
DEBUG = False
ALLOWED_HOSTS = ["*"]

# DB en mémoire — rapide, isolée
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Pas de Redis en CI
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Celery synchrone en tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Emails capturés
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Désactiver le password hashage lent (tests plus rapides)
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Médias en mémoire
DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"
```

---

## Étape 0.4 — Enrichir `config/settings/dev.py`

**Modifications** :

```python
from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
SECRET_KEY = "django-insecure-dev-key-not-for-production"

# Debug Toolbar
INSTALLED_APPS += ["debug_toolbar"]
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
INTERNAL_IPS = ["127.0.0.1", "::1"]

# Emails dans la console
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Logs SQL en dev (optionnel)
# LOGGING["loggers"]["django.db.backends"] = {"handlers": ["console"], "level": "DEBUG"}
```

---

## Étape 0.5 — Enrichir `config/settings/prod.py`

**Modifications** :

```python
from .base import *  # noqa: F403

SECRET_KEY = require_env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = _csv("ALLOWED_HOSTS")

# HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Sentry
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.05,
        send_default_pii=False,
    )
```

---

## Étape 0.6 — Créer `config/celery.py`

**Nouveau fichier** : `config/celery.py`

```python
"""Celery application for HayaFlash."""
from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("hayaflash")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
```

**Modifier `config/__init__.py`** :

```python
from .celery import app as celery_app  # noqa: F401

__all__ = ("celery_app",)
```

---

## Étape 0.7 — Refaire `templates/base.html`

**Fichier** : `templates/base.html`

```html
<!DOCTYPE html>
<html lang="fr" class="h-full">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
  <meta name="theme-color" content="#E63946" />
  <title>{% block title %}HayaFlash{% endblock %}</title>

  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            primary:  '#E63946',
            gold:     '#FFB800',
            success:  '#22C55E',
            warning:  '#F59E0B',
            danger:   '#EF4444',
          },
          fontFamily: {
            sans: ['Inter', 'system-ui', 'sans-serif'],
          },
        }
      }
    }
  </script>

  <!-- Alpine.js -->
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>

  <!-- HTMX -->
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>

  <!-- Lucide Icons -->
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>

  <!-- Inter font -->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />

  <style>
    [x-cloak] { display: none !important; }
    .live-pulse { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  </style>

  {% block extra_head %}{% endblock %}
</head>
<body class="h-full bg-gray-50 font-sans text-gray-900" x-data>

  <!-- Offline Banner -->
  <div
    x-data="{ online: navigator.onLine }"
    x-init="window.addEventListener('online', () => online = true); window.addEventListener('offline', () => online = false)"
    x-show="!online"
    x-cloak
    class="fixed top-0 inset-x-0 z-50 bg-yellow-500 text-white text-center text-sm py-2 font-semibold"
  >
    ⚠ Hors ligne — vos commandes seront synchronisées automatiquement
  </div>

  <!-- Toast Container -->
  <div
    id="toast-container"
    class="fixed bottom-4 inset-x-4 z-50 flex flex-col gap-2 pointer-events-none"
    aria-live="polite"
  ></div>

  {% if user.is_authenticated %}
  <!-- Nav Vendeur -->
  {% include "partials/_nav_seller.html" %}
  {% endif %}

  <!-- Main Content -->
  <main class="{% block main_class %}{% endblock %}">
    {% block body %}{% endblock %}
  </main>

  <!-- Messages Django → Toasts -->
  {% if messages %}
  <script>
    document.addEventListener('DOMContentLoaded', function() {
      {% for message in messages %}
      window.HF && window.HF.toast("{{ message|escapejs }}", "{{ message.tags }}");
      {% endfor %}
    });
  </script>
  {% endif %}

  <!-- HayaFlash JS Utils -->
  <script>
    window.HF = {
      toast(msg, type = 'info') {
        const colors = { success: 'bg-green-600', error: 'bg-red-600', warning: 'bg-yellow-500', info: 'bg-gray-800' };
        const el = document.createElement('div');
        el.className = `${colors[type] || colors.info} text-white px-4 py-3 rounded-xl shadow-lg text-sm font-medium pointer-events-auto transition-all duration-300`;
        el.textContent = msg;
        document.getElementById('toast-container').appendChild(el);
        setTimeout(() => el.remove(), 4000);
      }
    };
    // Init Lucide icons
    lucide.createIcons();
  </script>

  {% block extra_js %}{% endblock %}
</body>
</html>
```

---

## Étape 0.8 — Créer `templates/partials/_nav_seller.html`

**Nouveau fichier** : `templates/partials/_nav_seller.html`

```html
<nav class="bg-white border-b border-gray-200 px-4 h-14 flex items-center justify-between sticky top-0 z-40">
  <a href="{% url 'core:home' %}" class="flex items-center gap-2">
    <span class="text-primary font-black text-lg tracking-tight">HAYA<span class="text-gold">FLASH</span></span>
  </a>
  <div class="flex items-center gap-3">
    <a href="/seller/" class="text-gray-600 hover:text-primary transition-colors" title="Dashboard">
      <i data-lucide="layout-dashboard" class="w-5 h-5"></i>
    </a>
    <a href="/seller/flash-sales/" class="text-gray-600 hover:text-primary transition-colors" title="Mes ventes">
      <i data-lucide="zap" class="w-5 h-5"></i>
    </a>
    <a href="{% url 'accounts:logout' %}" class="text-gray-500 hover:text-red-500 transition-colors" title="Déconnexion">
      <i data-lucide="log-out" class="w-5 h-5"></i>
    </a>
  </div>
</nav>
```

---

## Étape 0.9 — Créer `Dockerfile`

**Nouveau fichier** : `Dockerfile`

```dockerfile
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dépendances système (psycopg2, Pillow)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpq-dev gcc libjpeg-dev libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collecte des static en build
ARG DJANGO_SETTINGS_MODULE=config.settings.prod
ENV DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}

RUN python manage.py collectstatic --noinput 2>/dev/null || echo "collectstatic skipped (no DB needed)"

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

---

## Étape 0.10 — Créer `docker-compose.yml`

**Nouveau fichier** : `docker-compose.yml`

```yaml
version: "3.9"

services:
  db:
    image: postgres:15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: hayaflash
      POSTGRES_USER: hayaflash
      POSTGRES_PASSWORD: hayaflash_dev
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    env_file: .env
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.dev
      DATABASE_URL: postgres://hayaflash:hayaflash_dev@db:5432/hayaflash
      REDIS_URL: redis://redis:6379/0
    volumes:
      - .:/app
      - media_data:/app/media
    ports:
      - "8000:8000"
    depends_on:
      - db
      - redis

  celery_worker:
    build: .
    command: celery -A config worker --loglevel=info
    env_file: .env
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.dev
      DATABASE_URL: postgres://hayaflash:hayaflash_dev@db:5432/hayaflash
      REDIS_URL: redis://redis:6379/0
    volumes:
      - .:/app
    depends_on:
      - db
      - redis

  celery_beat:
    build: .
    command: celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    env_file: .env
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.dev
      DATABASE_URL: postgres://hayaflash:hayaflash_dev@db:5432/hayaflash
      REDIS_URL: redis://redis:6379/0
    volumes:
      - .:/app
    depends_on:
      - db
      - redis

volumes:
  postgres_data:
  media_data:
```

---

## Étape 0.11 — Créer `infra/nginx/hayaflash.conf`

**Nouveau fichier** : `infra/nginx/hayaflash.conf`

```nginx
upstream hayaflash_backend {
    server web:8000;
}

server {
    listen 80;
    server_name _;

    client_max_body_size 10M;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;
    gzip_min_length 1000;

    # Rate limit sur l'API commandes (anti-spam)
    limit_req_zone $binary_remote_addr zone=orders_zone:10m rate=30r/m;

    location /static/ {
        alias /app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /app/media/;
        expires 7d;
    }

    location /api/v1/orders/ {
        limit_req zone=orders_zone burst=10 nodelay;
        proxy_pass http://hayaflash_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://hayaflash_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
    }
}
```

---

## Checklist Finale P0

- [ ] `pip install -r requirements.txt` OK
- [ ] `python manage.py check` OK
- [ ] `python manage.py check --deploy --settings=config.settings.staging` OK
- [ ] `python manage.py test --settings=config.settings.test` OK
- [ ] `docker-compose up` → app accessible sur `http://localhost:8000`
- [ ] `base.html` avec Tailwind visible dans le browser
- [ ] `python -c "from config.celery import app; print(app)"` OK
- [ ] `TIME_ZONE = "Africa/Bamako"` confirmé dans les settings chargés
