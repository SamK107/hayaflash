# 📊 HayaFlash — État du Codebase (v1.0)

> Généré le 2025-05-20. Basé sur analyse du code source réel.
> **Ce fichier est la source de vérité sur ce qui EXISTE et ce qui RESTE À FAIRE.**
> Mettre à jour après chaque sprint.

---

## 🗂️ Structure actuelle du projet

```
hayaflash/
├── accounts/          ✅ Implémenté
├── analytics/         ✅ Implémenté
├── core/              ✅ Implémenté
├── flash_sales/       ✅ Partiel (gaps ci-dessous)
├── notifications/     ⏳ Scaffold vide
├── orders/            ✅ Partiel (gaps ci-dessous)
├── delivery/          ✅ Implémenté (module + dashboard HTMX)
├── payments/          ✅ Mock complet
├── products/          ✅ Partiel (gaps ci-dessous)
├── subscriptions/     ⏳ Scaffold vide
├── config/            ✅ Complet
├── static/orders/js/  ✅ Offline queue IndexedDB
└── templates/         ✅ Partiel
```

---

## ✅ CE QUI EXISTE — Détail par module

### `accounts/`
| Fichier | Contenu réel | État |
|---|---|---|
| `models.py` | `User` (phone E.164, USERNAME_FIELD), `SellerProfile` (seller_code auto, public_slug) | ✅ |
| `backends.py` | `PhoneAuthBackend` | ✅ |
| `serializers.py` | Register/login serializers | ✅ |
| `views.py` | Register, login, logout, me | ✅ |
| `urls.py` | Routes auth | ✅ |
| `services/auth.py` | Logique d'authentification | ✅ |
| `services/otp.py` | OTP generation/validation | ✅ |
| `services/seller_codes.py` | `generate_unique_seller_code()` | ✅ |
| `services/slugs.py` | `generate_unique_seller_public_slug()` | ✅ |
| `services/sms.py` | SMS scaffold | ✅ |
| `services/users.py` | Services user | ✅ |
| `migrations/` | 3 migrations (initial + public_slug + populate) | ✅ |

**Champs présents sur `SellerProfile` :**
- `user`, `seller_code`, `public_slug`, `business_name`, `is_active`, `created_at`, `updated_at`

**Champs ABSENTS (requis par PROJECT_SPEC v2) :**
- ❌ `bio`
- ❌ `avatar` (ImageField)
- ❌ `delivery_zones` (zones gérées)

---

### `flash_sales/`
| Fichier | Contenu réel | État |
|---|---|---|
| `models.py` | `FlashSale` (title, public_slug, start_time, end_time, status, owner) | ✅ |
| `models.py` | `FlashSaleStatus` : `draft / live / closed` | ✅ |
| `models.py` | `is_live()`, `open_sale()`, `close_sale()` | ✅ |
| `services/ordering.py` | `assert_flash_sale_accepts_orders()` | ✅ |
| `services/slugs.py` | Génération slug unique | ✅ |
| `migrations/` | 3 migrations | ✅ |

**Champs ABSENTS (requis par PROJECT_SPEC v2) :**
- ❌ `description` (TextField)
- ❌ `cover_image` (ImageField)
- ❌ `delivery_zone` (zone géographique)
- ❌ `max_orders` (plafond optionnel)
- ❌ Statuts étendus : `scheduled / executing / completed / cancelled`
  - ⚠️ Actuellement : `draft / live / closed` seulement
- ❌ Ouverture/fermeture automatique (pas de Celery/cron)

---

### `products/`
| Fichier | Contenu réel | État |
|---|---|---|
| `models.py` | `Product` (flash_sale FK nullable, name, price, stock) | ✅ |
| `migrations/` | 1 migration | ✅ |

**Champs ABSENTS (requis par PROJECT_SPEC v2) :**
- ❌ `description` (TextField)
- ❌ `unit` (kg, pièce, lot...)
- ❌ `characteristics` (JSONB)
- ❌ `ProductMedia` (modèle entier absent — photos/vidéos)

---

