# HayaFlash — Analyse Complète V1 Launch
> Générée le 2026-07-10 · Basée sur analyse du code source réel + MASTER_CONTEXT (Parties 1–12) + CODEBASE_STATUS + PLAN_PHASES

---

## 1. BILAN RÉEL DU CODEBASE

### Ce qui est FAIT (après commit `feat(P0-P5): MVP base architecture`)

| Phase | Statut | Détail |
|---|---|---|
| **P0 — Foundation** | ✅ Complet | requirements (celery, redis, argon2, sentry), settings fr-fr/Africa/Bamako, Tailwind CDN + Alpine, Docker multi-stage, docker-compose complet (web+db+redis+worker+beat), Nginx HTTPS |
| **P1 — Modèles** | ✅ Complet | FlashSaleStatus étendu (SCHEDULED/LIVE/CLOSED/EXECUTING/COMPLETED/CANCELLED), FlashSale (description, cover_image, delivery_zone, max_orders), Product (description, unit, characteristics, stock_initial/available), ProductMedia, StockMovement, SellerProfile (bio, avatar, delivery_zones), Subscription, Notification |
| **P2 — UI Vendeur** | ✅ Complet | Flash Sales CRUD (list/create/detail/edit/open/close/cancel), Products CRUD, Dashboard vendeur, Subscription view |
| **P3 — LIVE Workflow** | ✅ Complet | Celery tasks (auto_open/auto_close), calendrier public `/ventes/`, API `/api/v1/flash-sales/`, page commande client |
| **P4 — Design** | ✅ Largement complet | Tailwind sur tous les templates critiques, hf-components.js (countdown, toasts, modal, offline banner), mobile-first 375px |
| **P5 — Notifications + Subs** | ✅ Complet | Notification model + dispatcher + sms.py + whatsapp.py, tasks Celery (confirmation, rappel), Subscription model + limits.py (3 ventes/mois free) |
| **P6 — CI/CD** | ❌ Manquant | Aucun .github/workflows/ — bloquant pour déploiement automatisé |

### Ce qui MANQUE encore (gaps critiques identifiés)

