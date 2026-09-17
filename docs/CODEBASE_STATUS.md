# HayaFlash — État du Codebase

> Mis à jour le 2026-09-09. Basé sur audit direct du code source (pas sur les docs).
> **Ce fichier est la source de vérité sur ce qui EXISTE et ce qui RESTE À FAIRE.**
> Mettre à jour après chaque chantier significatif.
>
> Note : la version précédente (13/07) listait la Phase 7 comme "à faire" alors que le
> code avait déjà été livré. Cette révision corrige l'écart après audit direct
> (urls.py, views.py, models.py, admin.py, settings de chaque app concernée).

---

## Structure actuelle

```
hayaflash/
├── accounts/       ✅ Complet
├── analytics/      ✅ Complet (+ QR code, reporting)
├── config/         ✅ Complet
├── core/           ✅ Complet (+ platform-admin)
├── delivery/       ✅ Complet (+ audio_note câblé)
├── flash_sales/    ✅ Complet (+ interests, analytics)
├── notifications/  ✅ Complet (rappel SaleInterest non automatisé — voir lacunes)
├── orders/         ✅ Complet
├── payments/       ✅ Mock complet (COD V1, activer en V1.1)
├── products/       ✅ Complet
├── subscriptions/  ✅ Complet (+ admin, platform_reporting, fixes quota 18/07)
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
- Celery tasks : `auto_open_scheduled_sales` + `auto_close_live_sales` (beat schedule 60s) + `send_pending_sale_reminders` (beat schedule 300s — **ajoutée le 09-09**, relance les `SaleInterest` non notifiés dont la vente ouvre dans l'heure)
- CRUD vendeur complet : list, create, edit, detail, open, close, cancel, clone
- Vue `sale_interests_view` (liste globale) + `flash_sale_interests_detail_view` (par vente) + `sale_interests_reset_view` — urls `interests/`, `<pk>/interests/`, `<pk>/interests/reset/`
- Vue `seller_analytics_view` : dashboard analytics MEDIUM (30j)/PRO (annuel + top produits), gate sur `sub.has_stats`

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
- `Delivery` : order (OneToOne), address_text, latitude, longitude, geo_accuracy, geo_method, delivery_notes, `audio_note` (FileField WebM/OGG), status, assigned_to, cod_amount, cod_collected, cod_collected_at, cod_confirmed_by
- `Delivery.GeoMethod` : gps / manual / timeout / denied
- `create_delivery_for_order()` décode un `audio_base64` envoyé par le client et l'attache via `_attach_audio_note()` (best-effort, ne bloque jamais la commande si le décodage échoue) — **l'audio client est bien stocké en base**, pas seulement transcrit en texte
- Dashboard livraisons HTMX vendeur (`/orders/seller/deliveries/`), `advance_delivery()` gère confirm/start_delivery/mark_delivered/mark_failed avec transitions verrouillées (`select_for_update`)
- Méthodes : `get_maps_url()`, `get_waze_url()`

### `subscriptions/`
- `Plan` (TextChoices) : `free / medium / pro`
- Prix : FREE=0 FCFA, MEDIUM=2 000 FCFA, PRO=5 000 FCFA
- Limites ventes/mois : FREE=3, MEDIUM=3, PRO=None (illimité)
- `Subscription` : seller (OneToOne), plan, expires_at
- `SubscriptionPayment` : UUID PK, seller, plan, provider, amount, phone, status, order_id, pay_token, txn_id, payment_url, raw_response, raw_callback, paid_at — **enregistré dans l'admin Django** (`SubscriptionPaymentAdmin`, filtres status/plan/provider)
- `SubscriptionAdmin` : actions de simulation de plan (Gratuit perpétuel / Medium 90j / Pro 90j) sans paiement réel
- `services/platform_reporting.py` : MRR, revenu YTD, timeline mensuelle, résumé remittance Orange, liste vendeurs abonnés — alimente `/platform-admin/`
- `services/limits.py` : fail-closed sur exception quota (refuse plutôt que d'autoriser en illimité), `CANCELLED` exclu du comptage de quota (libère le slot), PRO expiré retombe à FREE (audit du 18/07, tests dédiés en place)
- Providers : orange / moov / wave — service Orange Money dans `subscriptions/services/orange_money.py`
- Vues billing : checkout, payment_pending, subscription dashboard

### `notifications/`
- `Notification` : recipient_phone, channel (whatsapp/sms/email), message, status (pending/sent/failed), error_message, sent_at
- Services : `dispatcher.py`, `sms.py`, `whatsapp.py`
- Celery tasks : `send_order_confirmation` (déclenchée à création commande), `send_sale_reminder(flash_sale_id, phone)` (rappel 1h avant vente) — **appelée automatiquement depuis le 09-09** par `flash_sales.send_pending_sale_reminders` (beat 300s)

### `analytics/`
- `ShareLink` : token (unique 10 chars), link_type (seller/flash_sale/product), seller, flash_sale, product, target_key, click_count, share_count, conversion_count
- `ShareEvent` : share_link, event_type (page_view/click/whatsapp_share/conversion), source, order (FK nullable)
- Services : share_links, share_tracking, view_tracking, conversion_tracking, public_pages, seo (OG + JSON-LD), abuse (anti-spam), **`qrcode.py`** (génère un QR en base64 pour une vente), **`reporting.py`** (timelines de revenu 30j/mensuel, top produits)
- `get_seller_public_stats()` : total_orders + products_sold (agrégé, mis en cache)
- Pages publiques : `/s/<slug>/` (vendeur), `/f/<slug>/` (vente flash), `/f/<slug>/qrcode/` (JSON, auth vendeur), redirect WhatsApp tracké
- `flash_sale_interest` : endpoint POST JSON qui crée un `SaleInterest`

### `payments/`
- `PaymentTransaction` (UUID PK) + `LedgerEntry`
- Mock provider en place
- En veille pour V1 (COD actif) — ne pas supprimer, sera activé en V1.1

### `core/`
- `platform_admin_dashboard` (`@staff_member_required`, url `/platform-admin/`) : total vendeurs actifs, abonnements par plan, ventes live, commandes du mois, MRR, revenu total, revenu YTD, timeline, résumé Orange, vendeurs abonnés, 20 derniers paiements
- `seed_demo` (management command) : 4 boutiques de démo (FREE/MEDIUM/PRO/PRO), voir `docs/DEMO_PLAN.md`

### `config/`
- Settings multi-env : base, dev, staging, prod, test
- `celery.py` : app Celery + autodiscover ; `CELERY_BEAT_SCHEDULE` (dans `settings/base.py`) contient `auto-open-scheduled-sales`, `auto-close-live-sales` et, depuis le 09-09, `send-pending-sale-reminders` (300s)
- Docker : Dockerfile + docker-compose.yml (dev) + docker-compose.production.yml
- CI/CD : `.github/workflows/ci.yml` + `deploy.yml`

---

## Phase 7 — Terminée (vérifiée par audit code, 09/09)

Workflow détaillé : `docs/PHASE7_WORKFLOW.md`

| Fonctionnalité | Statut |
|---|---|
| QR Code partage vente (`analytics/services/qrcode.py`) | ✅ Fait |
| `Delivery.audio_note` (migration + capture + stockage) | ✅ Fait |
| Vue intérêts par vente `<pk>/interests/` | ✅ Fait |
| `analytics/services/reporting.py` + vue analytics MEDIUM/PRO | ✅ Fait |
| Admin plateforme `/platform-admin/` (staff only) | ✅ Fait |
| `SubscriptionPayment` dans l'admin Django | ✅ Fait |

---

## Ce qui n'existe PAS (lacunes résiduelles réelles)

### 1. Web Share API
Le partage est WhatsApp (`wa.me` + `api.whatsapp.com`) + QR code. Pas de `navigator.share()` détecté dans les vues/services examinés (templates non audités en détail — à vérifier si besoin).

### 2. F3 "Sales Drawer" — statut à reconfirmer
Le code contient déjà un composant "drawer" (bottom-sheet Alpine.js `orderDrawer` +
`interest-drawer-w`/`interest-drawer-end`) dans `templates/analytics/flash_sale_public.html`,
antérieur à la note "zéro code" du 18/07. Voir `docs/PROJECT_SPEC.md` — reste à confirmer
avec le product owner si c'est bien ce que désignait le label externe "F3 Sales Drawer".

### 3. Démo — items marqués optionnels dans `DEMO_PLAN.md`
Flag `is_demo` sur `SellerProfile`, reset automatisé hebdomadaire, badge "DÉMO" visible : non vérifiés dans le code, marqués facultatifs à la création du plan (14/07).

## Résolu depuis la dernière révision (09-09)

### Rappel automatique aux inscrits (`SaleInterest`)
Ajouté : champ `SaleInterest.reminded_at` (migration `flash_sales/0010_saleinterest_reminded_at.py`),
tâche `flash_sales.send_pending_sale_reminders` (toutes les 5 min, dans `CELERY_BEAT_SCHEDULE`)
qui trouve les inscrits non relancés dont la vente `SCHEDULED` ouvre dans l'heure, appelle
`notifications.send_sale_reminder` et marque `reminded_at` pour éviter les doublons.
**Migration non appliquée automatiquement** — lancer `python manage.py migrate` après déploiement.

---

## Dépendances installées (`requirements.txt`)

```
Django==5.2.13
djangorestframework==3.16.1
django-redis==5.4.0
django-cors-headers==4.9.0
django-htmx==1.27.0
celery==5.4.0
redis==5.2.1
django-celery-beat>=2.8.0
qrcode==8.2
argon2-cffi==23.1.0
sentry-sdk[django]==2.28.0
django-debug-toolbar==5.2.0
gunicorn==25.3.0
psycopg2-binary==2.9.11
python-dotenv==1.2.2
whitenoise==6.12.0
Brotli==1.1.0            # ajouté 14/09 — précompression Brotli par WhiteNoise en plus de gzip
django-csp==3.8          # ajouté 14/09 — Content-Security-Policy (Report-Only, voir § Performance & SEO)
pillow==12.2.0
dj-database-url==2.3.0
requests==2.33.1
```

---

## Tests existants

| App | État |
|-----|------|
| orders | ✅ Présent (delivery intégré) |
| delivery | ✅ Présent (dashboard tests) |
| analytics | ✅ Présent |
| payments | Présent |
| accounts | Présent |
| flash_sales | Présent |
| products | Présent |
| core | Présent |
| subscriptions | ✅ Renforcé (audit 18/07 : fail-closed, CANCELLED, expiry — +35 tests) |
| notifications | À compléter |
| E2E | ❌ Absent |

> Suite complète au 18/07 : 103 passed, 3 skipped (~77% couverture). Non ré-exécutée lors de cet audit (accès shell direct au dépôt indisponible) — à relancer pour confirmer l'état actuel.

---

## Performance & SEO (chantier ouvert le 13/09, exécuté le 14/09)

Contexte complet : `docs/AUDIT_PERFORMANCE_SEO.md`. Détail de maintenance du
build front : `docs/FRONTEND_VENDORING.md`.

| Action | État |
|---|---|
| Vendoring Tailwind (build CLI purgé, remplace `cdn.tailwindcss.com`), HTMX 2.0.0, Alpine 3.14.9 (version figée), Lucide 0.462.0 (version figée, remplace `@latest`) | ✅ Fait (14/09) — `static/vendor/`, référencé dans `templates/base.html` |
| Auto-hébergement des polices Inter (`base.html`) et Poppins (`core/home.html`), suppression de `fonts.googleapis.com` | ✅ Fait (14/09) — `static/fonts/` |
| `loading="lazy"`/`decoding="async"` sur les images produits below-the-fold, `fetchpriority="high"` sur les covers above-the-fold | ✅ Fait (14/09) — `flash_sale_public.html`, `public_detail.html`, `public_calendar.html`, `client_order.html`, `detail.html`, `_sale_list_section.html`, `seller/home.html` |
| Redimensionnement automatique des images à l'upload (max 1600px, best-effort) | ✅ Fait (14/09) — `core/services/image_optimize.py`, câblé dans `FlashSale.save()` et `ProductMedia.save()` |
| `robots.txt` + `sitemap.xml` (home, `/ventes/`, ventes live/programmées, vendeurs actifs) | ✅ Fait (14/09) — `core/sitemaps.py`, routes dans `config/urls.py` |
| `<link rel="canonical">` sur `/ventes/<slug>/` vers `/f/<slug>/` (duplication de contenu — voir `CLAUDE.md` point 14) | ✅ Fait (14/09) |
| Brotli (en plus de gzip) sur WhiteNoise | ✅ Fait (14/09) — `Brotli` dans `requirements.txt`, activation automatique par WhiteNoise |
| Content-Security-Policy | 🟡 Fait en **Report-Only** (14/09) — `CSP_REPORT_ONLY = True` dans `config/settings/base.py`. Ne bloque rien. Passage en mode bloquant = décision à prendre après vérification sans violation sur staging (console navigateur), et après avoir traité les `onclick=`/`<script>` inline qui nécessitent aujourd'hui `'unsafe-inline'`. |
| Tree-shaking Lucide (356 Ko → ~15-20 Ko estimé, ~67 icônes utilisées sur les ~1500 de la lib) | ❌ Pas fait — nécessite de pouvoir tester visuellement en live (accès shell machine indisponible le 14/09, cf. bug Windows connu côté pont Claude) |
| Migration `flash_sales/0010_saleinterest_reminded_at` | ❌ **Toujours pas appliquée** — nécessite `python manage.py migrate` en local (non exécutable à distance actuellement) |
| Suite de tests relancée | ❌ **Toujours pas relancée** depuis le 18/07 — même contrainte d'accès |

---

## Prochaines priorités suggérées

1. **Appliquer la migration `flash_sales/0010_saleinterest_reminded_at`** (`python manage.py migrate`) pour activer le rappel automatique ajouté le 09-09 — **et relancer `pytest --ds=config.settings.test`** pour confirmer l'état de couverture actuel (dernière mesure connue : 18/07) avant tout déploiement
2. **Retirer `if: false`** sur `deploy-staging`/`deploy-prod` (`.github/workflows/deploy.yml`) une fois le VPS prêt
3. **Décider du passage de la CSP en mode bloquant** (`CSP_REPORT_ONLY = False`) après vérification sans violation sur staging
4. **Clarifier F3 "Sales Drawer"** avec le product owner en montrant le code existant (`orderDrawer` dans `flash_sale_public.html`) : confirme-t-il le label, ou s'agit-il d'autre chose ?
5. **Web Share API** sur les pages publiques (`/f/<slug>/`, `/s/<slug>/`) si voulu en complément du QR code/WhatsApp
5. **Décider du sort des items démo optionnels** (`is_demo`, reset auto, badge DÉMO) si un usage showroom partenaires est prévu
