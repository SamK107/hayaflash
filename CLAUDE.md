# CLAUDE.md — HayaFlash

> Source de vérité technique pour Claude (Cowork / Claude Code).
> Mis à jour le 2026-09-13. Basé sur audit direct du code source.
> **Ne pas modifier sans avoir d'abord lu le code réel.**
>
> Note : la version précédente (13/07) n'avait jamais été mise à jour depuis le
> tout premier commit du projet — elle décrivait l'état d'avant la Phase 7
> (pas de QR code, pas d'admin plateforme, etc.) alors que tout ça existe et
> fonctionne depuis. Cette révision aligne le fichier sur le code réel.

---

## Projet

Application Django de ventes flash mobiles (Mali). Les vendeurs créent des ventes limitées dans le temps ; les clients commandent depuis une page publique partageable via WhatsApp.

---

## Stack

```
Backend  : Django 5.2 · DRF 3.16 · Celery · Redis
Frontend : HTMX 2.0.0 · Alpine.js 3.14.9 · Tailwind CSS (build statique, vendorisé)
DB dev   : SQLite
DB prod  : PostgreSQL
Infra    : Docker · Gunicorn · Nginx · GitHub Actions CI/CD
```

> **14/09** : plus aucune dépendance front chargée depuis un CDN externe
> (unpkg / jsdelivr / cdn.tailwindcss.com / fonts.googleapis.com) — tout est
> vendorisé dans `static/vendor/` et `static/fonts/`, servi par WhiteNoise.
> Voir point 12.

---

## Structure des apps

```
accounts/       → User (phone E.164) + SellerProfile (seller_code, public_slug, bio, avatar)
analytics/      → ShareLink/ShareEvent (tracking WhatsApp), QR code (services/qrcode.py),
                  reporting MEDIUM/PRO (services/reporting.py), pages publiques SEO
config/         → Settings multi-env, Celery, URLs, API router
core/           → Home page, slugs centralisés, AuditLog, dashboard staff /platform-admin/
delivery/       → Modèle Delivery (GPS, COD, audio_note), dashboard HTMX livraisons
flash_sales/    → FlashSale + SaleInterest, CRUD vendeur, tâches Celery auto open/close +
                  rappel automatique aux inscrits (send_pending_sale_reminders)
notifications/  → Modèle Notification, services WhatsApp/SMS, tâches Celery
orders/         → Order + OrderItem, create_order() idempotent, dashboard LIVE HTMX
payments/       → PaymentTransaction + LedgerEntry (COD V1, mock provider)
products/       → Product + ProductMedia + ProductVariant + StockMovement
subscriptions/  → Plan FREE/MEDIUM/PRO, Subscription, SubscriptionPayment (Orange Money),
                  admin Django (simulation de plan sans paiement réel)
```

---

## Commandes essentielles

```bash
# Dev
python manage.py runserver --settings=config.settings.dev
python manage.py migrate
python manage.py createsuperuser

# Celery (deux terminaux séparés)
celery -A config worker -l info
celery -A config beat -l info

# Tests
pytest --ds=config.settings.test
python manage.py check

# Docker (dev local)
docker-compose up
```

---

## URLs principales

| URL | Description |
|-----|-------------|
| `/admin/` | Django admin standard |
| `/platform-admin/` | Dashboard pilotage plateforme (staff only) — MRR, vendeurs, abonnements |
| `/seller/` | Dashboard vendeur (authentifié) |
| `/seller/flash-sales/` | CRUD ventes flash |
| `/seller/flash-sales/analytics/` | Reporting MEDIUM (30j) / PRO (annuel + top produits) |
| `/seller/flash-sales/<pk>/interests/` | Réservations d'intérêt par vente |
| `/orders/dashboard/` | Dashboard LIVE commandes |
| `/orders/seller/deliveries/` | Dashboard livraisons HTMX |
| `/f/<slug>/` | Page publique vente flash (SEO + commande) |
| `/f/<slug>/qrcode/` | QR code de la vente (JSON, auth vendeur) |
| `/s/<slug>/` | Page publique vendeur |
| `/ventes/` | Calendrier public des ventes |
| `/billing/` | Abonnements vendeur |
| `/health/` | Healthcheck (alias racine, anonyme — voir point 8) |
| `/api/v1/` | API REST (DRF) |

---

## Conventions

- **FBV partout** (pas de CBV). Services dans `app/services/`.
- **Pas de `Model.objects.create()`** pour `Order` — utiliser uniquement `orders.services.create_order.create_order()`.
- **Migrations data séparées** des migrations schema.
- **HTMX** pour les mises à jour partielles (dashboard LIVE, livraisons).
- **Alpine.js** pour l'état local UI (countdown, GPS, vocal, modals).
- Design system : primary `#E63946`, gold `#FFB800`, success `#22C55E`, bg `#F5F5F5`.

---

## Points clés à connaître

1. **Vocal client** = deux mécanismes coexistent : `SpeechRecognition` navigateur → transcription texte dans `Delivery.address_text`, **et** un enregistrement audio réel (`audio_base64` envoyé par le client, décodé et stocké dans `Delivery.audio_note` via `_attach_audio_note()`, best-effort — un échec de décodage ne bloque jamais la commande).
2. **Audio vendeur** = `FlashSale.description_audio` et `Product.description_audio` (FileField WebM/OGG), enregistré par le vendeur, lu par les clients.
3. **Partage** = WhatsApp (`wa.me` + `api.whatsapp.com`) + QR code (`analytics/services/qrcode.py`, vue `flash_sale_qr_view`, `/f/<slug>/qrcode/`) + Web Share API (`navigator.share()`, bouton complémentaire visible si `'share' in navigator`, sur `flash_sale_public.html` et `seller_public.html`). Le bouton WhatsApp reste le seul trackable via `ShareEvent`.
4. **Admin plateforme** = `django.contrib.admin` **+ vue custom** `/platform-admin/` (`core/views.py:platform_admin_dashboard`, `@staff_member_required`) : vendeurs actifs, ventes live, MRR, revenu YTD, résumé remittance Orange, derniers paiements.
5. **`SubscriptionPayment`** **est enregistré** dans l'admin Django (`SubscriptionPaymentAdmin` — filtres status/plan/provider). `SubscriptionAdmin` expose aussi des actions de simulation de plan (Gratuit perpétuel / Medium 90j / Pro 90j) sans paiement réel — pratique pour la démo/support.
6. **Plans MEDIUM et FREE** ont la même limite de 3 ventes/mois (`PLAN_MONTHLY_SALES_LIMIT`). Seul PRO est illimité.
7. **Stats avancées MEDIUM/PRO** déclarées dans `PLAN_FEATURES`, différenciées dans l'UI via `/seller/flash-sales/analytics/` (gate sur `sub.has_stats`).
8. **Quota d'abonnement (`subscriptions/services/limits.py`)** est fail-closed : toute exception pendant la vérification bloque la création de vente plutôt que de l'autoriser silencieusement (loggé via `logger.exception`). Une vente `CANCELLED` libère son slot de quota. Un abonnement PRO/MEDIUM expiré retombe sur la limite FREE.
9. **Healthcheck** (`config/api_urls.py:health`) doit rester `@permission_classes([AllowAny])` et accessible à la fois sous `/health/` (racine, alias dans `config/urls.py`, ciblé par Dockerfile/compose/nginx) et `/api/v1/health/` — ne pas réintroduire `IsAuthenticated` dessus, ça casse tous les healthchecks infra silencieusement (403, pas d'erreur visible sans creuser).
   **Piège lié — `{% include ... only %}` et `{% csrf_token %}`** : le mot-clé `only` isole le sous-template inclus et lui retire `request` + tous les context processors, dont celui du CSRF. `{% csrf_token %}` ne lève alors aucune erreur — il rend juste une chaîne **vide** (aucun `<input>`), avec seulement un `UserWarning` en DEBUG ("context did not provide the value"). Bug réel trouvé dans `templates/delivery/partials/delivery_list.html` (14/09, PR #13) : le formulaire POST classique "En livraison" avait donc zéro champ `csrfmiddlewaretoken`, échouant en 403 "CSRF token missing" — alors que les boutons HTMX voisins fonctionnaient (header `X-CSRFToken` poussé globalement par `base.html`, lu depuis le cookie en JS, indépendant du HTML rendu). Ne jamais mettre `only` sur un `{% include %}` qui contient (ou peut contenir, via un sous-include) un `{% csrf_token %}`. `django.test.Client` **désactive la vérification CSRF par défaut** — utiliser `Client(enforce_csrf_checks=True)` pour détecter ce type de bug en test (voir `delivery/tests.py::SellerDeliveryActionFormCsrfTests`).
10. **CI/CD** : `.github/workflows/deploy.yml` = `test → build → deploy-staging → deploy-prod` chaînés (même fichier, `needs:` — pas de dépendance inter-workflow fiable sur GitHub Actions). `deploy-staging`/`deploy-prod` ont `if: false` (**déploiement VPS mis en pause volontairement le 13/09** — retirer la ligne quand le VPS est prêt : `docker login ghcr.io`, secrets `STAGING_*`/`PROD_*`, `/srv/hayaflash/.env`). L'image est poussée sur GHCR taguée au SHA exact + tag mobile `staging-latest`. `infra/scripts/deploy.sh` gère le rollback automatique (tag précédent) si le smoke test échoue — ne défait pas les migrations DB (forward-only).
11. **F3 "Sales Drawer"** : incertitude de gouvernance non résolue — un composant drawer (`orderDrawer`, `templates/analytics/flash_sale_public.html`) existe, mais rien ne confirme que c'est ce que désignait ce label externe. Voir `docs/PROJECT_SPEC.md` § Incertitudes.
12. **Vendoring front (14/09)** : Tailwind/HTMX/Alpine/Lucide/polices Inter+Poppins ne sont plus chargés depuis un CDN — build/téléchargement figé dans `static/vendor/` et `static/fonts/`, référencés via `{% static %}` dans `base.html`/`home.html`. Pour reconstruire le CSS Tailwind après un changement de classes dans les templates : voir `docs/FRONTEND_VENDORING.md`. Une `Content-Security-Policy` est active en **Report-Only** (`CSP_REPORT_ONLY = True`, `config/settings/base.py`) — elle ne bloque rien tant que `'unsafe-inline'` reste nécessaire aux nombreux `onclick=`/`<script>` inline ; passage en mode bloquant = décision produit à part (voir docs/CODEBASE_STATUS.md).
13. **Images produits/couvertures** : redimensionnées automatiquement à l'upload (max 1600px, `core/services/image_optimize.py`, appelé depuis `FlashSale.save()` et `ProductMedia.save()`) — best-effort, ne bloque jamais l'upload en cas d'échec Pillow (même philosophie que `_attach_audio_note()`).
14. **`/ventes/<slug>/`** (`flash_sales.public_views.public_flash_sale_detail`) duplique **`/f/<slug>/`** (`analytics.views.flash_sale_public_page`, qui porte le SEO complet OG/JSON-LD). Un `<link rel="canonical">` a été ajouté sur `/ventes/<slug>/` pointant vers `/f/<slug>/` pour éviter le contenu dupliqué aux yeux des moteurs de recherche — mais avoir deux vues/templates pour la même ressource reste une dette à trancher (fusionner, ou assumer les deux avec un rôle clair pour chacune).

---

## Docs de référence

| Fichier | Rôle |
|---------|------|
| `docs/CODEBASE_STATUS.md` | État réel du code par module — **mettre à jour après chaque chantier** |
| `docs/PLAN_PHASES.md` | Phases P0→P6 avec statut d'avancement |
| `docs/PROJECT_SPEC.md` | Intention produit V1 |
| `docs/ARCHITECTURE.md` | Décisions d'architecture |
| `docs/API_CONTRACT.md` | Contrat API REST |
| `docs/workflows/WORKFLOW_Px_*.md` | Workflows exécutables par phase |
| `docs/AUDIT_PERFORMANCE_SEO.md` | Audit performance/SEO/CDN (13/09) + suivi des actions |
| `docs/FRONTEND_VENDORING.md` | Comment reconstruire `static/vendor/tailwind/tailwind-hayaflash.css` après un changement de classes Tailwind dans les templates |

---

## État des phases (septembre 2026)

| Phase | Nom | État |
|-------|-----|------|
| P0 | Foundation & Qualité | ✅ Terminé |
| P1 | Modèles Complets | ✅ Terminé |
| P2 | Interface Vendeur CRUD | ✅ Terminé |
| P3 | LIVE Workflow Complet | ✅ Terminé |
| P4 | Design Moderne Tailwind | ✅ Terminé |
| P5 | Notifications + Subscriptions | ✅ Terminé |
| P6 | CI/CD + Production Hardening | ✅ Terminé |
| P7 | Pro Features & Admin Plateforme | ✅ Terminé (QR code, audio_note, interests par vente, analytics MEDIUM/PRO, admin plateforme, `SubscriptionPayment` admin) |
| P8 | Performance & SEO Hardening | 🟡 En cours (14/09) — voir `docs/AUDIT_PERFORMANCE_SEO.md` et `docs/CODEBASE_STATUS.md` § Performance & SEO |

→ Détail et prochaines priorités : `docs/CODEBASE_STATUS.md`

---

## Orange Money Payment Integration (Phase 8.1 — 14/09/2026)

### Vue d'ensemble

HayaFlash intègre Orange Money (WebPay) pour permettre aux vendeurs de passer de FREE (limité) à MEDIUM ou PRO (payant).

**Flow utilisateur:**
1. Vendeur clique "Passer au plan PRO" depuis `/seller/abonnement/`
2. Affichage de confirmation (`subscriptions/checkout.html`)
3. POST avec numéro téléphone → création `SubscriptionPayment` + génération `notif_token`
4. OAuth2 token fetch + appel `/orange-money-webpay/ml/v1/webpayment`
5. Redirection vers URL de paiement Orange
6. Paiement complété → redirection vers `/billing/return/`
7. Webhook asynchrone reçu sur `/billing/webhook/orange/` → activation subscription
8. User voit page de confirmation via polling

### Règles critiques (non-négociables)

**1. Authentification webhook par notif_token**
- Les webhooks font un lookup par `notif_token` UNIQUEMENT (jamais par `order_id`)
- `notif_token` est généré et stocké **AVANT** la redirection vers Orange Money (sécurité)
- Pas d'HMAC-SHA256 ou autre vérification cryptographique requise
- Lookup SQL: `SubscriptionPayment.objects.get(notif_token=notif_token)`

**2. Idempotence webhook**
- Si `payment.status == 'success'`, le webhook ne re-traite **PAS** le paiement
- Prévient les ré-activations si Orange Money renvoie le même webhook 2 fois
- Logging dans `WebhookLog` même pour les skips (audit trail)

**3. Stockage notif_token AVANT redirection**
- `notif_token` doit être sauvegardé dans la DB **avant** d'appeler l'API Orange Money
- Garantit que les webhooks ultérieurs peuvent faire un lookup sécurisé
- Voir `subscriptions/services/payment.py:create_orange_payment()`

**4. Longueur order_id ≤ 24 caractères**
- Orange Money retourne HTTP 400 si `order_id` > 24 chars
- Validation dans `subscriptions/services/orange_money.py:initiate_payment()`
- Format: `HF-{plan[0]}-{8 random hex chars}` (ex: `HF-M-a1b2c3d4`)

**5. @csrf_exempt UNIQUEMENT sur webhook**
- `/billing/webhook/orange/` → `@csrf_exempt` (reçoit POST du serveur Orange)
- `/billing/return/` → **PAS** `@csrf_exempt` (redirection navigateur, session utilisateur valide)
- `/billing/cancel/` → **PAS** `@csrf_exempt` (redirection navigateur, session utilisateur valide)

**6. SSL verification TOUJOURS activée**
- `requests.post(..., verify=True)` dans `subscriptions/services/orange_money.py`
- `requests` active SSL par défaut, mais documenter `verify=True` explicitement
- Jamais `verify=False` ou `REQUESTS_CA_BUNDLE` à vide

### Architecture

**Models:**
- `SubscriptionPayment`: order_id (≤24 chars), notif_token (unique, indexed), status, txn_id, etc.
- `WebhookLog`: Audit trail de tous les webhooks reçus (notif_token, status, raw_payload, processed)

**Services:**
- `subscriptions/services/orange_money.py`:
  - `_get_access_token()`: OAuth2 client_credentials
  - `initiate_payment()`: POST `/orange-money-webpay/.../pay` avec notif_token
  - `verify_callback()`: Parse webhook payload, retourne notif_token (sécurité)

- `subscriptions/services/payment.py`:
  - `_generate_order_id()`: Format court ≤24 chars
  - `_generate_notif_token()`: Token 64 hex chars
  - `create_orange_payment()`: Crée payment, génère notif_token, appelle Orange Money
  - `activate_subscription_from_payment()`: Idempotent, active subscription après paiement

**Views:**
- `subscriptions/billing_views.py:billing_callback_view()`: Webhook (`@csrf_exempt`)
  - Lookup par notif_token
  - Idempotence check (status == 'success')
  - Log dans WebhookLog
  - Activation subscription atomique

- `subscriptions/views.py:payment_callback_view()`: Webhook alternatif (historique)
  - Même logique que `billing_callback_view`
  - URL historique `/seller/abonnement/callback/` (préférer `/billing/webhook/orange/`)

**URLs stables enregistrées chez Orange Money:**
```
POST   /billing/webhook/orange/      → notification async paiement
GET    /billing/return/?order_id=... → redirection post-paiement (succès)
GET    /billing/cancel/?order_id=... → redirection post-paiement (annulation)
```

### Variables d'environnement requises

```bash
# OAuth2 client credentials
ORANGE_ML_CLIENT_ID=<ID>
ORANGE_ML_CLIENT_SECRET=<SECRET>

# Merchant
ORANGE_ML_MERCHANT_KEY=<KEY>

# Base URL pour Orange Money (HTTPS publique, pas localhost)
ORANGE_ML_BASE_URL=https://example.com

# URLs fixes (optionnel, sinon générées automatiquement)
ORANGE_ML_RETURN_URL=https://example.com/billing/return/
ORANGE_ML_CANCEL_URL=https://example.com/billing/cancel/
ORANGE_ML_NOTIFY_URL=https://example.com/billing/webhook/orange/
```

### Debugging & Monitoring

**En dev** (DEBUG=True):
- Endpoint `/seller/abonnement/debug-om/` affiche l'état de la config (visible seulement en DEBUG)
- Vérification des credentials + test OAuth2 token

**WebhookLog (audit trail):**
```python
# Consulter les webhooks reçus
from subscriptions.models import WebhookLog
logs = WebhookLog.objects.filter(status='SUCCESS').order_by('-created_at')
for log in logs[:10]:
    print(f"{log.notif_token} → {log.status} ({log.created_at})")
```

**Idempotence testing:**
```bash
# Simuler un webhook dupliqué
curl -X POST http://localhost:8000/billing/webhook/orange/ \
  -H "Content-Type: application/json" \
  -d '{"notif_token":"xxx", "status":"SUCCESS", "txnid":"yyy"}'
# Log: "Webhook already processed — notif_token=... (idempotent skip)"
```

### Points de vigilance

1. **Ne jamais logguer le notif_token en clair** (secret) — utiliser `[:16] + "..."` dans les logs
2. **Ne jamais afficher l'order_id à l'utilisateur** sur la page de paiement
3. **Webhook doit TOUJOURS retourner 200 OK** même en cas d'erreur (sinon Orange Money retry infini)
4. **order_id doit être UNIQUE** — voir la validation dans `SubscriptionPayment.save()`
5. **SSL verification JAMAIS désactivée** — auditer les appels `requests.post()` régulièrement

### Migration de la DB

```bash
python manage.py makemigrations subscriptions
python manage.py migrate subscriptions
```

Ajoute:
- Champ `notif_token` (unique, indexed) à `SubscriptionPayment`
- Change `order_id` max_length de 100 à 24
- Crée table `WebhookLog` avec indexes