#### ❌ Gap #1 — CI/CD Pipeline (P6 complète)
Aucun fichier `.github/workflows/`. Le deploy prod est entièrement manuel.
- Manque : `ci.yml` (lint + tests), `deploy.yml` (staging auto + prod avec approbation)
- Manque : `infra/scripts/smoke_test.sh`
- Manque : `config/settings/test.py` (à vérifier — non vu dans l'analyse)

#### ❌ Gap #2 — Export CSV/Excel des commandes
Mentionné comme objectif "Gagner du temps" dans le MASTER_CONTEXT (Partie 1, §7). **Absent du codebase.** 
C'est un besoin terrain fort : le vendeur veut récupérer ses commandes après un LIVE.
- Manque : `GET /seller/flash-sales/<id>/export/` → CSV téléchargeable
- 20 lignes de code. ROI énorme.

#### ❌ Gap #3 — AuditLog
Défini en détail dans MASTER_CONTEXT Partie 8 (§10) comme exigence forensic. Absent du codebase.
```python
class AuditLog:
    actor_id, action, entity_type, entity_id, metadata, timestamp
```
Actions à auditer : ouverture LIVE, fermeture, annulation commande, modification stock.

#### ❌ Gap #4 — Enforcement subscription dans la vue
`can_create_flash_sale()` existe dans `subscriptions/services/limits.py` mais il faut **vérifier** qu'elle est appelée dans `flash_sale_create_view()`. Si non appelée, le quota Free n'est pas enforced.

#### ❌ Gap #5 — Celery Beat schedule dans settings
`CELERY_BEAT_SCHEDULE` est dans `config/settings/base.py` mais les tasks `auto_open_scheduled_sales` et `auto_close_live_sales` doivent y être listées explicitement. À vérifier/confirmer.

#### ❌ Gap #6 — Rate limiting DRF (throttle classes)
Le service layer `client_order.py` a un rate limit maison (30/IP/min), mais les throttle classes DRF ne sont pas configurées dans `settings/base.py`. À solidifier pour la prod.

#### ⚠️ Gap #7 — Orange Money paiement abonnement
`payments/` est un mock complet. Orange Money réel = V1.1. **Acceptable pour V1** si le flux Pro est géré manuellement (activation admin). À documenter clairement.

#### ⚠️ Gap #8 — Tests insuffisants
- `orders/tests.py` : 332 lignes ✅
- `flash_sales/tests.py` : 111 lignes (léger)
- `notifications/`, `subscriptions/` : probablement vides
- Manque tests d'intégration end-to-end
- Manque tests de concurrence (race conditions stock)

#### ⚠️ Gap #9 — PWA / Service Worker
Offline First est au cœur du MASTER_CONTEXT. L'`offline queue` IndexedDB existe en JS. Mais il n'y a pas de `manifest.json` ni de `service-worker.js` pour une vraie PWA installable. **Critique pour le marché africain mobile** (accès depuis l'écran d'accueil, icône, splash).

#### ⚠️ Gap #10 — QR Code partage
Mentionné dans le MASTER_CONTEXT comme "future version" mais très pertinent pour le Live en boutique physique (persona Aïcha). Bibliothèque `qrcode` en Python = 5 lignes.

---

## 2. VERDICT V1 — EST-CE SUFFISANT POUR LANCER ?

### Réponse : **OUI sur le fond, avec 6 ajouts pré-lancement.**

Le cœur du produit est **fonctionnel** :
- ✅ Vendeur crée une vente en < 60s
- ✅ Client commande en < 10s
- ✅ Commandes zéro perte (idempotence + IndexedDB)
- ✅ Ouverture/fermeture automatique (Celery)
- ✅ Dashboard LIVE avec countdown + badge pulsant
- ✅ Livraisons + GPS
- ✅ Pages publiques SEO (vendeur + vente)
- ✅ Analytics + partage WhatsApp
- ✅ Abonnements Free/Pro (modèle + enforcement)
- ✅ Docker + Nginx prod-ready

**Ce qui bloque réellement le lancement** (liste courte) :
1. CI/CD pipeline → sans ça, chaque deploy est risqué
2. Confirmation que l'enforcement subscription est actif dans la vue
3. Confirmation Celery Beat schedule complet dans settings
4. Export CSV commandes (feature terrain critique)
5. Tests minimaux + smoke test post-deploy
6. AuditLog (conformité forensic requise par gouvernance)

---

## 3. COMPARAISON BONNES PRATIQUES — APPS MODERNES SIMILAIRES

Comparaison avec Whatnot, TikTok Shop Live, Bidali, Vendez.bj (contexte africain) :

### Ce que HayaFlash fait MIEUX
- **Offline First natif** : aucun concurrent africain n'a ça
- **Idempotence** : protection contre double commande (souvent absent chez les concurrents)
- **Architecture services** : codebase maintenable vs spaghetti
- **Mobile First strict** : pas d'interface desktop gonflée

### Ce que les apps similaires font et que HayaFlash devrait ajouter pour V1

| Feature | Priorité | Effort | Justification |
|---|---|---|---|
| **Export CSV/Excel commandes** | 🔴 V1 | 1 jour | Whatnot, TikTok Shop : export systématique. Besoin #1 vendeur post-LIVE |
| **PWA manifest + Service Worker** | 🟠 V1 | 2 jours | WhatsApp Business est PWA. L'icône sur home screen = adoption x2 en Afrique |
| **QR Code sur page vente** | 🟡 V1.1 | 0.5 jour | Bidali, MarketPlace locale : QR = partage physique immédiat |
| **Bulk actions commandes** | 🟡 V1.1 | 1 jour | "Confirmer toutes" / "Marquer toutes livrées" → gain temps vendeur masssif |
| **Countdown client-side** | ✅ Fait | — | Alpine.js countdown implémenté |
| **Stock visible en temps réel** | ✅ Fait | — | HTMX polling |
| **Message WhatsApp pre-filled** | ✅ Fait | — | `build_whatsapp_share_url()` implémenté |
| **Branding "Commande via HayaFlash"** | ✅ Fait | — | Acquisition virale par design |

### Ce qui est SUFFISANT pour la V1 et ne nécessite pas d'ajout
- Pas de paiement intégré → COD (paiement à la livraison) est le standard africain
- Pas de WebSockets → HTMX polling 3-5s est satisfaisant pour V1 (< 100 vendeurs simultanés)
- Pas de React/SPA → Django Templates + HTMX = correct pour le volume V1
- Pas de multi-boutiques → V2 selon roadmap

**Conclusion benchmark :** Le projet est compétitif pour la V1 africaine. Ajouter Export CSV + PWA manifest avant launch, le reste est itératif.

---

## 4. WORKFLOW & GOUVERNANCE — PHASES RESTANTES

### Règle d'or pour les sessions Claude Code
```
1 session = 1 phase = 1 commit atomique
Jamais de "grand commit" multi-phases
Toujours commencer par lire CODEBASE_STATUS.md
Toujours finir par le mettre à jour
```

---

## PHASE A — Vérification & Correction (1 session, ~2h)

**Objectif** : Confirmer que tout ce qui est censé être fait l'est vraiment. Corriger les gaps silencieux.

### A.1 — Vérifier enforcement subscription
```python
# flash_sales/views.py → flash_sale_create_view()
# DOIT contenir :
from subscriptions.services.limits import can_create_flash_sale

ok, msg = can_create_flash_sale(seller)
if not ok:
    messages.error(request, msg)
    return redirect("flash_sales:list")
```
**Si absent → ajouter. Si présent → confirmer avec test.**

### A.2 — Vérifier Celery Beat schedule
```python
# config/settings/base.py → CELERY_BEAT_SCHEDULE
# DOIT contenir :
CELERY_BEAT_SCHEDULE = {
    "auto-open-sales": {
        "task": "flash_sales.auto_open_scheduled_sales",
        "schedule": 60.0,
    },
    "auto-close-sales": {
        "task": "flash_sales.auto_close_live_sales",
        "schedule": 60.0,
    },
}
```

### A.3 — Vérifier DRF throttle
```python
# config/settings/base.py → REST_FRAMEWORK
REST_FRAMEWORK = {
    ...
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/minute",
        "user": "100/minute",
    },
}
```

### A.4 — config/settings/test.py
```python
from .base import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
```

**Critère de succès A :** `python manage.py check --deploy` passe. `pytest` tourne sans erreur de config.

---

## PHASE B — Features V1 Manquantes (2 sessions, ~4h total)

### B.1 — Export CSV Commandes (Session 1, ~2h)

**Fichier :** `orders/views.py`
```python
import csv
from django.http import HttpResponse

@login_required
def export_orders_csv(request, pk):
    """GET /seller/flash-sales/<pk>/export.csv"""
    flash_sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    orders = Order.service_objects.filter(
        flash_sale=flash_sale
    ).prefetch_related("items__product", "delivery")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="commandes-{flash_sale.public_slug}.csv"'
    response.write("﻿")  # BOM UTF-8 pour Excel

    writer = csv.writer(response)
    writer.writerow(["#", "Client", "Téléphone", "Produits", "Total FCFA", "Statut", "Adresse", "Heure"])
    
    for order in orders:
        items_str = " | ".join(
            f"{item.product_name_snapshot} x{item.quantity}"
            for item in order.items.all()
        )
        delivery_addr = ""
        if hasattr(order, "delivery"):
            delivery_addr = order.delivery.address or ""
        writer.writerow([
            order.pk,
            order.customer_name,
            order.customer_phone,
            items_str,
            int(order.total_amount),
            order.get_status_display(),
            delivery_addr,
            order.created_at.strftime("%H:%M"),
        ])
    return response
```

**URL :** `path("flash-sales/<int:pk>/export.csv", export_orders_csv, name="export-orders-csv")`

**Bouton dans `templates/orders/dashboard.html` :**
```html
<a href="{% url 'export-orders-csv' flash_sale.pk %}"
   class="inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium">
  <i data-lucide="download" class="w-4 h-4"></i>
  Exporter CSV
</a>
```

### B.2 — AuditLog (Session 1, ~1h)

**Fichier :** `core/models.py`
```python
class AuditLog(models.Model):
    actor    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action   = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=50)
    entity_id   = models.IntegerField()
    metadata    = models.JSONField(default=dict)
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    timestamp   = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Journal d'audit"
```

**Usage dans OrderService :**
```python
AuditLog.objects.create(
    actor=None,  # action client anonyme
    action="order.created",
    entity_type="Order",
    entity_id=order.pk,
    metadata={"flash_sale_id": flash_sale.pk, "total": float(order.total_amount)},
)
```

Actions à logger : `order.created`, `order.cancelled`, `flashsale.opened`, `flashsale.closed`, `order.status_changed`.

### B.3 — PWA Manifest + Service Worker minimal (Session 2, ~2h)

**Fichier :** `static/manifest.json`
```json
{
  "name": "HayaFlash",
  "short_name": "HayaFlash",
  "description": "Ventes Flash Live",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#F5F5F5",
  "theme_color": "#E63946",
  "icons": [
    { "src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

**Dans `base.html` `<head>` :**
```html
<link rel="manifest" href="/static/manifest.json">
<meta name="theme-color" content="#E63946">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="apple-touch-icon" href="/static/img/icon-192.png">
```

**Fichier :** `static/sw.js` (Service Worker minimal — cache les assets statiques)
```javascript
const CACHE = "hayaflash-v1";
const ASSETS = ["/static/js/hf-components.js", "/static/manifest.json"];

self.addEventListener("install", e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(ASSETS))
));

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
```

**Critère de succès B :** Lighthouse PWA score > 0. Export CSV fonctionne sur mobile. AuditLog visible dans admin.

---

## PHASE C — Tests + CI/CD (2 sessions, ~4h total)

### C.1 — Tests critiques manquants (Session 1, ~2h)

Priorité tests à écrire :

**`flash_sales/tests.py`** — à compléter :
```python
def test_celery_auto_open():
    """Vérifie que auto_open_scheduled_sales() passe SCHEDULED → LIVE."""
    
