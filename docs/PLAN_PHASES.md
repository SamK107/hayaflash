# HayaFlash — Plan d'Implémentation V1
> Généré le 2026-07-04 par Cowork. Mis à jour le 2026-07-13 (audit code source).
> Se réfère à : `CODEBASE_STATUS.md` (état réel), `PROJECT_SPEC.md` (intention produit).
> Chaque phase a son workflow exécutable dans `docs/workflows/`.

---

## Architecture Cible

```
Stack finale V1 :
Django 5.2 · HTMX 2.0 · Alpine.js 3 · Tailwind CSS 3 CDN
PostgreSQL (prod) · SQLite (dev) · Redis (cache + Celery)
Celery + Celery Beat · Gunicorn · Nginx · Docker

Design System :
Primary   #E63946  (rouge action)
Gold      #FFB800  (accent)
Dark      #111111
Success   #22C55E
BG        #F5F5F5
```

---

## Vue d'ensemble des 6 Phases

| Phase | Nom | État (juillet 2026) |
|---|---|---|
| P0 | Foundation & Qualité | ✅ Terminé |
| P1 | Modèles Complets + Migrations | ✅ Terminé |
| P2 | Interface Vendeur (CRUD) | ✅ Terminé |
| P3 | LIVE Workflow Complet | ✅ Terminé |
| P4 | Design Moderne (Tailwind) | ✅ Terminé |
| P5 | Notifications + Subscriptions | ✅ Terminé |
| P6 | CI/CD + Production Hardening | ✅ Terminé |

> Toutes les phases sont complètes. Les prochaines priorités sont dans `docs/CODEBASE_STATUS.md` (section "Ce qui n'existe PAS").

---

## Phase 0 — Foundation & Qualité
> Workflow : `docs/workflows/WORKFLOW_P0_FOUNDATION.md`

**Objectif** : Corriger les dettes techniques, aligner sur DJANGO_REFERENCE, installer les fondations manquantes (Tailwind, Celery, Argon2, settings corrects).

### Tâches

**0.1 — Settings**
- Corriger `LANGUAGE_CODE = "fr-fr"` et `TIME_ZONE = "Africa/Bamako"`
- Ajouter `Argon2PasswordHasher` + `django[argon2]` dans requirements
- Enrichir `LOGGING` (formatter verbose, loggers par app)
- Créer `config/settings/test.py` (DB SQLite in-memory, no Redis, emails console)
- Ajouter `django-debug-toolbar` dans `settings/dev.py`
- Ajouter `Sentry` dans `settings/prod.py`
- Ajouter headers sécurité manquants (HSTS, CSP) dans prod

**0.2 — Celery**
- Ajouter `celery`, `redis` dans `requirements.txt`
- Créer `config/celery.py` (app Celery + auto-discovery)
- Modifier `config/__init__.py` pour importer l'app Celery

**0.3 — Base Template (Tailwind + Alpine)**
- Refaire `templates/base.html` : Tailwind CDN + Alpine.js + meta complet + design system
- Créer `templates/partials/_messages.html` (toasts/alerts)
- Créer `templates/partials/_nav_seller.html` (nav vendeur authentifié)

**0.4 — Infrastructure locale**
- Créer `Dockerfile` (Python 3.11 slim, optimisé)
- Créer `docker-compose.yml` (web + db postgres + redis + celery worker + beat)
- Créer `.env.example` enrichi avec toutes les variables

**Critères de succès P0** :
- `python manage.py runserver` fonctionne sans erreur
- `python manage.py check --deploy` passe en staging
- `docker-compose up` démarre la stack locale
- Tailwind visible dans le browser sur `base.html`

---

## Phase 1 — Modèles Complets + Migrations
> Workflow : `docs/workflows/WORKFLOW_P1_MODELES.md`

**Objectif** : Aligner tous les modèles avec PROJECT_SPEC v2. Zéro champ manquant sur les entités critiques.

### Tâches

