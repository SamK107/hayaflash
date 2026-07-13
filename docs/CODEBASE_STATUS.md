# HayaFlash — État du Codebase

> Mis à jour le 2026-07-13. Basé sur audit direct du code source (pas sur les docs).
> **Ce fichier est la source de vérité sur ce qui EXISTE et ce qui RESTE À FAIRE.**
> Mettre à jour après chaque chantier significatif.

---

## Structure actuelle

```
hayaflash/
├── accounts/       ✅ Complet
├── analytics/      ✅ Complet
├── config/         ✅ Complet
├── core/           ✅ Complet
├── delivery/       ✅ Complet
├── flash_sales/    ✅ Complet
├── notifications/  ✅ Complet
├── orders/         ✅ Complet
├── payments/       ✅ Mock complet (COD V1, activer en V1.1)
├── products/       ✅ Complet
├── subscriptions/  ✅ Complet
├── templates/      ✅ Complet
├── Dockerfile      ✅ Présent
├── docker-compose.yml              ✅ Dev
├── docker-compose.production.yml   ✅ Prod
└── .github/workflows/ci.yml + deploy.yml  ✅ Présent
```

---

## État détaillé par module

### `accounts/`
- `User` : phone E.164, `USERNAME_FIELD = "phone"`, `PhoneAuthBackend`
- `SellerProfile` : `seller_code` (auto), `public_slug`, `business_name`, `bio`, `avatar` (ImageField), `delivery_zones`, `is_active`
- Services : auth, OTP, seller_codes, slugs, SMS, users
- 4 migrations en place (dont populate slugs + bio/avatar/zones)

### `flash_sales/`
- `FlashSaleStatus` (6 valeurs) : `scheduled / live / closed / executing / completed / cancelled`
- `FlashSale` : title, description, cover_image, public_slug, start_time, end_time, status, owner, delivery_zone, max_orders, description_audio (FileField WebM), teasers
- Méthodes : `open_sale()`, `close_sale()`, `complete_sale()`, `cancel_sale()`, `accepts_orders`
- `SaleInterest` : flash_sale (FK), phone, name (optionnel), created_at — créé depuis `/f/<slug>/` (bouton "M'alerter")
- Celery tasks : `auto_open_scheduled_sales` + `auto_close_live_sales` (beat schedule 60s)
- CRUD vendeur complet : list, create, edit, detail, open, close, clone
- Vue `sale_interests_view` + template `interests.html` — visible côté vendeur

### `products/`
- `Product` : flash_sale (FK nullable), name, description, price, stock_initial, stock_available, unit, characteristics (JSONField), description_audio (FileField), display_order, is_active
- `ProductMedia` : product (FK), media_type (image/video), file (ImageField), video_url, alt_text, order
- `ProductVariant` : product (FK), type, value, stock, price_delta
- `StockMovement` : product, order (FK nullable), quantity_change, movement_type (reservation/release/correction/initial), notes

### `orders/`
- `Order` : flash_sale (FK), customer_name, customer_phone, status, client_request_id (unique — idempotence), total_amount, created_at
- `OrderStatus` : pending / confirmed / out_for_delivery / delivered / cancelled
- `GuardedOrderManager` bloque `Order.objects.create()` — utiliser `create_order()` uniquement
- `create_order()` : atomique, idempotent, décrémente stock avec guard `stock_available__gte`, crée `Delivery` et `StockMovement` dans la même transaction
- Dashboard LIVE HTMX : KPI (total_orders, total_quantity, total_revenue, pending_revenue) + liste commandes polling 3s
- Cache KPI TTL 4 secondes

### `delivery/`
- `Delivery` : order (OneToOne), address_text, latitude, longitude, geo_accuracy, geo_method, delivery_notes, status, assigned_to, cod_amount, cod_collected
- `Delivery.GeoMethod` : gps / manual / timeout / denied
- Dashboard livraisons HTMX vendeur (`/orders/seller/deliveries/`)
- Méthodes : `get_maps_url()`, `get_waze_url()`

### `subscriptions/`
- `Plan` (TextChoices) : `free / medium / pro`
- Prix : FREE=0 FCFA, MEDIUM=2 000 FCFA, PRO=5 000 FCFA
- Limites ventes/mois : FREE=3, MEDIUM=3, PRO=None (illimité)
- `Subscription` : seller (OneToOne), plan, expires_at
- `SubscriptionPayment` : UUID PK, seller, plan, provider, amount, phone, status, order_id, pay_token, txn_id, payment_url, raw_response, raw_callback, paid_at
- Providers : orange / moov / wave
- Service Orange Money dans `subscriptions/services/orange_money.py`
- Vues billing : checkout, payment_pending, subscription dashboard