### `orders/`
| Fichier | Contenu réel | État |
|---|---|---|
| `models.py` | `Order`, `OrderItem`, `GuardedOrderManager`, `total_amount` | ✅ |
| `models.py` | `OrderStatus` : `pending / confirmed / out_for_delivery / delivered / cancelled` | ✅ |
| `services/create_order.py` | `create_order()` idempotent + `Delivery` atomique + `total_amount` | ✅ ⭐ |
| `services/dashboard.py` | KPI cache, advance_order_status, order rows | ✅ |
| `services/client_order.py` | Rate limit, mapping public + bloc `delivery` | ✅ |
| `api.py` | API REST commande publique + réponse `delivery` / `total_amount` | ✅ |
| `views.py` | Dashboard HTMX, advance status, client order page | ✅ |
| `urls.py` | Routes | ✅ |
| `templates/orders/` | `dashboard.html`, `client_order.html` (GPS + adresse), partials | ✅ |
| `static/orders/js/client_order_queue.js` | Offline queue + GPS + payload `delivery` | ✅ ⭐ |
| `migrations/` | 4 migrations (total_amount, out_for_delivery, data migrate) | ✅ |

**Intégration livraison :**
- ✅ `create_order()` crée `Delivery` dans la même transaction
- ✅ `total_amount` calculé et persisté à la création
- ✅ Dashboard livraisons vendeur HTMX (`/orders/seller/deliveries/`)

---

### `delivery/`
| Fichier | Contenu réel | État |
|---|---|---|
| `models.py` | `Delivery` (adresse, GPS, COD, statuts, maps/waze URLs) | ✅ |
| `services/validation.py` | Validation adresse + coordonnées GPS | ✅ |
| `services/delivery.py` | `create_delivery_for_order()`, `advance_delivery()`, `list_seller_deliveries()` | ✅ |
| `api.py` | `GET /api/v1/delivery/`, `PATCH .../advance/` (auth vendeur) | ✅ |
| `admin.py` | Delivery admin | ✅ |
| `views.py` | Dashboard HTMX livraisons post-live + partials | ✅ |
| `services/seller_dashboard.py` | Contexte page, summary, rows, actions HTMX | ✅ |
| `tests_dashboard.py` | Tests dashboard vendeur | ✅ |

---

### `analytics/`
| Fichier | Contenu réel | État |
|---|---|---|
| `models/share.py` | `ShareLink`, `ShareEvent`, `ShareLinkType`, `ShareEventType` | ✅ |
| `services/share_links.py` | Création/résolution liens | ✅ |
| `services/view_tracking.py` | Tracking vues | ✅ |
| `services/share_tracking.py` | Tracking partages WhatsApp | ✅ |
| `services/conversion_tracking.py` | Attribution share_ref → commande | ✅ |
| `services/cache.py` | Cache invalidation (Redis/LocMem) | ✅ |
| `services/public_pages.py` | Contexte pages publiques SEO | ✅ |
| `services/seo.py` | OpenGraph, JSON-LD | ✅ |
| `services/abuse.py` | Anti-spam, déduplication | ✅ |
| `services/events.py` | Enregistrement événements | ✅ |
| `aggregators/seller_stats.py` | Stats agrégées vendeur | ✅ |
| `signals.py` | Post-save signals pour invalidation cache | ✅ |
| `views.py` | Pages publiques vendeur `/s/<slug>/`, flash sale `/f/<slug>/`, WhatsApp redirect | ✅ |
| `templates/analytics/` | `seller_public.html`, `flash_sale_public.html`, partials SEO | ✅ |
| `migrations/` | 2 migrations | ✅ |

---

### `payments/`
| Fichier | Contenu réel | État |
|---|---|---|
| `models.py` | `PaymentTransaction` (UUID PK), `LedgerEntry` | ✅ |
| `services/payments.py` | Initiation paiement | ✅ |
| `services/mock_provider.py` | Mock Mobile Money (dev) | ✅ |
| `services/webhooks.py` | Validation HMAC webhook | ✅ |
| `services/ledger.py` | Enregistrement ledger | ✅ |
| `api.py` | `/payments/initiate/`, `/payments/webhook/` | ✅ |
| `migrations/` | 1 migration | ✅ |