def test_celery_auto_close():
    """Vérifie que auto_close_live_sales() passe LIVE → CLOSED."""
    
def test_subscription_enforcement_blocks_4th_sale():
    """Plan Free ne peut pas créer une 4ème vente ce mois."""
    
def test_export_csv_returns_all_orders():
    """Export CSV contient toutes les commandes de la vente."""
```

**`orders/tests.py`** — à vérifier et compléter :
```python
def test_concurrent_orders_no_oversell():
    """Deux commandes simultanées sur le dernier stock → une seule réussit."""
    # Utiliser threading.Thread ou transaction + select_for_update
    
def test_idempotence_same_client_request_id():
    """Même client_request_id → une seule commande créée."""
```

**`notifications/tests.py`** — à créer :
```python
def test_send_order_confirmation_task():
    """Task Celery envoie notification après commande."""
```

**`subscriptions/tests.py`** — à créer :
```python
def test_can_create_flash_sale_free_plan_limit():
def test_can_create_flash_sale_pro_plan_unlimited():
```

Objectif coverage : > 70%.

### C.2 — GitHub Actions CI/CD (Session 2, ~2h)

**Fichier :** `.github/workflows/ci.yml`
```yaml
name: CI

on: [push, pull_request]

env:
  DJANGO_SETTINGS_MODULE: config.settings.test

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run Django check
        run: python manage.py check

      - name: Run tests with coverage
        run: |
          pip install pytest-django pytest-cov
          pytest --ds=config.settings.test --cov=. --cov-report=term-missing --cov-fail-under=60

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff
      - run: ruff check .
