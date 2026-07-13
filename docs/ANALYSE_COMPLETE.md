# HayaFlash — Analyse Complète du Codebase
> Générée le 2026-07-04 par Cowork (Claude).  
> Source : analyse du code source réel + MASTER_CONTEXT (12 parties) + PROJECT_SPEC v2 + DJANGO_REFERENCE 2026-07.  
> **Ce document est la base de travail pour le plan d'implémentation.**

---

## 1. Résumé Exécutif

HayaFlash est une plateforme SaaS de Live Commerce mobile-first conçue pour l'Afrique francophone. L'architecture technique (Django + HTMX + Alpine.js + Tailwind + PostgreSQL) est bien choisie et pertinente. Le cœur transactionnel (création de commande idempotente, offline queue, géolocalisation, analytics viral) est solide.

**État global : ~45% de la V1 implémentée.**

Ce qui existe est de bonne qualité technique (services bien séparés, transactions atomiques, idempotence). Ce qui manque couvre principalement les interfaces vendeur (aucun CRUD UI), les statuts étendus de vente, le design moderne (pas de Tailwind), l'infrastructure Celery/CI/CD, et deux modules entiers vides (notifications, subscriptions).

---

## 2. Audit Module par Module

### ✅ `accounts/` — Solide

| Composant | État | Remarque |
|---|---|---|
| `User` (phone E.164, USERNAME_FIELD) | ✅ | Conforme spec |
| `SellerProfile` (seller_code, public_slug, business_name) | ✅ | — |
| `PhoneAuthBackend` | ✅ | — |
| `services/auth.py`, `otp.py`, `seller_codes.py`, `slugs.py` | ✅ | Architecture service correcte |
| `services/sms.py` | ✅ scaffold | Pas d'envoi réel |
| `views.py` (register, login, logout, me) | ✅ | — |
| Templates login/register | ✅ | Minimalistes, pas de Tailwind |

**Champs ABSENTS sur SellerProfile** (requis spec) :
- `bio` (TextField)
- `avatar` (ImageField)
- `delivery_zones` (zones gérées par le vendeur)

---

### ⚠️ `flash_sales/` — Partiel

| Composant | État | Remarque |
|---|---|---|
| Modèle `FlashSale` | ✅ partiel | Manque champs critiques |
| `FlashSaleStatus` : `draft / live / closed` | ⚠️ | Incomplet — spec exige 6 statuts |
| `is_live()`, `open_sale()`, `close_sale()` | ✅ | — |
| `services/ordering.py` | ✅ | — |
| Views/URLs CRUD vendeur | ❌ | **Aucune interface vendeur** |
| API publiques flash sales | ❌ | `GET /api/v1/flash-sales/` inexistant |
| Celery auto-open/close | ❌ | Pas de Celery installé |

**Champs ABSENTS sur FlashSale** :
- `description` (TextField)
- `cover_image` (ImageField)
- `delivery_zone` (CharField)
- `max_orders` (IntegerField, optionnel)
- Statuts `scheduled`, `executing`, `completed`, `cancelled`

---

### ⚠️ `products/` — Très partiel

| Composant | État | Remarque |
|---|---|---|
| Modèle `Product` (name, price, stock) | ✅ partiel | Champs minimalistes |
| 1 migration | ✅ | — |
| Views/URLs CRUD | ❌ | Aucune interface |
| `ProductMedia` | ❌ | Modèle entier absent |
| `ProductVariant` | ❌ | Modèle entier absent |
| `StockMovement` | ❌ | Ledger de stock absent |

**Champs ABSENTS sur Product** :
- `description` (TextField)
- `unit` (kg, pièce, lot...)
- `characteristics` (JSONField)
- `display_order` (IntegerField)
- `stock_initial` (séparé de `stock_available`)

---

### ✅ `orders/` — Cœur solide

| Composant | État | Remarque |
|---|---|---|
| `Order`, `OrderItem`, `GuardedOrderManager` | ✅ | Pattern excellent |
| `OrderStatus` : pending/confirmed/out_for_delivery/delivered/cancelled | ✅ | Conforme spec |
| `services/create_order.py` — idempotent, atomique, `select_for_update` | ✅ ⭐ | Robuste |
| `services/dashboard.py` — KPI, advance_status | ✅ | — |
| Dashboard HTMX (polling 5s) | ✅ | Fonctionnel, design basique |
| Page commande client + GPS | ✅ | — |
| Offline queue IndexedDB JS | ✅ ⭐ | Solide |
| `GET /api/v1/orders/` (liste par vente) | ❌ | Absent |

---

### ✅ `delivery/` — Bien implémenté

Modèle complet (adresse, GPS, COD, statuts, Maps URLs), services, dashboard HTMX, API. Solide.

---

### ✅ `analytics/` — Complet

ShareLink, ShareEvent, tracking viral, SEO OpenGraph/JSON-LD, pages publiques vendeur et vente, tracking conversion. Module le plus complet du projet.

---

### ✅ `payments/` — Scaffold mock