### `notifications/`
- `Notification` : recipient_phone, channel (whatsapp/sms/email), message, status (pending/sent/failed), error_message, sent_at
- Services : `dispatcher.py`, `sms.py`, `whatsapp.py`
- Celery tasks : `send_order_confirmation` (déclenchée à création commande), `send_sale_reminder` (rappel 1h avant vente)

### `analytics/`
- `ShareLink` : token (unique 10 chars), link_type (seller/flash_sale/product), seller, flash_sale, product, target_key, click_count, share_count, conversion_count
- `ShareEvent` : share_link, event_type (page_view/click/whatsapp_share/conversion), source, order (FK nullable)
- Services : share_links, share_tracking, view_tracking, conversion_tracking, public_pages, seo (OG + JSON-LD), abuse (anti-spam)
- `get_seller_public_stats()` : total_orders + products_sold (agrégé, mis en cache)
- Pages publiques : `/s/<slug>/` (vendeur), `/f/<slug>/` (vente flash), redirect WhatsApp tracké

### `payments/`
- `PaymentTransaction` (UUID PK) + `LedgerEntry`
- Mock provider en place
- En veille pour V1 (COD actif) — ne pas supprimer, sera activé en V1.1

### `config/`
- Settings multi-env : base, dev, staging, prod, test
- `celery.py` : beat schedule auto open/close ventes (60s)
- Docker : Dockerfile + docker-compose.yml (dev) + docker-compose.production.yml
- CI/CD : `.github/workflows/ci.yml` + `deploy.yml`

---

## Ce qui n'existe PAS (lacunes identifiées — juillet 2026)

### 1. Admin plateforme custom
Seul `django.contrib.admin` standard est exposé (`/admin/`). Il n'existe pas de vue custom dédiée à la gestion plateforme (abonnements, paiements, vendeurs).

- `SubscriptionPayment` n'est pas enregistré dans l'admin Django.
- Pas de dashboard plateforme avec métriques globales (MRR, vendeurs actifs, etc.).

### 2. Stats par vente flash (UI)
`get_dashboard_kpis()` retourne des KPIs globaux (toutes ventes confondues). Il n'y a pas de vue analytique par vente flash individuelle côté vendeur.

Les features MEDIUM ("Statistiques de ventes 30 derniers jours") et PRO ("Statistiques avancées") sont déclarées dans `PLAN_FEATURES` mais aucune vue ne les différencie — le dashboard est identique pour tous les plans.

### 3. Partage — QR code et Web Share API
Seul WhatsApp (`wa.me` + `api.whatsapp.com`) est implémenté. Pas de QR code, pas de `navigator.share`.

### 4. Notification à l'ouverture pour SaleInterest
`SaleInterest` stocke phone + name. La tâche `send_sale_reminder` existe mais n'est pas connectée automatiquement aux `SaleInterest` — elle doit être appelée explicitement avec un `phone`. Il n'y a pas de beat schedule qui envoie automatiquement un rappel aux inscrits 1h avant l'ouverture.

### 5. Vocal client (commande)
Le bouton micro sur la page de commande utilise `SpeechRecognition` navigateur (transcription client-side uniquement). Le résultat est injecté dans le champ adresse et stocké en texte dans `Delivery.address_text`. Aucun audio client n'est stocké en base.

---

## Dépendances installées (`requirements.txt`)

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
celery (présent dans config/celery.py — vérifier requirements.txt)
```

---

## Tests existants

| App | État |
|-----|------|
| orders | ✅ Présent (delivery intégré) |
| delivery | ✅ Présent (dashboard tests) |
| analytics | Présent |
| payments | Présent |
| accounts | Présent |
| flash_sales | Présent |
| products | Présent |
| core | Présent |
| subscriptions | À compléter |
| notifications | À compléter |
| E2E | ❌ Absent |

---

## Prochaines priorités suggérées

1. **Connecter SaleInterest → send_sale_reminder** : beat schedule qui déclenche les rappels aux inscrits 1h avant `start_time`
2. **SubscriptionPayment dans l'admin** : enregistrer + filtres par status/provider
3. **Analytics par vente flash** : vue dédiée avec CA, commandes, stock par `flash_sale_id`
4. **Différencier MEDIUM vs PRO** dans l'UI analytics (actuellement identique)
5. **Admin plateforme custom** : page staff-only avec métriques globales
