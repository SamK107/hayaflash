# HayaFlash — État du Codebase

> Mis à jour le 2026-09-20. Basé sur audit direct du code source (pas sur les docs).
> **Ce fichier est la source de vérité sur ce qui EXISTE et ce qui RESTE À FAIRE.**
> Mettre à jour après chaque chantier significatif.
>
> Note : la révision précédente (09-09) affirmait trois choses fausses, découvertes
> en comparant ce fichier au code réel le 18/09 : le rappel automatique `SaleInterest`
> était déjà marqué "non automatisé" dans la structure alors que la section "Résolu"
> plus bas du même fichier le disait fait ; la migration `0010_saleinterest_reminded_at`
> était marquée "toujours pas appliquée" alors qu'elle l'était ; le Web Share API était
> listé en lacune alors qu'il est implémenté depuis PR #10 (13/09). Cette révision
> corrige ces trois écarts et ajoute Phase 8.1 (Orange Money) + les chantiers
> gouvernance/sauvegardes, absents du fichier jusqu'ici.

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
├── notifications/  ✅ Complet (rappel SaleInterest automatisé depuis le 09-09)
├── orders/         ✅ Complet
├── payments/       ✅ Mock complet (COD V1, activer en V1.1)
├── products/       ✅ Complet
├── subscriptions/  ✅ Complet (+ admin, platform_reporting, Orange Money Phase 8.1,
│                     fixes quota fail-closed/CANCELLED/expiry — mergés 18/09, PR #15)
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
- **Refactor 20/09 (PR "Publication rapide")** : `Product.flash_sale` (FK) supprimé.
  `Product` appartient maintenant au vendeur (`owner` FK vers `SellerProfile`, nullable
  pour les lignes orphelines historiques) et devient un catalogue réutilisable entre
  ventes. Le lien produit ↔ vente passe par un modèle through explicite,
  `FlashSaleProduct` (`flash_sale`, `product`, `promo_price` nullable, `display_order`,
  `is_active`, `unique_together`), exposé aussi via `FlashSale.products` (M2M through,
  `related_name="+"` pour ne pas casser les `sale.products.all()` existants). Migration
  en 3 temps (additive → data migration → suppression du FK legacy), testée sur copie
  de la DB réelle avant application (78/78 lignes migrées, 0 orphelin).
- `Product` : owner (FK `SellerProfile`, nullable), name, description, price,
  stock_initial, stock_available, unit, characteristics (JSONField),
  description_audio (FileField), display_order, is_active (masquage catalogue —
  voir Publication rapide ci-dessous)
- `FlashSaleProduct` : flash_sale (FK), product (FK), promo_price (nullable —
  fallback `product.price`), display_order, is_active ; propriétés `effective_price`
  et `is_available`
- `ProductMedia` : product (FK), media_type (image/video), file (ImageField), video_url, alt_text, order — une seule photo par produit dans la grille Publication rapide (upload remplace, n'empile plus)
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
- `SubscriptionPayment` : UUID PK, seller, plan, provider, amount, phone, status, order_id (≤24 chars), `notif_token` (unique, indexé — remplace `pay_token` depuis PR #15), txn_id, payment_url, raw_response, raw_callback, paid_at — **enregistré dans l'admin Django** (`SubscriptionPaymentAdmin`, filtres status/plan/provider)
- `WebhookLog` : audit trail des webhooks Orange Money reçus (notif_token, status, raw_payload, processed) — voir `docs/decisions/ADR-0001-strategie-sauvegardes.md` pour le contexte plus large sauvegardes
- `SubscriptionAdmin` + `SellerProfileAdmin` (accounts) : actions de simulation de plan (Gratuit perpétuel / Medium 90j / Pro 90j) sans paiement réel — PR #17
- `services/platform_reporting.py` : MRR, revenu YTD, timeline mensuelle, résumé remittance Orange, liste vendeurs abonnés — alimente `/platform-admin/`
- `services/limits.py` : `get_sale_quota()`/`can_create_flash_sale()` — **fail-closed sur exception** (`flash_sales.services.crud.can_seller_create_sale()` refuse plutôt que d'autoriser en illimité), `CANCELLED` exclu du comptage de quota (libère le slot), PRO/MEDIUM expiré retombe à FREE. **Attention** : ce fix a été écrit le 18/07 sur une branche (`feature/home-admin-seed`) jamais mergée à l'époque — il n'était **pas réellement actif sur `main` avant le 18/09** (PR #15), malgré ce que laissait penser la précédente révision de ce fichier. Tests dédiés en place (`subscriptions/tests.py`, `flash_sales/tests.py`).
- Orange Money WebPay (Phase 8.1, PR #15, 18/09) : `services/orange_money.py` (OAuth2 + WebPay client), `services/payment.py` (`create_orange_payment()`, `activate_subscription_from_payment()`), `billing_views.py` (URLs stables `/billing/return/`, `/billing/cancel/`, `/billing/webhook/orange/`, enregistrées chez Orange Money). Détail complet : `CLAUDE.md` § Orange Money Payment Integration, `subscriptions/README.md`.
- Paywall quota (`templates/flash_sales/quota_exceeded.html`) : lien vers `subscriptions:checkout` réparé le 17/09 (référençait une URL `subscriptions:upgrade` inexistante, `NoReverseMatch`/500 systématique) — voir PR mergée sur `feature/orange-money-payment-integration`.
- Providers : orange (implémenté) / moov / wave (UI présente, service non implémenté — message "disponible prochainement")

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
- `seed_demo` : **n'existe pas sur `main`**. Une version (juillet, `feature/home-admin-seed`) appelait `Product.objects.get_or_create(owner=...)` et `create_order(flash_sale=..., product=..., ...)` — deux signatures obsolètes (`Product` s'attache via `flash_sale`, pas `owner` ; `create_order()` prend un payload dict). Volontairement exclue lors de la récupération de cette branche (PR #17, 17/09) plutôt que rejouée telle quelle. `docs/DEMO_PLAN.md`, référencé par une précédente révision de ce fichier, n'existe pas non plus sur `main` pour la même raison.

### `config/`
- Settings multi-env : base, dev, staging, prod, test
- `celery.py` : app Celery + autodiscover ; `CELERY_BEAT_SCHEDULE` (dans `settings/base.py`) contient `auto-open-scheduled-sales`, `auto-close-live-sales` et, depuis le 09-09, `send-pending-sale-reminders` (300s)
- Docker : Dockerfile + docker-compose.yml (dev) + docker-compose.production.yml
- CI/CD : `.github/workflows/ci.yml` + `deploy.yml`

---

## Phase 7 — Terminée (vérifiée par audit code, 09/09)

| Fonctionnalité | Statut |
|---|---|
| QR Code partage vente (`analytics/services/qrcode.py`) | ✅ Fait |
| `Delivery.audio_note` (migration + capture + stockage) | ✅ Fait |
| Vue intérêts par vente `<pk>/interests/` | ✅ Fait |
| `analytics/services/reporting.py` + vue analytics MEDIUM/PRO | ✅ Fait |
| Admin plateforme `/platform-admin/` (staff only) | ✅ Fait |
| `SubscriptionPayment` dans l'admin Django | ✅ Fait |

---

## Phase 8 — Performance/SEO + Phase 8.1 Orange Money (18/09)

| Fonctionnalité | Statut |
|---|---|
| Vendoring CDN (Tailwind/HTMX/Alpine/Lucide/polices), lazy loading, sitemap/robots, CSP report-only, redimensionnement upload | ✅ Fait (PR #16, 14-17/09) |
| Orange Money WebPay (checkout, webhook idempotent, `notif_token`, `WebhookLog`) | ✅ Fait (PR #15, 18/09) — voir CLAUDE.md § Orange Money Payment Integration |
| Quota fail-closed + `CANCELLED` exclu + expiry → FREE | ✅ Fait (PR #15, 18/09 — récupéré d'une branche de juillet jamais mergée) |
| Paywall `quota_exceeded.html` (lien cassé réparé) + design aligné Tailwind | ✅ Fait (17/09) |
| Actions admin simulation de plan (accounts + subscriptions) + section marketing home | ✅ Fait (PR #17, 17/09) |
| Scripts sauvegarde DB/médias + test de restauration + copie hors-site | 🟡 Code prêt et testé en local, rien d'automatisé/exécuté en réel (PR #18/#19, 17-18/09) — voir `docs/decisions/ADR-0001-strategie-sauvegardes.md` |
| Healthcheck `/health/` vérifie DB + cache | 🟡 En revue (PR #20, 18/09) |
| Alerte admin sur webhook suspect / paiement FAILED | 🟡 En revue (PR #21, 18/09) |

---

## Phase 9 — Publication rapide (catalogue produits) (20/09)

| Fonctionnalité | Statut |
|---|---|
| Refactor `Product` en catalogue réutilisable par vendeur (`owner` + `FlashSaleProduct` through-model, remplace `Product.flash_sale`) | ✅ Fait — migration en 3 temps testée sur copie DB réelle |
| Page `/<flash_sale_pk>/quick-publish/` : grille Alpine.js/Tailwind pour publier/mettre à jour 20+ produits en une fois (prix promo, stock, ordre) | ✅ Fait |
| API DRF `FlashSaleProductViewSet` (`catalog`, `bulk-update` transactionnel tout-ou-rien, `duplicate-from`, `bulk-upload-images`, `assign-image`, `archive-product`, `delete-product`) | ✅ Fait |
| Upload photo groupé : rattachement auto par nom de fichier normalisé (espaces/`_`/`-` équivalents), puis par ordre de dépôt sur les lignes sans photo, puis création automatique d'une nouvelle ligne (photo déjà en place) si aucune correspondance | ✅ Fait |
| Masquer/réafficher un produit catalogue (`is_active`, sans le supprimer) et suppression définitive (protégée par `on_delete=PROTECT` sur `Order`/`OrderItem.product` — refusée avec message explicite si le produit a déjà des commandes) | ✅ Fait |
| Mode support (`/admin/sellers/<seller_id>/<flash_sale_pk>/quick-publish/`, staff only, `?seller_id=` impersonation) | ✅ Fait |
| Non-régression checkout : `price_snapshot` utilise `FlashSaleProduct.effective_price` (prix promo), pas le prix catalogue brut | ✅ Fait — testé |
| `flash_sales.services.crud.clone_flash_sale` : réutilise le catalogue existant au lieu de dupliquer `Product`/`ProductMedia` | ✅ Fait |

---

## Phase 10 — Audit fonctionnel, pages acheteur, PWA multi-boutiques & conversion (à venir)

Cadré le 22/09 avant la configuration du déploiement VPS automatique (voir
`GOVERNANCE_SECURITE.md` § 6). Objectif : fiabiliser et optimiser l'expérience
avant d'ouvrir le déploiement continu, pas ajouter du périmètre non maîtrisé.

### 10.0 — Audit fonctionnel navigateur (pré-requis, en cours)

Audit Playwright en deux sessions (21 et 22/09), rapport détaillé :
`Claude outputs/AUDIT_10.0_rapport_suite.md` (dossier local, ignoré par git).

| Parcours | Statut |
|---|---|
| Vendeur : connexion, création vente, ouverture, Publication Rapide (avec upload photo) | ✅ Testé (22/09) |
| Acheteur : page vente publique, commande, confirmation | ✅ Testé après correctif (22/09) |
| Acheteur : paiement Orange Money réel (abonnement vendeur) | 🟡 Redirection vers la page de paiement Orange confirmée (23/09) — reste à valider paiement → webhook → `WebhookLog` → activation du plan, et le chemin annulation |
| Vendeur : dashboard livraison | ✅ Testé (commande visible, 22/09) |
| Vendeur : paramètres, abonnement | 🟡 Partiel — lien "Passer Pro" corrigé (22/09), parcours complet non rejoué |
| Admin plateforme (staff) + `/admin/` Django | ✅ Testé (22/09) |
| Mode support (`quick-publish` en impersonation staff) | 📋 Non testé en navigateur (couvert par tests unitaires) |

**Bugs trouvés et corrigés :**

| # | Bug | Gravité | Correctif |
|---|---|---|---|
| 1 | Formulaire de commande `/order/` sans `action` → POST sur une vue `@require_GET` → **405 pour 100 % des acheteurs** (invisible en tests unitaires, qui passaient par l'API) | Critique | `clientOrderForm()` (Alpine, `static/js/hf-components.js`) appelle `POST /api/v1/orders/` — commit `fbc171a` (23/09) |
| 2 | "Ouvrir la vente" en avance : statut LIVE affiché mais `is_live()` (basé sur `start_time`/`end_time`) refusait les commandes, message d'erreur technique en anglais | Critique | `open_sale()` avance `start_time` à maintenant en conservant la durée prévue — commit `fbc171a` |
| 3 | `/seller/` en 500 pour un compte staff sans `SellerProfile` | Majeur | Redirection vers `/platform-admin/` — commit `fbc171a` |
| 4 | Ventes programmées du calendrier public `/ventes/` sans lien (carte non cliquable) | Mineur | Carte liée à `/f/<slug>/` (gère l'état programmé + bouton "M'alerter") + test `PublicCalendarScheduledLinkTest` — 23/09 |
| 5 | Lien "Passer Pro" (paramètres) vers une mauvaise page | Mineur | commit `01550e0` (22/09) |

**Restant / en attente :**
- Accents manquants dans l'UI (`Debut`, `Programmee`…) — commit dédié séparé.
- Décision produit : la boutique `/s/<slug>/` n'affiche que les ventes live, pas les programmées.
- Test Orange Money bout en bout (voir tableau ci-dessus) — en production, argent réel.

Leçon : les tests unitaires (API/services) ne voient pas les bugs de câblage
HTML/JS. Garder ce format d'audit navigateur avant chaque activation du
déploiement continu.

### 10.1 — Optimisation pages acheteur (dépend de 10.0)

| Piste identifiée | Statut |
|---|---|
| Stock restant plus visible (compte à rebours, jauge) | 📋 À faire — attend les constats de 10.0 |
| Preuve sociale live (`SaleInterest` déjà en base — "X personnes intéressées") | 📋 À faire |
| Tunnel de commande raccourci (friction minimale avant nom/téléphone) | 📋 À faire |

### 10.2 — PWA acheteur multi-boutiques + notifications (à venir)

| Fonctionnalité | Statut |
|---|---|
| Bug à corriger : manifest unique (`start_url: /seller/`) partagé par les pages acheteur — une installation depuis une vente ouvre l'espace vendeur | 📋 À faire |
| Manifest acheteur séparé (icône/nom propres), scope dédié aux routes publiques, `start_url` vers un tableau de bord découverte | 📋 À faire |
| Champs structurés `pays`/`ville` (remplace le texte libre `delivery_zone`) pour permettre le filtrage géographique | 📋 À faire |
| Dashboard "Découvrir" : boutiques avec vente programmée/en cours uniquement, filtrées par ville, extensible pays plus tard (expansion Afrique de l'Ouest) | 📋 À faire |
| Notifications push (Web Push, clés VAPID, nouveau canal `push` dans `notifications/services/`, réutilise le pattern `send_pending_sale_reminders`) | 📋 À faire — nécessite l'installation PWA acheteur fonctionnelle (iOS : push impossible hors app installée) |
| Bandeau d'installation iOS (pas de `beforeinstallprompt` sur Safari — instructions manuelles "Ajouter à l'écran d'accueil") | 📋 À faire |

### 10.3 — Scarcité & conversion (à venir)

Principe décidé le 23/09 : la rareté de base est **active par défaut pour tous
les vendeurs** (c'est l'essence d'une vente flash) ; seul le quota strict est
une **option activée par le vendeur**.

| Fonctionnalité | Activation | Statut |
|---|---|---|
| Rareté temporelle (compte à rebours), stock réel affiché, preuve sociale live | Par défaut, pour tous — pas d'option | 📋 À faire — voir 10.1 |
| Quota de places strict (pertinent billetterie/événementiel) | **Option vendeur**, désactivée par défaut | 📋 À faire (post-audit) |

### 10.4 — Billetterie & confirmation de livraison par QR (optionnel, post-lancement)

Principe décidé le 23/09 : les deux fonctionnalités sont des **options au choix
du vendeur**, jamais imposées. Non bloquantes pour le lancement.

| Fonctionnalité | Activation | Statut |
|---|---|---|
| QR de confirmation livraison (paiement sur place) : jeton signé (`django.core.signing`) à usage unique, scan caméra navigateur (`getUserMedia` + `jsQR`) dans l'app vendeur déjà installée, lié à `Delivery` (UUID déjà en place) | **Option vendeur** (réglage boutique ou par vente), désactivée par défaut | 📋 À faire — non bloquant pour le lancement |
| Billetterie événementielle : module distinct (contrôle d'accès, pas logistique), quota strict pertinent ici | **Choix du vendeur à la création** : type de vente « Vente classique » / « Événement » (pas une simple case à cocher) | 📋 À faire — non bloquant, piste d'extension produit |

---


## Ce qui n'existe PAS (lacunes résiduelles réelles)

### 1. F3 "Sales Drawer" — statut à reconfirmer
Le code contient déjà un composant "drawer" (bottom-sheet Alpine.js `orderDrawer` +
`interest-drawer-w`/`interest-drawer-end`) dans `templates/analytics/flash_sale_public.html`,
antérieur à la note "zéro code" du 18/07. Voir `docs/PROJECT_SPEC.md` — reste à confirmer
avec le product owner si c'est bien ce que désignait le label externe "F3 Sales Drawer".

### 2. Démo — `seed_demo` et flag `is_demo`
`seed_demo`, reset automatisé hebdomadaire, badge "DÉMO" visible sur `SellerProfile` :
non implémentés. `docs/DEMO_PLAN.md` (qui les décrivait comme facultatifs) a été retiré
du dépôt (voir § `core/`) — à recréer si un usage showroom partenaires est décidé.

### 3. Passage de la CSP en mode bloquant
`CSP_REPORT_ONLY = True` depuis le 14/09 — décision produit à prendre après vérification
sans violation sur staging et traitement des `onclick=`/`<script>` inline restants.

### 4. Chiffrement des sauvegardes hors-site
Décidé (GPG/age, voir ADR-0001) mais pas implémenté : `infra/scripts/copy_offsite.sh`
copie en clair pour l'instant.

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
| products | ✅ Renforcé — `products/tests_quick_publish.py` (46 tests : modèles, API bulk-update/catalog/duplicate/upload/archive/delete, mode admin, non-régression checkout) |
| core | Présent |
| subscriptions | ✅ Renforcé (fail-closed, CANCELLED, expiry, webhooks Orange Money — merge effectif 18/09) |
| notifications | À compléter |
| E2E | ❌ Absent |

> Suite complète relancée le 23/09 sur `main` après les correctifs Phase 10.0
> (`manage.py test --settings=config.settings.test`) : **173 tests, OK (3 skipped)**
> — 174 attendus avec `PublicCalendarScheduledLinkTest`. (Le 20/09 : 169 tests au total.)
> Couverture non remesurée (`--cov-fail-under=60` dans la CI, pas de rapport détaillé
> regénéré pour ce fichier).

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
| Tree-shaking Lucide (356 Ko → ~15-20 Ko estimé, ~67 icônes utilisées sur les ~1500 de la lib) | ❌ Pas fait — nécessite de pouvoir tester visuellement en live |
| Migration `flash_sales/0010_saleinterest_reminded_at` | ✅ Appliquée (confirmé `showmigrations` le 18/09) |
| Suite de tests relancée | ✅ Relancée le 18/09 — 118 passed, 3 skipped |

---

## Prochaines priorités suggérées

Recoupé avec `GOVERNANCE_SECURITE.md` § Synthèse des priorités (plus détaillé sur la partie sécurité/infra) :

1. **Brancher le disque externe sur le VPS** et lancer une première exécution réelle de `infra/scripts/backup.sh` → `copy_offsite.sh` → `restore_test.sh` (voir ADR-0001) — rien de tout ça n'a encore tourné en conditions réelles.
2. **Chiffrer les sauvegardes hors-site** (`copy_offsite.sh` copie en clair aujourd'hui).
3. **Retirer `if: false`** sur `deploy-staging`/`deploy-prod` (`.github/workflows/deploy.yml`) une fois le VPS prêt.
4. **Durcissement VPS** (fail2ban, ufw, SSH par clé) — à vérifier par SSH dès qu'un accès est disponible (`GOVERNANCE_SECURITE.md` catégorie 7).
5. **Décider du passage de la CSP en mode bloquant** (`CSP_REPORT_ONLY = False`) après vérification sans violation sur staging.
6. **Clarifier F3 "Sales Drawer"** avec le product owner en montrant le code existant (`orderDrawer` dans `flash_sale_public.html`) : confirme-t-il le label, ou s'agit-il d'autre chose ?
7. **Décider du sort des items démo** (`seed_demo` à réécrire pour le schéma actuel, `is_demo`, reset auto, badge DÉMO) si un usage showroom partenaires est prévu.
8. **Audit fonctionnel navigateur** (Phase 10.0, ci-dessus) avant d'activer le
   déploiement continu — corriger ce qui est cassé pendant que `deploy-staging`/
   `deploy-prod` sont encore en pause plutôt qu'après.
9. **PWA acheteur** (Phase 10.2) : corriger le bug de manifest partagé
   (`start_url: /seller/` hérité par les pages acheteur) avant toute
   communication invitant les clients à installer l'app.
