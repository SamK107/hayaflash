# 🏗️ HayaFlash — Architecture Technique (v2.0)

---

## 1. Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                        CLIENTS                              │
│   Browser Mobile (Client)   │   Browser Desktop (Vendeur)  │
└──────────────┬──────────────┴──────────────┬────────────────┘
               │                             │
               ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│                     Nginx / Reverse Proxy                   │
│              Static files, SSL termination                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Gunicorn (Django 5.2)                     │
│                                                             │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│   │ accounts │  │flash_sale│  │  orders  │  │ delivery │  │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│   │ products │  │analytics │  │   core   │  │  notifs  │  │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
│                                                             │
│                   services/ (business logic)                │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌────────────┐ ┌─────────┐ ┌─────────┐
       │ PostgreSQL │ │  Redis  │ │ Storage │
       │  (prod DB) │ │ (cache) │ │(S3/local│
       └────────────┘ └─────────┘ └─────────┘
              │
       ┌──────▼──────┐
       │  Celery     │
       │  (tasks     │
       │  async)     │
       └─────────────┘
```

---

## 2. Schéma ER Complet

### Entités principales

```
accounts_user
─────────────────────────────────────
id              UUID PK
phone           VARCHAR(20) UNIQUE    ← USERNAME_FIELD
email           VARCHAR(254)
display_name    VARCHAR(100)
is_active       BOOLEAN DEFAULT true
is_staff        BOOLEAN DEFAULT false
is_phone_verified BOOLEAN DEFAULT false
date_joined     TIMESTAMP
updated_at      TIMESTAMP
INDEX: phone

accounts_sellerprofile
─────────────────────────────────────
id              UUID PK
user_id         FK → accounts_user (1-1)
seller_code     VARCHAR(20) UNIQUE  auto "SLR-XXXXXXXX"
public_slug     VARCHAR(120) UNIQUE  ← /s/<slug>/
business_name   VARCHAR(200)
bio             TEXT
avatar          ImageField
delivery_zones  TEXT[]              ← zones gérées
is_active       BOOLEAN DEFAULT true
created_at      TIMESTAMP
updated_at      TIMESTAMP
INDEX: public_slug, seller_code

flash_sales_flashsale
─────────────────────────────────────
id              UUID PK
owner_id        FK → accounts_sellerprofile
title           VARCHAR(200)
description     TEXT
public_slug     VARCHAR(120) UNIQUE  ← /f/<slug>/
status          VARCHAR(20)  [scheduled|live|closed|executing|completed|cancelled]
start_time      TIMESTAMP
end_time        TIMESTAMP
delivery_zone   VARCHAR(200)         ← zone géographique
max_orders      INTEGER NULL         ← plafond optionnel
cover_image     ImageField
created_at      TIMESTAMP
updated_at      TIMESTAMP
INDEX: status, start_time, owner_id, public_slug

products_product
─────────────────────────────────────
id              UUID PK
flash_sale_id   FK → flash_sales_flashsale
name            VARCHAR(200)
description     TEXT
price           DECIMAL(10,2)
stock           INTEGER DEFAULT 0
unit            VARCHAR(50)          ← "pièce", "kg", "lot"
characteristics JSONB               ← {"couleur": "rouge", ...}
created_at      TIMESTAMP
updated_at      TIMESTAMP
INDEX: flash_sale_id

products_productmedia
─────────────────────────────────────
id              UUID PK
product_id      FK → products_product
media_type      VARCHAR(10) [image|video]
file            FileField / URLField
order           INTEGER DEFAULT 0    ← tri d'affichage
created_at      TIMESTAMP

orders_order
─────────────────────────────────────
id              UUID PK
flash_sale_id   FK → flash_sales_flashsale
client_request_id VARCHAR(36) UNIQUE  ← idempotence
customer_name   VARCHAR(200)
customer_phone  VARCHAR(20)
status          VARCHAR(30) [pending|confirmed|out_for_delivery|delivered|cancelled]
notes           TEXT
total_amount    DECIMAL(10,2)        ← calculé à la création
created_at      TIMESTAMP
updated_at      TIMESTAMP
INDEX: flash_sale_id, status, client_request_id, customer_phone, created_at

orders_orderitem
─────────────────────────────────────
id              UUID PK
order_id        FK → orders_order
product_id      FK → products_product
product_name_snapshot VARCHAR(200)
price_snapshot  DECIMAL(10,2)
quantity        INTEGER
subtotal        DECIMAL(10,2)        ← calculé

delivery_delivery
─────────────────────────────────────
id              UUID PK
order_id        FK → orders_order (1-1)
address_text    VARCHAR(500)         ← adresse saisie par client
latitude        DECIMAL(10,8) NULL
longitude       DECIMAL(11,8) NULL
geo_accuracy    FLOAT NULL           ← précision GPS en mètres
delivery_notes  TEXT NULL
status          VARCHAR(30) [pending|assigned|in_transit|delivered|failed]
assigned_to     VARCHAR(200) NULL    ← nom livreur (V1 free text)
scheduled_at    TIMESTAMP NULL
delivered_at    TIMESTAMP NULL
cod_amount      DECIMAL(10,2)        ← montant à collecter
cod_collected   BOOLEAN DEFAULT false
cod_collected_at TIMESTAMP NULL
cod_confirmed_by_id FK → accounts_user NULL
created_at      TIMESTAMP
updated_at      TIMESTAMP
INDEX: status, order_id

analytics_sharelink
─────────────────────────────────────
id              UUID PK
token           VARCHAR(32) UNIQUE
link_type       VARCHAR(20) [seller|flash_sale|product]
seller_id       FK → accounts_sellerprofile NULL
flash_sale_id   FK → flash_sales_flashsale NULL
product_id      FK → products_product NULL
target_key      VARCHAR(200) UNIQUE
click_count     INTEGER DEFAULT 0
share_count     INTEGER DEFAULT 0
conversion_count INTEGER DEFAULT 0
created_at      TIMESTAMP
INDEX: token, target_key

analytics_shareevent
─────────────────────────────────────
id              UUID PK
share_link_id   FK → analytics_sharelink
event_type      VARCHAR(30) [page_view|click|whatsapp_share|conversion]
source          VARCHAR(100)
order_id        FK → orders_order NULL
ip_hash         VARCHAR(64)          ← hash IP anonymisé
created_at      TIMESTAMP
INDEX: (share_link_id, event_type), (share_link_id, created_at), created_at
```

---

## 3. Flux Critiques

### 3.1 Flux Création de Commande

```
Client (Browser)
    │
    ├─ [Offline ?] → IndexedDB queue → retry quand online
    │
    └─ POST /api/v1/orders/
        body: {
          flash_sale_id, client_request_id (UUID),
          customer_name, customer_phone,
          items: [{product_id, quantity}],
          delivery: {address_text, latitude, longitude}
        }
            │
            ▼
        API View (validation basique)
            │
            ▼
        services.create_order()
            │
            ├─ 1. Vérifier flash_sale.status == "live"
            ├─ 2. Vérifier start_time ≤ now ≤ end_time
            ├─ 3. Idempotence check: client_request_id déjà connu ?
            │       └─ OUI → retourner Order existant (200)
            ├─ 4. BEGIN TRANSACTION
            │   ├─ 4a. select_for_update() sur Product rows
            │   ├─ 4b. Vérifier stock suffisant pour chaque item
            │   ├─ 4c. Créer Order (via GuardedOrderManager)
            │   ├─ 4d. Créer OrderItem(s) avec snapshots prix
            │   ├─ 4e. Créer Delivery (adresse + GPS)
            │   ├─ 4f. Décrémenter stock(s)
            │   └─ 4g. COMMIT
            ├─ 5. Enregistrer share_ref analytics (hors transaction)
            └─ 6. Retourner {order_id, status, total_amount}
                        │
                        ▼
                Dashboard Vendeur
                (HTMX polling → apparaît en < 5s)
```

### 3.2 Flux Cycle de Vie Vente Flash

```
Vendeur crée vente (status: scheduled)
    │
    ├─ Celery Beat ou cron check chaque minute
    │       └─ start_time atteint → status: live (auto)
    │
    ├─ OU Vendeur ouvre manuellement → status: live
    │
    ├─ [Commandes entrent en temps réel]
    │
    ├─ end_time atteint → status: closed (auto)
    │   OU Vendeur ferme manuellement
    │
    ├─ Vendeur traite les commandes → status: executing
    │   ├─ Confirme chaque commande → pending → confirmed
    │   ├─ Prépare et assigne livreur → out_for_delivery
    │   └─ Livraison effectuée → delivered + COD collecté
    │
    └─ Toutes commandes traitées → status: completed
```

### 3.3 Flux Géolocalisation

```
Page commande client (mobile)
    │
    ├─ navigator.geolocation.getCurrentPosition()
    │   ├─ Succès → {lat, lng, accuracy}
    │   │   ├─ accuracy > 500m → warning UX (pas bloquant)
    │   │   └─ Reverse geocoding Nominatim (OSM) → adresse suggestion
    │   │
    │   └─ Échec/refus → champ adresse textuelle obligatoire
    │
    ├─ Client confirme/corrige adresse
    │
    └─ Soumis avec commande
        │
        ▼
    Backend validation:
    ├─ lat in [-90, 90], lng in [-180, 180]
    ├─ Adresse texte non vide (min 10 chars)
    └─ Stocké dans Delivery
```

---

## 4. Stratégie Cache (Redis)

| Clé | TTL | Invalidation |
|---|---|---|
| `seller_stats:{seller_id}` | 300s | save FlashSale / Order |
| `flashsale_page:{slug}` | 60s | save FlashSale / Product |
| `seller_page:{slug}` | 300s | save SellerProfile |
| `live_orders_count:{sale_id}` | 5s | nouvelle commande |
| `otp:{phone}` | 300s | utilisé ou expiré |
| `ratelimit:order:{ip}` | 60s | rolling window |

### Invalidation pattern
```python
# Post-save signal sur Order
cache.delete(f"live_orders_count:{order.flash_sale_id}")
cache.delete(f"seller_stats:{order.flash_sale.owner_id}")
```

---

## 5. Multi-Worker & Concurrence

- **Gunicorn** : workers = (2 × CPU) + 1
- **select_for_update()** : obligatoire sur tout accès stock en écriture
- **Transactions atomiques** : `with transaction.atomic():` sur create_order
- **Idempotence** : `client_request_id` UNIQUE en DB (dernière ligne de défense)
- **Race condition test** : test de concurrence avec `threading.Thread` obligatoire dans la suite de tests

---

## 6. Sécurité

| Risque | Mitigation |
|---|---|
| Double commande | `client_request_id` UNIQUE DB |
| Oversell stock | `select_for_update` + transaction |
| Commande hors live | check `status + fenêtre temps` côté service |
| Spam commandes | Rate limit 30/IP/min (Redis) |
| GPS falsifié | Validation range server, pas bloquant |
| CSRF | Django middleware + HTMX headers |
| Webhook forgery | HMAC SHA-256 signature |
| Enumération slugs | Slugs aléatoires (pas séquentiels) |
| Données personnelles | Phones hashés dans les logs |

---

## 7. Offline Sync (Client JS)

```javascript
// Architecture de la sync queue
class HayaOrderQueue {
  async enqueue(orderPayload) {
    // Génère UUID côté client
    orderPayload.client_request_id = crypto.randomUUID();
    await idb.set(`queue:${orderPayload.client_request_id}`, orderPayload);
  }

  async flush() {
    const pending = await idb.list('queue:');
    for (const item of pending) {
      try {
        const res = await fetch('/api/v1/orders/', {
          method: 'POST',
          body: JSON.stringify(item),
          headers: {'Content-Type': 'application/json'}
        });
        if (res.ok || res.status === 409) {
          // 409 = idempotence déjà traité
          await idb.delete(`queue:${item.client_request_id}`);
        }
        // Sinon retry au prochain flush
      } catch (e) {
        // Réseau indisponible → retry
      }
    }
  }
}

// Flush au retour de connexion
window.addEventListener('online', () => queue.flush());
// Flush périodique
setInterval(() => queue.flush(), 30_000);
```

---

## 8. Celery Tasks

| Task | Trigger | Description |
|---|---|---|
| `auto_open_flash_sales` | Cron 1min | Passe `scheduled → live` si `start_time` atteint |
| `auto_close_flash_sales` | Cron 1min | Passe `live → closed` si `end_time` atteint |
| `send_sale_reminder_sms` | Scheduled | SMS aux clients inscrits aux rappels |
| `aggregate_analytics` | Daily | Calcul stats historiques |

---

## 9. Roadmap Technique

### V1.1 — Paiement Mobile Money
- Intégration Orange Money / MTN MoMo
- Entité `PaymentTransaction` (déjà scaffoldée)
- Webhook HMAC pour confirmation

### V1.2 — Livraison avancée
- Assignation livreur avec compte
- Tracking temps réel livreur (position GPS)
- Preuve de livraison (photo)

### V2 — Multi-tenant
- `SellerProfile` → `Tenant` avec isolation DB (schéma séparé)
- Sous-domaines : `{slug}.hayaflash.com`

### V2.1 — Marketplace
- Multi-vendeurs par vente flash
- Commission platform

---

## 10. Gap Analysis (état actuel → V1 target)

| Module | État | Gap V1 |
|---|---|---|
| accounts | ✅ | — |
| flash_sales | ✅ | Ajouter `delivery_zone`, `max_orders`, médias |
| products | ✅ | Ajouter `ProductMedia`, `characteristics` |
| orders | ✅ | Intégrer `Delivery` dans `create_order()` |
| delivery | ❌ | À créer entièrement |
| analytics | ✅ | — |
| notifications | ⏳ | SMS rappel vente, confirmation commande |
| subscriptions | ⏳ | Scaffold → enforcement middleware |
| CI/CD | ❌ | Dockerfile + GitHub Actions |
| OpenAPI | ❌ | Générer depuis DRF |
| Tests E2E | ❌ | Playwright ou Cypress |
| Calendrier public | ❌ | Page ventes programmées |

---

## 🔚 Fin du document