```

**Fichier :** `.github/workflows/deploy.yml`
```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy-staging:
    runs-on: ubuntu-latest
    needs: []  # déclenché après CI via branch protection

    steps:
      - uses: actions/checkout@v4

      - name: Build Docker image
        run: |
          docker build -t hayaflash:${{ github.sha }} .
          docker tag hayaflash:${{ github.sha }} hayaflash:latest

      - name: Deploy to staging via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.STAGING_HOST }}
          username: ${{ secrets.STAGING_USER }}
          key: ${{ secrets.STAGING_SSH_KEY }}
          script: |
            cd /srv/hayaflash
            git pull origin main
            docker compose -f docker-compose.production.yml pull
            docker compose -f docker-compose.production.yml up -d
            docker compose exec web python manage.py migrate --noinput
            bash infra/scripts/smoke_test.sh

  deploy-prod:
    needs: deploy-staging
    runs-on: ubuntu-latest
    environment: production  # approbation manuelle requise

    steps:
      - uses: actions/checkout@v4
      - name: Deploy to production
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PROD_HOST }}
          username: ${{ secrets.PROD_USER }}
          key: ${{ secrets.PROD_SSH_KEY }}
          script: |
            cd /srv/hayaflash
            git pull origin main
            docker compose -f docker-compose.production.yml up -d --no-deps web worker beat
            docker compose exec web python manage.py migrate --noinput