**1.1 — FlashSale : statuts étendus**
```python
class FlashSaleStatus(models.TextChoices):
    SCHEDULED  = "scheduled",  "Programmée"
    LIVE       = "live",       "En cours"
    CLOSED     = "closed",     "Fermée"
    EXECUTING  = "executing",  "Exécution"
    COMPLETED  = "completed",  "Terminée"
    CANCELLED  = "cancelled",  "Annulée"
```
- Migration : renommer `draft → scheduled`, ajouter nouveaux statuts
- Mettre à jour `open_sale()`, `close_sale()`, ajouter `complete_sale()`, `cancel_sale()`
- Mettre à jour `services/ordering.py` : checker `status == LIVE` ET fenêtre temps

**1.2 — FlashSale : champs manquants**
```python
description   = models.TextField(blank=True)
cover_image   = models.ImageField(upload_to="flash_sales/covers/", null=True, blank=True)
delivery_zone = models.CharField(max_length=200, blank=True)
max_orders    = models.IntegerField(null=True, blank=True)
```

**1.3 — Product : champs manquants**
```python
description     = models.TextField(blank=True)
unit            = models.CharField(max_length=50, default="pièce")
characteristics = models.JSONField(default=dict, blank=True)
display_order   = models.IntegerField(default=0)
stock_initial   = models.IntegerField(default=0)  # renommer stock → stock_available
```
- Migration data : copier `stock → stock_initial` ET `stock → stock_available`

**1.4 — ProductMedia (nouveau modèle)**
```python
class ProductMedia(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Vidéo"
    product    = models.ForeignKey(Product, related_name="media", on_delete=models.CASCADE)
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.IMAGE)
    file       = models.ImageField(upload_to="products/media/", null=True, blank=True)
    video_url  = models.URLField(blank=True)
    order      = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["order"]
```

**1.5 — SellerProfile : champs manquants**
```python
bio            = models.TextField(blank=True)
avatar         = models.ImageField(upload_to="sellers/avatars/", null=True, blank=True)
delivery_zones = models.CharField(max_length=500, blank=True)
```

**1.6 — StockMovement (nouveau modèle)**
```python
class StockMovement(models.Model):
    class Type(models.TextChoices):
        RESERVATION = "reservation", "Réservation"
        RELEASE     = "release",     "Libération"
        CORRECTION  = "correction",  "Correction"
    product        = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="stock_movements")
    order          = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL)
    quantity_change= models.IntegerField()
    type           = models.CharField(max_length=20, choices=Type.choices)
    created_at     = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
```
- Intégrer la création de `StockMovement` dans `create_order()` (hors transaction critique)

**1.7 — Mise à jour admin.py**
- Tous les nouveaux modèles enregistrés dans admin avec list_display, list_filter, search_fields

**Critères de succès P1** :
- `python manage.py migrate` sans erreur
- `python manage.py check` sans warning
- Tous les modèles visibles dans l'admin Django

---

## Phase 2 — Interface Vendeur (CRUD)
> Workflow : `docs/workflows/WORKFLOW_P2_VENDOR_UI.md`

**Objectif** : Un vendeur peut créer une vente, ajouter des produits, et gérer ses ventes depuis une interface web moderne (Tailwind).

### Tâches

**2.1 — Flash Sales CRUD (vendeur)**

URLs :
```
/seller/flash-sales/           → liste des ventes
/seller/flash-sales/create/    → créer une vente
/seller/flash-sales/<id>/edit/ → modifier
/seller/flash-sales/<id>/      → détail + produits
/seller/flash-sales/<id>/open/ → ouvrir manuellement
/seller/flash-sales/<id>/close/→ fermer manuellement
```

Views (FBV, authentifiées) :
- `flash_sale_list_view()` — liste avec statuts, KPI mini, liens
- `flash_sale_create_view()` — formulaire création (titre, description, dates, zone livraison, cover_image)
- `flash_sale_edit_view()` — idem, pré-rempli
- `flash_sale_detail_view()` — détail + liste produits + actions
- `flash_sale_open_view()` — POST, change status → live
- `flash_sale_close_view()` — POST, change status → closed

