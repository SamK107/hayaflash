# Workflow P6 — CI/CD + Production Hardening
> Phase 6 · Durée estimée : ~1 semaine  
> Prérequis : P0 à P5

---

## Objectif

Déploiement reproductible avec Docker, pipeline CI/CD GitHub Actions, tests complets, et smoke tests post-deploy.

---

## Étape 6.1 — `.github/workflows/ci.yml`

```yaml
name: CI — Tests & Qualité

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    name: Tests Django
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: hayaflash_test
          POSTGRES_USER: hayaflash
          POSTGRES_PASSWORD: testpass
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Check Django configuration
        env:
          DJANGO_SETTINGS_MODULE: config.settings.test
          SECRET_KEY: ci-test-secret-key
        run: python manage.py check

      - name: Run migrations
        env:
          DJANGO_SETTINGS_MODULE: config.settings.test
          SECRET_KEY: ci-test-secret-key
          DATABASE_URL: postgres://hayaflash:testpass@localhost:5432/hayaflash_test
        run: python manage.py migrate --noinput

      - name: Run tests with coverage
        env:
          DJANGO_SETTINGS_MODULE: config.settings.test
          SECRET_KEY: ci-test-secret-key
          DATABASE_URL: postgres://hayaflash:testpass@localhost:5432/hayaflash_test
        run: |
          pip install pytest-django pytest-cov
          pytest --ds=config.settings.test \
                 --cov=. \
                 --cov-report=term-missing \
                 --cov-fail-under=60 \
                 -v

  lint:
    name: Qualité du code
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install ruff
      - run: ruff check .
```

---

## Étape 6.2 — `.github/workflows/deploy.yml`

```yaml
name: Deploy HayaFlash

on:
  push:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build:
    name: Build & Push Docker Image
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Login to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}

  deploy-staging:
    name: Deploy → Staging
    needs: build
    runs-on: ubuntu-latest
    environment: staging

    steps:
      - name: Deploy to staging server
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.STAGING_HOST }}
          username: ${{ secrets.STAGING_USER }}
          key:      ${{ secrets.STAGING_SSH_KEY }}
          script: |
            cd /srv/hayaflash
            docker pull ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
            docker-compose -f docker-compose.production.yml up -d
            docker-compose -f docker-compose.production.yml exec -T web python manage.py migrate --noinput
            docker-compose -f docker-compose.production.yml exec -T web python manage.py collectstatic --noinput

      - name: Smoke test staging
        run: |
          sleep 10
          curl -f https://staging.hayaflash.com/api/v1/health/ || exit 1
          echo "✅ Staging smoke test passed"

  deploy-prod:
    name: Deploy → Production
    needs: deploy-staging
    runs-on: ubuntu-latest
    environment: production  # Requires manual approval in GitHub

    steps:
      - name: Deploy to production server
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.PROD_HOST }}
          username: ${{ secrets.PROD_USER }}
          key:      ${{ secrets.PROD_SSH_KEY }}
          script: |
            cd /srv/hayaflash
            docker pull ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
            docker-compose -f docker-compose.production.yml up -d --no-deps web
            docker-compose -f docker-compose.production.yml exec -T web python manage.py migrate --noinput

      - name: Smoke test production
        run: |
          sleep 15
          curl -f https://hayaflash.com/api/v1/health/ || exit 1
          echo "✅ Production smoke test passed"
```

---

## Étape 6.3 — `docker-compose.production.yml`

```yaml
version: "3.9"

services:
  db:
    image: postgres:15-alpine
    restart: always
    env_file: .env.production
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: always
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru

  web:
    image: ghcr.io/VOTRE_ORG/hayaflash:latest
    restart: always
    env_file: .env.production
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.prod
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - media_data:/app/media
      - static_data:/app/staticfiles

  celery_worker:
    image: ghcr.io/VOTRE_ORG/hayaflash:latest
    restart: always
    command: celery -A config worker --loglevel=info --concurrency=4
    env_file: .env.production
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.prod
    depends_on:
      - db
      - redis

  celery_beat:
    image: ghcr.io/VOTRE_ORG/hayaflash:latest
    restart: always
    command: celery -A config beat --loglevel=info
    env_file: .env.production
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.prod
    depends_on:
      - db
      - redis

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infra/nginx/hayaflash.conf:/etc/nginx/conf.d/default.conf:ro
      - media_data:/app/media:ro
      - static_data:/app/staticfiles:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - web

volumes:
  postgres_data:
  media_data:
  static_data:
```

---

## Étape 6.4 — `infra/scripts/smoke_test.sh`

```bash
#!/bin/bash
set -e

BASE_URL="${1:-https://hayaflash.com}"

echo "🔍 Smoke tests sur $BASE_URL"

# Health check
curl -sf "$BASE_URL/api/v1/health/" | grep -q '"status": "ok"'
echo "✅ Health check OK"

# Page publique (accueil)
curl -sf -o /dev/null -w "%{http_code}" "$BASE_URL/" | grep -q "200"
echo "✅ Page accueil OK"

# Page calendrier public
curl -sf -o /dev/null -w "%{http_code}" "$BASE_URL/ventes/" | grep -q "200"
echo "✅ Page calendrier OK"

# API flash sales
curl -sf "$BASE_URL/api/v1/flash-sales/" | grep -q "^\["
echo "✅ API flash sales OK"

echo "🎉 Tous les smoke tests passent !"
```

---

## Étape 6.5 — `scripts/backup-db.sh`

```bash
#!/bin/bash
set -e

DB_NAME="${DB_NAME:-hayaflash}"
DB_USER="${DB_USER:-hayaflash}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="$BACKUP_DIR/hayaflash_$TIMESTAMP.dump"

mkdir -p "$BACKUP_DIR"
pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$FILENAME"
echo "✅ Backup créé : $FILENAME"

# Supprimer les backups de plus de 30 jours
find "$BACKUP_DIR" -name "*.dump" -mtime +30 -delete
echo "🧹 Anciens backups nettoyés"
```

---

## Étape 6.6 — `ruff.toml` (qualité du code)

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "W", "I", "N", "UP"]
ignore = ["E501"]

[tool.ruff.per-file-ignores]
"*/migrations/*.py" = ["E501", "F401"]
```

---

## Étape 6.7 — `pytest.ini`

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.test
python_files = tests.py test_*.py *_tests.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

---

## Checklist Finale P6

- [ ] `docker-compose up` → app accessible sur `http://localhost:8000`
- [ ] `docker-compose -f docker-compose.production.yml config` valide
- [ ] `ruff check .` → 0 erreur
- [ ] `pytest --ds=config.settings.test` → coverage > 60%
- [ ] Push sur `main` → CI passe (GitHub Actions)
- [ ] CI green → deploy staging automatique
- [ ] Smoke test staging passe : `/api/v1/health/`, `/ventes/`, `/api/v1/flash-sales/`
- [ ] Deploy prod nécessite approbation manuelle (GitHub Environment protection)
- [ ] `scripts/backup-db.sh` tourne sans erreur
- [ ] HTTPS configuré sur staging via Let's Encrypt

---

## Résumé Commandes de Déploiement Local

```bash
# Démarrer la stack complète
docker-compose up -d

# Voir les logs
docker-compose logs -f web

# Migrations
docker-compose exec web python manage.py migrate

# Créer un superuser
docker-compose exec web python manage.py createsuperuser

# Tester Celery
docker-compose exec celery_worker celery -A config inspect active

# Smoke test local
bash infra/scripts/smoke_test.sh http://localhost:8000
```