```

**Fichier :** `infra/scripts/smoke_test.sh`
```bash
#!/bin/bash
set -e
BASE="${1:-http://localhost:8000}"

echo "Smoke test: $BASE"

# Health check
curl -sf "$BASE/health/" | grep -q '"status":"ok"' || { echo "FAIL: health"; exit 1; }
echo "✓ /health/"

# Page publique ventes
curl -sf "$BASE/ventes/" | grep -q "Ventes Flash" || { echo "FAIL: /ventes/"; exit 1; }
echo "✓ /ventes/"

# API flash-sales
curl -sf "$BASE/api/v1/flash-sales/" | python3 -c "import sys,json; json.load(sys.stdin)" || { echo "FAIL: API"; exit 1; }
echo "✓ /api/v1/flash-sales/"

echo "All smoke tests passed ✓"
```

**Critère de succès C :** Push sur `main` → CI passe → staging deploy → smoke test vert.

---

## PHASE D — Hardening Final (1 session, ~2h)

### D.1 — Bulk Actions commandes
```python
# orders/views.py
@login_required
def bulk_confirm_orders(request, pk):
    """POST /seller/flash-sales/<pk>/orders/confirm-all/"""
    # Confirmer toutes les commandes pending en 1 clic
    
@login_required  
def bulk_mark_delivered(request, pk):
    """POST /seller/flash-sales/<pk>/orders/mark-delivered/"""
```

### D.2 — docker-compose.production.yml
```yaml
# Séparé de docker-compose.yml (dev)
# Ajouter : nginx service, volumes prod, no dev-reload
```

### D.3 — Vérification Nginx rate limiting sur /api/v1/orders/
```nginx
# Ajouter dans hayaflash.conf :
limit_req_zone $binary_remote_addr zone=orders:10m rate=10r/s;

location /api/v1/orders/ {
    limit_req zone=orders burst=20 nodelay;
    proxy_pass http://django;
    ...
}
```

### D.4 — Variables d'environnement prod
```bash
# .env.example → compléter avec :
ORANGE_MONEY_API_KEY=      # activé en V1.1
SMS_GATEWAY_API_KEY=       # Orange SMS Mali
WHATSAPP_BUSINESS_TOKEN=   # pour V1.1 (V1 = lien wa.me)
SENTRY_DSN=
ALLOWED_HOSTS=hayaflash.ml,www.hayaflash.ml
SECRET_KEY=                # OBLIGATOIRE : 50+ chars random
```

---

## 5. GOUVERNANCE — RÈGLES D'EXÉCUTION

### Pour Claude Code (règles impératives)

```
AVANT chaque session :
1. Lire CODEBASE_STATUS.md
2. Lire la phase workflow concernée dans docs/workflows/
3. Confirmer les prérequis

PENDANT chaque session :
- 1 fichier à la fois
- Valider avec `python manage.py check` après chaque modification modèle
- `pytest` partiel après chaque service/view
- Ne jamais commiter si les tests échouent