Services :
- `flash_sales/services/crud.py` : `create_flash_sale()`, `update_flash_sale()`, validation métier

Templates (Tailwind, mobile-first) :
- `templates/flash_sales/list.html`
- `templates/flash_sales/create.html`
- `templates/flash_sales/detail.html`
- `templates/flash_sales/partials/_flash_sale_card.html`

**2.2 — Products CRUD (dans le contexte d'une vente)**

URLs :
```
/seller/flash-sales/<id>/products/create/  → ajouter produit
/seller/flash-sales/<id>/products/<pid>/   → modifier produit
/seller/flash-sales/<id>/products/<pid>/delete/ → supprimer
```

Views :
- `product_create_view()` — formulaire + upload image
- `product_edit_view()` — idem
- `product_delete_view()` — POST only, soft

Services :
- `products/services/crud.py` : `create_product()`, `update_product()`, `upload_media()`

Templates :
- `templates/products/product_form.html`
- `templates/products/partials/_product_card.html`

**2.3 — Dashboard vendeur amélioré**

- Page `/seller/` : accueil vendeur avec ses ventes actives, KPI globaux, bouton "Créer une vente"
- Navbar vendeur persistante (HTMX-compatible)
- Vue unifiée : ventes par statut (tabs : Programmées / En cours / Terminées)

**Critères de succès P2** :
- Vendeur peut créer une vente en < 60 secondes
- Vendeur peut ajouter un produit avec image et stock
- Dashboard vendeur accessible et fonctionnel
- Toutes les pages passent sur mobile (viewport 375px)

---

## Phase 3 — LIVE Workflow Complet
> Workflow : `docs/workflows/WORKFLOW_P3_LIVE.md`

**Objectif** : Le cycle de vie complet d'une vente est automatisé et le dashboard LIVE offre une expérience temps réel excellente.

### Tâches

**3.1 — Celery Tasks**

`flash_sales/tasks.py` :
```python
@shared_task
def auto_open_scheduled_sales():
    """Passe scheduled → live si start_time atteint."""
    ...

@shared_task
def auto_close_live_sales():
    """Passe live → closed si end_time atteint."""
    ...
```

`config/celery.py` beat schedule :
```python
CELERY_BEAT_SCHEDULE = {
    "auto-open-sales": {
        "task": "flash_sales.tasks.auto_open_scheduled_sales",
        "schedule": 60.0,  # toutes les 60 secondes
    },
    "auto-close-sales": {
        "task": "flash_sales.tasks.auto_close_live_sales",
        "schedule": 60.0,
    },
}
```

**3.2 — Dashboard LIVE amélioré**

Template `templates/orders/dashboard.html` refonte Tailwind :
- Badge "● LIVE" rouge pulsant (Alpine.js animation)
- Timer countdown (`HH:MM:SS`) mis à jour chaque seconde (Alpine.js)
- KPI cards : commandes / articles / revenu / stock critique
- Liste des dernières commandes (HTMX polling 3s) avec slide-in animation
- Actions rapides : Confirmer / En livraison / Livré / Annuler (1 clic, HTMX)
- Filtre statut par tabs (HTMX)
- Bouton "Fermer la vente" rouge + modal confirmation

**3.3 — Calendrier public des ventes**

URL : `/ventes/`

View : liste des ventes `scheduled` et `live` de tous les vendeurs (publique)
- Tri par date
- Countdown vers ouverture
- Card par vente : titre, vendeur, produits aperçu, statut
- SEO : OpenGraph, JSON-LD Event

Template `templates/flash_sales/public_calendar.html`

**3.4 — API flash sales publiques**

```
GET /api/v1/flash-sales/              → liste scheduled + live
GET /api/v1/flash-sales/<slug>/       → détail + produits
GET /api/v1/flash-sales/<slug>/kpi/   → KPI LIVE (polling)
```

Serializers : `FlashSalePublicSerializer`, `ProductPublicSerializer`

**3.5 — Page commande client améliorée (Tailwind)**

Refonte `templates/orders/client_order.html` :
- Design ultra-épuré, mobile-first
- Couleurs : fond blanc, CTA rouge `#E63946`
- Produit en hero (image, nom, prix, stock restant)
- Formulaire : 4 champs max, très aéré
- GPS : bouton "Détecter ma position" avec feedback visuel
- CTA "Commander" : gros, 56px height, full-width
- Toast confirmation animé

**Critères de succès P3** :
- Vente s'ouvre automatiquement à `start_time` (Celery)
- Vente se ferme automatiquement à `end_time`
- Dashboard LIVE affiche badge rouge pulsant + countdown
- Commande apparaît dans le dashboard en < 5 secondes
- `/ventes/` liste les ventes programmées

---

## Phase 4 — Design Moderne Complet (Tailwind)
> Workflow : `docs/workflows/WORKFLOW_P4_DESIGN.md`

**Objectif** : Toutes les pages sont au niveau d'une app moderne, cohérente, mobile-first. Expérience utilisateur excellente sur Android entrée de gamme.

### Design System à appliquer

```css
/* Tokens */
--color-primary:  #E63946;  /* rouge action */
--color-gold:     #FFB800;  /* accent */
--color-dark:     #111111;
--color-success:  #22C55E;
--color-warning:  #F59E0B;
--color-danger:   #EF4444;
--color-bg:       #F5F5F5;
--color-surface:  #FFFFFF;
--color-text:     #1A1A1A;
--color-muted:    #6B7280;
--radius:         0.75rem;
--shadow-sm:      0 1px 3px rgba(0,0,0,0.08);
--shadow-md:      0 4px 12px rgba(0,0,0,0.12);
```

### Pages à refondre (par priorité)

1. `base.html` — layout général, nav, footer branding
2. `orders/client_order.html` — page commande (UX critique)
3. `orders/dashboard.html` — dashboard LIVE vendeur
4. `accounts/login.html` + `register.html`
5. `flash_sales/list.html` + `create.html` + `detail.html`
6. `delivery/deliveries_dashboard.html`
7. `analytics/flash_sale_public.html` + `seller_public.html`
8. `flash_sales/public_calendar.html` (nouveau)

### Composants Alpine.js à créer

- **Timer countdown** : `x-data="countdown(endTime)"` → affiche `HH:MM:SS`
- **Toast notifications** : `x-data="toasts()"` → queue de messages
- **Modal confirmation** : `x-data="modal()"` → actions critiques (fermer vente, annuler commande)
- **Offline banner** : `x-data="onlineStatus()"` → badge "Hors ligne" si déconnecté
- **GPS loader** : animation pendant capture position

**Critères de succès P4** :
- Lighthouse Mobile Score > 85
- Toutes les pages render proprement sur 375px
- Aucun CSS inline restant sur les pages critiques
- Touch targets > 48px partout
- Timer visible et fonctionnel sur dashboard LIVE

---

## Phase 5 — Notifications + Subscriptions
> Workflow : `docs/workflows/WORKFLOW_P5_NOTIFS_SUBS.md`

**Objectif** : Les vendeurs reçoivent des notifications WhatsApp/SMS. Le système d'abonnement est enforced.

### 5.1 — Notifications

`notifications/models.py` :
```python
class Notification(models.Model):
    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp"
        SMS      = "sms"
        EMAIL    = "email"
    class Status(models.TextChoices):
        PENDING = "pending"
        SENT    = "sent"
        FAILED  = "failed"
    recipient_phone = models.CharField(max_length=20)
    channel         = models.CharField(max_length=20, choices=Channel.choices)
    message         = models.TextField()
    status          = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    sent_at         = models.DateTimeField(null=True)
    created_at      = models.DateTimeField(auto_now_add=True)
```

`notifications/services/` :
- `whatsapp.py` : envoi via WhatsApp Business API (ou lien `wa.me` en fallback)
- `sms.py` : intégration SMS gateway (Orange SMS API Mali)
- `dispatcher.py` : routeur par canal

Celery tasks :
- `send_order_confirmation_sms` — déclenché à la création de commande
- `send_sale_reminder` — 1h avant le début d'une vente (aux clients "Me rappeler")

### 5.2 — Subscriptions

`subscriptions/models.py` :
```python
class Plan(models.TextChoices):
    FREE = "free", "Gratuit"
    PRO  = "pro",  "Pro"

class Subscription(models.Model):
    seller      = models.OneToOneField("accounts.SellerProfile", on_delete=models.CASCADE)
    plan        = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    expires_at  = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
```

`subscriptions/services/` :
- `limits.py` : `can_create_flash_sale(seller)` → vérifie quota
- `enforcement.py` : middleware ou décorateur sur les views de création

Limites Plan Free : 3 ventes/mois
Limites Plan Pro : illimité

**Critères de succès P5** :
- SMS/WhatsApp envoyé à la confirmation d'une commande
- Vendeur Free bloqué à 3 ventes/mois avec message d'upgrade
- Page de gestion abonnement accessible dans le dashboard

---

## Phase 6 — CI/CD + Production Hardening
> Workflow : `docs/workflows/WORKFLOW_P6_CICD.md`

**Objectif** : Le projet est deployable de manière reproductible, avec tests automatiques et pipeline CI/CD.

### 6.1 — Docker

`Dockerfile` (optimisé multi-stage) :
```dockerfile
FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS production
COPY . .
RUN python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60"]
```

`docker-compose.yml` (dev) : web + db + redis + celery_worker + celery_beat
`docker-compose.production.yml` : idem + nginx

### 6.2 — Nginx

`infra/nginx/hayaflash.conf` :
- Reverse proxy vers Gunicorn
- Compression gzip
- Static files servis directement
- WebSocket ready (`/ws/`)
- Rate limiting sur `/api/v1/orders/`
- HTTPS (Let's Encrypt)

`infra/nginx/rate-limit-zones.conf`

### 6.3 — CI/CD GitHub Actions

`.github/workflows/ci.yml` :
```yaml
on: [push, pull_request]
jobs:
  test:
    steps:
      - checkout
      - setup Python
      - pip install -r requirements.txt
      - python manage.py check
      - pytest --ds=config.settings.test
```

`.github/workflows/deploy.yml` :
```yaml
on:
  push:
    branches: [main]
jobs:
  deploy-staging:
    steps:
      - build Docker image
      - push to registry
      - SSH deploy to staging
      - smoke test
  deploy-prod:
    needs: deploy-staging
    environment: production
    steps:
      - deploy to prod (after manual approval)
```

### 6.4 — Tests

- `config/settings/test.py` : SQLite in-memory, pas de Redis, emails console
- Tests manquants à compléter : flash_sales, products, subscriptions, notifications
- Script `infra/scripts/smoke_test.sh` : teste les endpoints critiques post-deploy

**Critères de succès P6** :
- `docker-compose up` → app accessible en local
- `pytest` passe avec coverage > 70%
- Push sur `main` → deploy staging automatique
- Deploy prod déclenché manuellement avec approbation

---

## Ordre d'Exécution Recommandé

```
P0 (1 sem) → P1 (1 sem) → P2 (2 sem) → P3 (2 sem) → P4 (2 sem) → P5 (1 sem) → P6 (1 sem)
                                                                                  Total : ~10 semaines
```

P0 et P1 sont des prérequis stricts pour les suivantes.  
P4 peut démarrer en parallèle de P3 (design des templates pendant que les vues sont implémentées).  
P5 et P6 peuvent être parallélisées.

---

## Convention de Nommage des Workflows

Chaque fichier workflow dans `docs/workflows/` suit ce format :
```
WORKFLOW_Px_NOM.md
```
Il contient :
- **Objectif** de la phase
- **Prérequis** (phases précédentes, env vars)
- **Étapes** numérotées avec fichiers exacts à créer/modifier
- **Tests de validation** par étape
- **Checklist finale**

Ces fichiers sont conçus pour être exécutés par Cowork (Claude) étape par étape.