**Note :** Les payments sont scaffoldés avec mock. En V1 COD (paiement à la livraison), ce module est en veille — ne pas supprimer, il servira en V1.1.

---

### `core/`
| Fichier | Contenu réel | État |
|---|---|---|
| `services/slugs.py` | Génération slugs centralisée | ✅ |
| `views.py` | Home page | ✅ |
| `urls.py` | Home URL | ✅ |

---

### `config/`
| Fichier | Contenu réel | État |
|---|---|---|
| `settings/base.py` | Settings complets (Redis, DB multi-env, WhiteNoise, DRF, CORS, HTMX) | ✅ |
| `settings/dev.py` | Dev settings | ✅ |
| `settings/staging.py` | Staging settings | ✅ |
| `settings/prod.py` | Prod settings | ✅ |
| `urls.py` | URL routing principal | ✅ |
| `api_urls.py` | Routes API v1 | ✅ |
| `wsgi.py` / `asgi.py` | Entry points | ✅ |

---

### `notifications/` — ⏳ Scaffold vide
```
notifications/
├── models.py      → classe vide
├── views.py       → vide
├── services/      → __init__.py vide
└── tests.py       → vide
```
**Aucune logique implémentée.**

---

### `subscriptions/` — ⏳ Scaffold vide
```
subscriptions/
├── models.py      → classe vide
├── views.py       → vide
├── services/      → __init__.py vide
└── tests.py       → vide
```
**Aucune logique implémentée.**

---

## ❌ CE QUI MANQUE ENTIÈREMENT

### 1. ~~Dashboard livraisons vendeur (HTMX)~~ ✅

---

### 2. Calendrier public des ventes programmées

**N'existe pas.** Page `/ventes/` ou `/` listant les ventes `scheduled` et `live`.

À créer :
- View : `flash_sales/views.py` → `public_flash_sales_list()`
- Template : `templates/flash_sales/public_list.html`
- URL : `/ventes/` ou `/`
- Context : ventes actives + prochaines + countdown

---

### 4. API REST flash sales publiques

**L'endpoint `GET /api/v1/flash-sales/` n'existe pas.**

À créer dans `flash_sales/` :
- Serializer : `FlashSalePublicSerializer`
- View : `FlashSaleListAPIView` + `FlashSaleDetailAPIView`
- URL : `/api/v1/flash-sales/` et `/api/v1/flash-sales/<slug>/`

---

### 5. Statuts FlashSale étendus

Actuellement : `draft / live / closed`
Requis par spec : `scheduled / live / closed / executing / completed / cancelled`

Migration nécessaire : ajouter les nouveaux choix + renommer `draft → scheduled`.

---

### 6. Champs manquants sur les modèles existants

**`FlashSale`** — migrations à créer :
```python
description     = models.TextField(blank=True)
cover_image     = models.ImageField(null=True, blank=True)
delivery_zone   = models.CharField(max_length=200, blank=True)
max_orders      = models.IntegerField(null=True, blank=True)
```

**`Product`** — migrations à créer :
```python
description     = models.TextField(blank=True)
unit            = models.CharField(max_length=50, default='pièce')
characteristics = models.JSONField(default=dict, blank=True)
```

**`ProductMedia`** — nouveau modèle :
```python
class ProductMedia(models.Model):
    product    = models.ForeignKey(Product, related_name='media', ...)
    media_type = models.CharField(choices=['image', 'video'])
    file       = models.FileField(...)
    order      = models.IntegerField(default=0)
```

**`SellerProfile`** — migrations à créer :
```python
bio             = models.TextField(blank=True)
avatar          = models.ImageField(null=True, blank=True)
delivery_zones  = models.CharField(max_length=500, blank=True)
```

---

### 7. Infrastructure CI/CD

**Rien n'existe dans le repo.**

À créer :
```
.github/workflows/deploy.yml   ← CI tests + build + deploy staging + approval + prod
Dockerfile                     ← Image Docker Python 3.11
docker-compose.yml             ← Dev local (DB + Redis)
infra/scripts/smoke_test.sh    ← Smoke tests post-deploy
```

---

### 8. Celery (tâches asynchrones)

**Non installé.** `celery` absent de `requirements.txt`.