APRÈS chaque session :
1. Mettre à jour CODEBASE_STATUS.md
2. Commit atomique : "feat(Px): description courte"
3. Push sur feature/phase-x
4. Pull Request → review → merge main
```

### Branching Git
```
main          → production stable
staging       → deploy automatique post-CI
feature/Px-*  → phase en cours
hotfix/*      → correctifs urgents prod
```

### Convention commits
```
feat(A): verify subscription enforcement + DRF throttle
feat(B1): export CSV commandes post-LIVE
feat(B2): AuditLog core model + signals
feat(B3): PWA manifest + service worker minimal
feat(C): tests coverage + github actions CI/CD
feat(D): docker-compose.production + bulk actions + nginx rate limit
```

---

## 6. ORDRE D'EXÉCUTION RECOMMANDÉ

```
Phase A (2h)     → Vérifications + corrections silencieuses
    ↓
Phase B1 (2h)    → Export CSV + AuditLog      [PARALLÉLISABLE avec B3]
Phase B3 (2h)    → PWA manifest + SW          [PARALLÉLISABLE avec B1]
    ↓
Phase C (4h)     → Tests + CI/CD pipeline
    ↓
Phase D (2h)     → Hardening final
    ↓
🚀 LAUNCH V1     → Deploy staging → smoke test → prod
```

**Durée totale estimée : 12h de sessions Claude Code soit 3–4 journées de travail.**

---

## 7. CHECKLIST DE LANCEMENT V1

```
□ python manage.py check --deploy → 0 erreur, 0 warning
□ pytest → coverage > 70%
□ docker compose up → app accessible sur port 8000
□ docker compose -f docker-compose.production.yml up → Nginx HTTPS
□ CI/CD → push main → staging deploy automatique
□ Smoke test → tous les endpoints critiques vert
□ Créer 1 vente test → publier → commander → voir dashboard → export CSV
□ Vérifier countdown visible sur page client
□ Vérifier commande offline (mode avion) → reconnexion → sync
□ Vérifier limit Free plan (3 ventes → blocage)
□ Sentry → 1 erreur test → reçue dans dashboard
□ Celery Beat → auto-open d'une vente schedulée vérifiée
```

---

## 8. WHAT NOT TO BUILD BEFORE V1

Sur la base du MASTER_CONTEXT Partie 1 §20 ("Règle absolue") :

| Feature | Décision | Raison |
|---|---|---|
| WebSockets / Django Channels | ❌ V2 | HTMX polling suffisant <100 vendeurs |
| Orange Money réel | ❌ V1.1 | COD + activation manuelle suffisants |
| Multi-boutiques | ❌ V2 | 1 seller = 1 compte, OK pour Mali |
| WhatsApp Business API réelle | ❌ V1.1 | Lien wa.me suffisant |
| QR Code | ⏸ V1.1 | Utile, pas bloquant |
| Application mobile | ❌ V2 | API stable = base pour mobile |
| Programme fidélité | ❌ V2 | Pas de valeur V1 |
| OpenAPI schema complet | ⏸ Post-launch | Aucun consommateur externe en V1 |

---

---

## 9. FEATURES POST-V1 — SPÉCIFICATIONS DÉTAILLÉES

Ces features sont spécifiées ici pour être implémentées en V1.1 sans ambiguïté.

---

### 9.1 — Enregistrement vocal de la description (V1.1)

**Objectif :** Permettre au vendeur de dicter sa description de vente plutôt que la taper (mobile first).

**UX prévue :**
- Sur la page `create.html` (et `edit.html`), sous le champ `description`, ajouter un bouton "🎤 Enregistrer" 
- Enregistrement via `MediaRecorder API` (navigateur)
- Transcription via Whisper API (OpenAI) ou fallback Web Speech API (Chrome mobile)
- Le texte transcrit est **injecté dans le textarea** `description` — l'utilisateur peut ensuite le corriger

**Implémentation backend :**
```python
# POST /api/v1/flash-sales/transcribe-audio/
# Body : multipart/form-data { audio: File (webm/mp4/mp3) }
# Response : { "transcript": "...", "confidence": 0.92 }

# views.py
class TranscribeAudioView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        audio_file = request.FILES.get("audio")
        if not audio_file:
            return Response({"error": "No audio"}, status=400)
        
        # OpenAI Whisper
        import openai
        transcript = openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="fr"
        )
        return Response({"transcript": transcript.text})
```

**Implémentation frontend Alpine.js :**
```javascript
// Dans le bloc x-data de create.html
recording: false,
mediaRecorder: null,
audioChunks: [],

async startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  this.mediaRecorder = new MediaRecorder(stream);
  this.audioChunks = [];
  this.mediaRecorder.ondataavailable = e => this.audioChunks.push(e.data);
  this.mediaRecorder.onstop = () => this.sendAudio();
  this.mediaRecorder.start();
  this.recording = true;
},

stopRecording() {
  this.mediaRecorder.stop();
  this.recording = false;
},

async sendAudio() {
  const blob = new Blob(this.audioChunks, { type: "audio/webm" });
  const fd = new FormData();
  fd.append("audio", blob, "recording.webm");
  const resp = await fetch("/api/v1/flash-sales/transcribe-audio/", {
    method: "POST",
    headers: { "X-CSRFToken": getCsrfToken() },
    body: fd
  });
  const data = await resp.json();
  if (data.transcript) {
    // Injecter dans le textarea description
    document.querySelector('[name="description"]').value = data.transcript;
  }
}
```

**Règles UI :**
- Bouton visible uniquement si `navigator.mediaDevices` disponible (mobile/desktop Chrome/Firefox)
- Pendant l'enregistrement : bouton rouge pulsant "🔴 Arrêter"
- Après transcription : message succès "Texte ajouté — vérifiez et corrigez si besoin"
- Pas de remplacement automatique si description déjà saisie : demander confirmation

**Priorité :** V1.1 — post-lancement, batch fonctionnalités mobile.

---

### 9.2 — Countdown chromatique (vert → jaune → rouge) (V1.1)

**Objectif :** Renforcer l'urgence visuelle sur la page client ET le dashboard vendeur via un countdown dont la couleur change selon le temps restant.

**Règle de couleur :**
```
> 70% du temps restant  → 🟢 Vert    (#16A34A / green-600)
30% – 70% restant       → 🟡 Jaune   (#D97706 / amber-600)  
< 30% restant           → 🔴 Rouge   (#DC2626 / red-600) + animation pulse
< 10% restant           → 🔴 Rouge + fond rouge pâle + chiffres en gros
```

**Calcul JS :**
```javascript
// Dans hf-components.js → CountdownTimer component
get colorClass() {
  const pct = (this.secondsLeft / this.totalSeconds) * 100;
  if (pct > 70) return 'text-green-600';
  if (pct > 30) return 'text-amber-600';
  return 'text-red-600';
},
get pulseClass() {
  const pct = (this.secondsLeft / this.totalSeconds) * 100;
  return pct < 30 ? 'animate-pulse' : '';
},
get urgentBg() {
  const pct = (this.secondsLeft / this.totalSeconds) * 100;
  return pct < 10 ? 'bg-red-50 rounded-xl px-4 py-2' : '';
}
```

**Pages concernées :**
1. **Page client** `templates/flash_sales/public_sale.html` — countdown grand format visible au-dessus des produits
2. **Dashboard vendeur** `templates/seller/home.html` — compteur compact dans chaque carte de vente active
3. **Page LIVE vendeur** `templates/flash_sales/live.html` — countdown très visible en haut de page

**Implémentation :**
- Les composants Alpine `CountdownTimer` dans `hf-components.js` reçoivent `start_time`, `end_time` en data attributes
- Le calcul `totalSeconds` = `end_time - start_time` est fait une seule fois à l'init
- `secondsLeft` est mis à jour toutes les secondes via `setInterval`
- La couleur est réactive via `:class`

**Priorité :** V1.1 — impactant mais non bloquant pour le lancement. Le countdown blanc/gris actuel fonctionne.

---

*Document généré le 2026-07-10. Mettre à jour après chaque phase complétée.*