PaymentTransaction, LedgerEntry, mock Orange Money, HMAC webhooks. En veille (COD en V1). À activer en V1.1.

---

### ❌ `notifications/` — Entièrement vide

models.py vide, views.py vide, services/__init__.py vide. Rien implémenté.

---

### ❌ `subscriptions/` — Entièrement vide

Idem. Plans Free/Pro, enforcement middleware : tout à créer.

---

### ✅ `config/` — Bien structuré

Settings multi-env (base/dev/staging/prod), Redis optionnel, WhiteNoise, CORS, HTMX. Solide.

---

## 3. Gaps vs DJANGO_REFERENCE 2026-07

| Recommandation | État actuel | Action |
|---|---|---|
| `Argon2PasswordHasher` | ❌ absent | Ajouter `django[argon2]` + config |
| `LANGUAGE_CODE = "fr-fr"` | ❌ `"en-us"` | Corriger |
| `TIME_ZONE = "Africa/Bamako"` | ❌ `"UTC"` | Corriger |
| `Celery` (broker, beat) | ❌ absent | Ajouter `celery`, `config/celery.py` |
| `settings/test.py` (CI, DB en mémoire) | ❌ absent | Créer |
| `Sentry` (production) | ❌ absent | Ajouter `settings/prod.py` |
| `django-debug-toolbar` (dev) | ❌ absent | Ajouter `settings/dev.py` |
| Logging structuré (verbose formatter) | ⚠️ minimal | Enrichir |
| `Dockerfile` optimisé | ❌ absent | Créer |
| `docker-compose.yml` (dev) | ❌ absent | Créer |
| `infra/nginx/` | ❌ absent | Créer |
| `.github/workflows/ci.yml` | ❌ absent | Créer |
| `.github/workflows/deploy.yml` | ❌ absent | Créer |

> **Note DRF** : `.cursor/rules` dit "DRF interdit" mais PROJECT_SPEC dit "API-first avec DRF". Recommandation : **garder DRF** pour l'API publique (mobile futur). Les views internes restent en FBV Django pur.

---

## 4. Ce qui fonctionne vs ce qui manque

### Flux fonctionnels aujourd'hui
```
✅ Vendeur crée un compte (phone + OTP)
✅ Client passe commande (formulaire + GPS + offline queue)
✅ Commande apparaît dans le dashboard (HTMX polling)
✅ Vendeur avance le statut (confirm/deliver)
✅ Livraison créée automatiquement à la commande
✅ Dashboard livraisons vendeur
✅ Pages publiques vendeur + vente (SEO)
✅ Analytics viral (share links, tracking)
```

### Flux cassés ou inexistants
```
❌ Vendeur ne peut PAS créer une vente flash (pas d'UI)
❌ Vendeur ne peut PAS ajouter des produits (pas d'UI)
❌ Vente ne s'ouvre/ferme PAS automatiquement (pas de Celery)
❌ Statuts étendus absents (scheduled, executing, completed)
❌ Aucun calendrier public des ventes
❌ Aucune notification (SMS/WhatsApp)
❌ Aucun enforcement d'abonnement
❌ Interface non stylisée (pas Tailwind)
❌ Impossible de déployer de façon reproductible (pas de Docker/CI)
```

---

## 5. Points de Qualité Urgents

- `FlashSaleStatus` : renommer `DRAFT → SCHEDULED`, ajouter `EXECUTING`, `COMPLETED`, `CANCELLED`
- `Product.stock` : séparer en `stock_initial` + `stock_available`
- `base.html` : Tailwind CDN + Alpine.js + meta viewport complet
- Argon2 à activer
- Headers HSTS/CSP/X-Frame en prod
- `prefetch_related('items__product')` systématique sur listes orders
- Touch targets min 48px (actuellement non garanti)
- Badge LIVE pulsant + timer countdown : absents

---

## 6. Résumé des Priorités

### P0 — Bloquant absolu
1. Interface CRUD vendeur (créer/modifier vente flash)
2. Interface CRUD produits (ajouter/modifier produits avec stock)
3. Statuts FlashSale étendus + champs manquants
4. Celery auto-open/close des ventes
5. Tailwind + design moderne sur pages critiques

### P1 — Important pour la valeur produit
6. Calendrier public des ventes (scheduled + live)
7. API flash sales publiques
8. ProductMedia (photos/vidéos)
9. Notifications (SMS confirmation commande)
10. Infrastructure (Dockerfile, docker-compose, CI/CD)

### P2 — Utile pour la croissance$$
11. Subscriptions (enforcement middleware)
12. SellerProfile champs (bio, avatar)
13. StockMovement ledger
14. Tests E2E

---

## 7. Verdict Final

HayaFlash a une **base technique solide**. Le cœur transactionnel est production-ready. Le blocage principal est l'**absence d'interface vendeur** : impossible de créer une vente ou des produits sans passer par l'admin Django.

Avec le plan en 6 phases documenté dans `PLAN_PHASES.md`, la V1 peut être complète et déployable en production. Durée estimée : 10–14 semaines de développement.