Requis pour :
- Auto-ouverture des ventes `scheduled → live` à `start_time`
- Auto-fermeture `live → closed` à `end_time`
- SMS rappel clients

À ajouter :
```
requirements.txt  → celery, redis
config/celery.py  → app Celery
```

---

### 9. ~~`total_amount` sur `Order`~~ ✅

Calculé et persisté dans `create_order()`.

---

## ⚠️ INCONSISTANCES À CORRIGER

| Problème | Localisation | Action |
|---|---|---|
| Payload JS envoie `name`/`phone`/`quantity` (mappé serveur) vs spec `customer_name`/`items[]` | `client_order.py` | Acceptable V1 — mapping serveur en place |
| Pas de rate limiting DRF throttle sur orders | `orders/api.py` | ✅ Rate limit service layer (30/IP/min) — polish headers optionnel |
| Dashboard livraisons HTMX absent | `delivery/views.py` | ✅ Implémenté PROMPT 10.1 |

---

## 📦 Dépendances installées (`requirements.txt`)

```
Django==5.2.13
djangorestframework==3.16.1
django-redis==5.4.0
django-cors-headers==4.9.0
django-htmx==1.27.0
gunicorn==25.3.0
psycopg2-binary==2.9.11
python-dotenv==1.2.2
whitenoise==6.12.0
pillow==12.2.0
dj-database-url==2.3.0
requests==2.33.1
```

**Manquant :**
- ❌ `celery` (tâches async)
- ❌ `redis` (client Python direct — django-redis le fournit indirectement mais celery en a besoin)

---

## 🧪 Tests existants

| App | Fichier | État |
|---|---|---|
| `orders` | `orders/tests.py` | ✅ Présent (delivery intégré) |
| `delivery` | `delivery/tests.py` | ✅ Présent |
| `analytics` | `analytics/tests.py` | Présent |
| `payments` | `payments/tests.py` | Présent |
| `accounts` | `accounts/tests.py` | Présent |
| `flash_sales` | `flash_sales/tests.py` | Présent |
| `products` | `products/tests.py` | Présent |
| `core` | `core/tests.py` | Présent |
| E2E | — | ❌ Absent |
| GPS offline | — | ❌ Absent |
| Concurrence PostgreSQL | — | À vérifier dans orders/tests.py |

---

## 🗺️ Roadmap V1 — Par priorité

### P0 — Bloquant (V1 non viable sans ça)

1. ~~**Créer app `delivery/`**~~ ✅
2. ~~**Intégrer `Delivery` dans `create_order()`**~~ ✅
3. ~~**GPS côté client**~~ ✅
4. ~~**Aligner payload JS**~~ ✅ (mapping serveur + bloc `delivery`)
5. ~~**Renommer `OrderStatus.SHIPPED`**~~ ✅ → `out_for_delivery`

### P1 — Important

6. **Statuts FlashSale étendus** (`scheduled`, `executing`, `completed`, `cancelled`)
7. **Champs manquants** `FlashSale.description/delivery_zone`, `Product.unit/description`
8. ~~**Dashboard livraisons vendeur**~~ ✅
9. **API flash sales publiques** `GET /api/v1/flash-sales/`
10. **Rate limiting orders** — ✅ fonctionnel (service layer) ; polish tests/headers optionnel

### P2 — Utile

11. **`ProductMedia`** modèle (photos/vidéos produits)
12. **Calendrier public** des ventes programmées
13. **Celery** pour auto-open/close des ventes
14. **`SellerProfile`** champs bio/avatar
15. **Dockerfile + CI/CD**

### P3 — Nice-to-have

16. **Notifications SMS** (rappels, confirmation commande)
17. **Subscriptions** (enforcement middleware)
18. **OpenAPI** (génération depuis DRF)

---

# NEXT RECOMMENDED PHASE

Current recommended focus:

- Statuts FlashSale étendus + champs produit/vente
- API flash sales publiques `GET /api/v1/flash-sales/`
- Calendrier public des ventes programmées

Production hardening should wait until:
- delivery dashboard vendeur stable
- critical workflows finalized
- test coverage improved

---


## 🔚 Fin du document