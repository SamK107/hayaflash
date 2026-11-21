# Contexte technique HayaFlash → démarrage de « Dowba »

> Généré le 2026-11-17 par lecture seule du dépôt (branche `feat/seed-demo-distrib-v2`).
> Aucune valeur secrète n'est reproduite : seuls les **noms** de variables figurent ici (`<REDACTED>`).
> « Non trouvé » = information absente du code/des docs lus. Le fichier `.env` local n'a pas été ouvert.

---

## 1. Environnement local

| Élément | Constat |
|---|---|
| OS de dev | Windows 11 Pro (Git Bash + PowerShell). Prod : Linux (conteneurs Docker sur un VPS) |
| Python | **3.11.9** dans le `.venv` local ; **3.12** dans le Dockerfile et la CI (écart à corriger pour Dowba : choisir une seule version) |
| Django | **5.2.17** (`requirements.txt`, épinglé) · DRF 3.17.2 · Celery 5.4.0 |
| Base de données | Dev : **SQLite** (`db_dev.sqlite3`). Staging/prod/CI : **PostgreSQL 16** (`postgres:16-alpine`) |
| Node | **Non utilisé** (aucun `package.json`). Le CSS Tailwind est un build statique vendorisé (voir §5) |
| Redis | Optionnel en dev (LocMemCache sinon) ; requis en prod (cache + broker Celery), `redis:7-alpine` |
| Installation | `venv` + `pip install -r requirements.txt` (dev : `requirements-dev.txt` = pytest, pytest-django, pytest-cov, pip-audit, bandit). Pas de Poetry |
| Port dev | `8000` (runserver), `8443` (HTTPS mkcert via `runserver_https`), `5433` (Postgres compose dev), `6379` (Redis) |
| Ports prod | Nginx du conteneur publié sur `8020` (staging) / `8021` (prod), derrière le proxy hôte |

Commandes utiles (issues de `CLAUDE.md`, `pytest.ini`, CI) :

```bash
python manage.py runserver --settings=config.settings.dev
python manage.py runserver_https --settings=config.settings.dev     # PWA sur téléphone
python manage.py migrate
python manage.py createsuperuser                                     # identifiant = téléphone
pytest --ds=config.settings.test                                     # tests (SQLite)
pytest --ds=config.settings.test_pg --cov=. --cov-fail-under=60      # comme la CI (PostgreSQL)
python manage.py check && python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput                             # WhiteNoise
celery -A config worker -l info -Q default,flash_sales,notifications
celery -A config beat -l info                                        # prod : --scheduler django_celery_beat.schedulers:DatabaseScheduler
docker-compose up                                                    # dev (web+db+redis+worker)
```

---

## 2. Structure du projet

### Arborescence (2 niveaux, hors `.venv`, `staticfiles`, caches)

```
hayaflash/
├── config/            settings/ (base, dev, staging, prod, test, test_pg, _csp, _orange, _sentry), urls, api_urls, celery, db_router, wsgi/asgi, gunicorn_logging
├── accounts/          services/ (otp, sms, auth, users, passwords, seller_codes, slugs), backends.py, access.py
├── analytics/         services/ (qrcode, reporting, public_pages), pages publiques SEO
├── assist/            saisie assistée (staff)
├── core/              middleware, context_processors, services/ (image_optimize, rate_limit, client_ip, axes_hooks), AuditLog
├── delivery/  distrib/  flash_sales/  notifications/  orders/  partners/  payments/  products/  subscriptions/
├── templates/  static/ (vendor, fonts, js, img, manifest*.json, sw.js)  media/  staticfiles/
├── infra/             nginx/, cron/, scripts/ (deploy_vps.sh, backup.sh, restore*.sh, smoke_test.sh, check_stack_isolation.sh…)
├── docs/              specs/, releases/, decisions/, runbooks…
├── scripts/           release_check.py, demo_captures.py, build_deck.py
├── Dockerfile  docker-compose.yml  docker-compose.production.yml  .github/workflows/
└── pytest.ini  .coveragerc  .env.example  CLAUDE.md  GOVERNANCE_*.md
```

### Settings

Découpés : `config/settings/base.py` (commun) + `dev.py` / `staging.py` / `prod.py` / `test.py` / `test_pg.py`. Sélection via `DJANGO_SETTINGS_MODULE`
(défaut Dockerfile : `config.settings.prod`). Variables lues avec **`python-dotenv`** (`load_dotenv(BASE_DIR/".env", override=False)`) puis
`os.environ` ; helper `require_env()` qui lève `ImproperlyConfigured` en staging/prod (ex. `SECRET_KEY`). Pas de `django-environ`.
Sous-modules : `_orange.py` (réglages Orange, double préfixe), `_csp.py` (CSP), `_sentry.py` (Sentry + masquage PII).

### Variables d'environnement (noms uniquement)

| Variable | Rôle |
|---|---|
| `ENVIRONMENT` (alias `ENV`) | dev / staging / prod |
| `DJANGO_SETTINGS_MODULE` | module de settings |
| `SECRET_KEY` = `<REDACTED>` | clé Django (obligatoire staging/prod) |
| `DEBUG`, `ALLOWED_HOSTS`, `SECURE_SSL_REDIRECT`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS` | sécurité/hôtes |
| `DATABASE_URL` (prioritaire, dj-database-url) ou `DB_NAME`, `DB_USER`, `DB_PASSWORD`=`<REDACTED>`, `DB_HOST`, `DB_PORT`, `DB_CONN_MAX_AGE` ; `DEV_SQLITE_NAME` | base de données |
| `REDIS_URL`, `REDIS_PASSWORD`=`<REDACTED>` | cache + broker/backend Celery |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | overrides Celery (défaut `REDIS_URL`) |
| `STATIC_URL`, `STATIC_ROOT`, `MEDIA_URL`, `MEDIA_ROOT` | fichiers statiques/médias |
| `HAYAFLASH_PUBLIC_BASE_URL` | base des liens de partage |
| `ORANGE_ML_CLIENT_ID`, `ORANGE_ML_CLIENT_SECRET`, `ORANGE_ML_MERCHANT_KEY` = `<REDACTED>` | identifiants Orange Money WebPay |
| `ORANGE_ML_BASE_URL`, `ORANGE_ML_RETURN_URL`, `ORANGE_ML_CANCEL_URL`, `ORANGE_ML_NOTIFY_URL`, `ORANGE_ML_TIMEOUT`, `ORANGE_ML_CURRENCY` | URLs publiques/callbacks, timeout (1–120 s, défaut 20), devise (défaut XOF). Chaque nom accepte aussi le préfixe `ORANGE_MONEY_*` (`ORANGE_ML_*` prioritaire) |
| `PAYMENTS_WEBHOOK_SECRET`=`<REDACTED>`, `PAYMENTS_MOCK_SIMULATE_FAILURE` | app `payments` (fournisseur mock, HMAC) |
| `SMS_NOTIFICATIONS_ENABLED`, `ORANGE_SMS_API_KEY`=`<REDACTED>`, `ORANGE_SMS_BASE_URL` | SMS Orange (inactif par défaut) |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_SSL`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`=`<REDACTED>`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL`, `EMAIL_TIMEOUT` | SMTP (console par défaut) |
| `SENTRY_DSN`=`<REDACTED>`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE` | monitoring |
| `CSP_REPORT_URI`, `CSP_REPORT_ONLY` | Content-Security-Policy |
| `HEALTH_CELERY_MAX_AGE`, `HEALTH_CELERY_REQUIRED` | healthcheck Celery |
| `HAYAFLASH_PROJECT`, `HAYAFLASH_HTTP_PORT`, `DOCKER_IMAGE`, `IMAGE_TAG` | isolation staging/prod sur un même VPS |
| `HAYAFLASH_ALLOW_DEMO_SEED`, `HAYAFLASH_NOINDEX`, `HF_REAL_IP_FROM`, `APP_RELEASE` | garde-fous démo/SEO/proxy/version de cache |
| `HAYAFLASH_PROMO_DISPLAY`, `DISTRIB_ENABLED` | interrupteurs fonctionnels |
| `LEGAL_ENTITY_*`, `LEGAL_HOST_*`, `LEGAL_JURISDICTION` | mentions légales |
| `BACKUP_ROOT`, `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY`, `BACKUP_REMOTE`, `PROD_DOMAIN` | sauvegardes/déploiement |
| `TEST_PG_HOST/NAME/USER/PASSWORD/PORT` | tests PostgreSQL |

### Apps Django

| App | Rôle |
|---|---|
| `accounts` | `User` (téléphone) + `SellerProfile`, OTP, backends d'auth, `seller_required` |
| `analytics` | ShareLink/ShareEvent, QR code, reporting MEDIUM/PRO, pages publiques SEO |
| `assist` | saisie assistée de ventes par l'équipe (staff) |
| `core` | accueil, AuditLog, dashboard `/platform-admin/`, middlewares, utilitaires (images, rate limit, IP) |
| `delivery` | livraisons (GPS, COD, note vocale) |
| `distrib` | module grossistes/revendeurs (relevés, paiements OM saisis à la main), interrupteur `DISTRIB_ENABLED` |
| `flash_sales` | ventes flash, CRUD vendeur, tâches d'ouverture/fermeture/rappels |
| `notifications` | notifications WhatsApp (lien `wa.me`) / SMS |
| `orders` | commandes (`create_order()` idempotent), dashboard LIVE HTMX |
| `partners` | programme partenaires (liens, commissions) |
| `payments` | transactions/ledger COD V1 + fournisseur mock (distinct des abonnements) |
| `products` | produits, médias, variantes, mouvements de stock |
| `subscriptions` | plans FREE/MEDIUM/PRO, **paiement Orange Money**, tarifs spéciaux |

---

## 3. Utilisateurs et authentification

- **Modèle custom** `accounts.User` (`AbstractBaseUser` + `PermissionsMixin`), `AUTH_USER_MODEL = "accounts.User"`.
  Champs : `phone` (unique, max 16, validateur E.164, **`USERNAME_FIELD`**), `email` (facultatif), `display_name`, `is_active`, `is_staff`, `is_phone_verified`, `date_joined`, `updated_at`.
  `REQUIRED_FIELDS = ["display_name"]`. Normalisation : `UserManager.normalize_phone` (strip + suppression des espaces).
- **Connexion par téléphone + mot de passe** (backend `accounts.backends.PhoneAuthBackend`). **OTP** SMS 6 chiffres existe
  (`accounts/services/otp.py` : 300 s, 5 essais, verrouillage 300 s, stocké en cache, hash `make_password`), mais `accounts/services/sms.py`
  est un **mock** (imprime une empreinte du numéro, n'envoie rien) → pas de vraie vérification SMS en production.
- **Profil** : `SellerProfile` (OneToOne ; `seller_code`, `public_slug`, `business_name`, avatar, zones, catégorie).
- **Rôles/permissions** : pas de groupes sophistiqués. `is_staff` → admin plateforme ; décorateur `accounts.access.seller_required`
  (redirige les comptes sans boutique, 403 pour HTMX/JSON) ; DRF : `SessionAuthentication` + `IsAuthenticated` par défaut, throttling anon 30/min, user 100/min
  (variantes lisant l'IP via `core.services.client_ip`).
- **Hash des mots de passe** : Argon2 (puis PBKDF2). **django-axes** : 5 échecs, blocage 30 min sur (téléphone, IP), hooks dans `core/services/axes_hooks.py`.
- **Middlewares notables** (ordre) : `CanonicalHostMiddleware` (www → apex 301), `SecurityMiddleware`, `NoIndexMiddleware` (hôtes non prod), `CSPMiddleware`,
  `WhiteNoiseMiddleware`, `Session`, `CorsMiddleware`, `Common`, `Csrf`, `Authentication`, `Messages`, `XFrameOptions`, `HtmxMiddleware`, `AxesMiddleware` (en dernier).
- Fuseau `Africa/Bamako`, langue `fr-fr`.

---

## 4. Intégration Orange Money (section détaillée)

### 4.1 Fichiers et modules

| Chemin | Rôle |
|---|---|
| `config/settings/_orange.py` | lecture des variables `ORANGE_ML_*` / `ORANGE_MONEY_*`, timeout borné, devise |
| `config/settings/base.py` (l. ~626-642) | expose `ORANGE_MONEY_CLIENT_ID/SECRET/MERCHANT_KEY/BASE_URL/RETURN_URL/CANCEL_URL/NOTIFY_URL/TIMEOUT/CURRENCY` |
| `subscriptions/services/orange_money.py` | client HTTP : token OAuth2, initiation, statut, parsing du callback, contrôle de montant |
| `subscriptions/services/payment.py` | orchestration : création du paiement, URLs, activation idempotente, vérification active, annulation |
| `subscriptions/billing_views.py` | URLs **stables** `/billing/return/`, `/billing/cancel/`, `/billing/webhook/orange/` + `process_orange_webhook()` |
| `subscriptions/billing_urls.py` | routage `/billing/` |
| `subscriptions/views.py` + `urls.py` | checkout vendeur (`/seller/abonnement/checkout/<plan>/`), anciennes routes `retour/annule/callback`, diagnostic `debug-om` (DEBUG seulement) |
| `subscriptions/tasks.py` | tâche Celery `subscriptions.check_pending_orange_payments` |
| `subscriptions/models.py` | `SubscriptionPayment`, `WebhookLog`, `PlanConfig`, `SellerPriceOverride`, `Subscription` |
| `subscriptions/management/commands/regularize_orange_notif_token.py` | régularisation des paiements d'avant le correctif du token |
| Tests | `subscriptions/tests_orange_payments.py`, `tests_orange_status.py`, `tests_orange_env.py`, `tests_webhook_active_check.py`, `tests_webhooklog_endpoints.py`, `tests_views_billing.py` |
| Docs | `CLAUDE.md` § Orange Money, `subscriptions/README.md`, `docs/RUNBOOK_TEST_PAIEMENT.md` |

### 4.2 Flux complet

1. **Initiation** — le vendeur POST son téléphone sur `checkout_view`. `create_orange_payment()` :
   calcule le montant **côté serveur** (`get_price_quote`), génère `order_id` (`HF-{M|P}-{8 hex}`, ≤ 24 car.) et un `notif_token` local (`secrets.token_hex(32)`),
   **crée la ligne `SubscriptionPayment` (status `pending`) avant tout appel réseau**, puis appelle Orange.
2. **Token OAuth2** — `POST https://api.orange.com/oauth/v3/token`, `grant_type=client_credentials`, HTTP Basic (client_id/secret), timeout configurable. Jeton non mis en cache (un appel par opération).
3. **Appel WebPay** — `POST https://api.orange.com/orange-money-webpay/ml/v1/webpayment`, en-tête `Authorization: Bearer …`, JSON :
   `merchant_key`, `currency` (XOF), `order_id`, `notif_token`, `amount` (entier), `return_url`, `cancel_url`, `notif_url`, `lang` (`fr`), `reference`.
   Réponse 200/201 : `payment_url` (ou `paymentUrl`), `pay_token`, `notif_token` (celui d'Orange). L'application **remplace** son `notif_token` par celui d'Orange
   (constaté au test réel du 27/09 : le webhook renvoie le jeton d'Orange, pas le nôtre), conserve la réponse dans `raw_response` (dont `pay_token`), puis redirige l'utilisateur vers `payment_url`.
4. **URL de retour** — `GET /billing/return/?order_id=…` (`@login_required`, **pas** `csrf_exempt`). Le paiement est recherché **parmi ceux du vendeur connecté** (anti-IDOR). Si `pending` : vérification active ; si `success` → message + redirection ; sinon page d'attente (`payment_pending.html`).
   `GET /billing/cancel/` : passe un paiement `pending` en `cancelled`.
5. **Webhook** — `POST /billing/webhook/orange/` (`@csrf_exempt`, `@require_POST`). Corps JSON ou `application/x-www-form-urlencoded`. Contenu documenté : `status`, `notif_token`, `txnid` (pas de montant).
   Traitement (`process_orange_webhook`) : lookup **uniquement par `notif_token`** ; token absent → 200 ; token inconnu → `WebhookLog(payment=None, processed=False)` + 200 ;
   paiement déjà `success` → log « idempotent » + 200 ; montant notifié ≠ montant attendu → pas d'activation ; statut `SUCCESS` → **n'active pas sur la foi du payload** :
   rappelle `transactionstatus` (défense en profondeur, F-61) et n'active que si Orange confirme ; échec → `failed`. **Toujours HTTP 200** (exception interceptée et journalisée).
6. **Vérification du statut** — `POST …/orange-money-webpay/ml/v1/transactionstatus` avec `{order_id, amount, pay_token}` ; statuts lus : `SUCCESS`, `INITIATED`, `PENDING`, `EXPIRED`, `FAILED`.
   Appelée par le retour navigateur, le webhook et la tâche Celery (toutes les 5 min, paiements `pending` < 24 h).
7. **Activation** — `activate_subscription_from_payment()` : `@transaction.atomic`, `select_for_update` sur le paiement (anti-double activation webhook/retour/Celery), prolongation depuis l'échéance si même plan encore actif, sinon depuis maintenant ; journal `AuditLog` ; commission partenaire en best-effort.

### 4.3 Paramètres et formats

- **Pays/devise** : Mali, `XOF` (FCFA). **Montants : entiers FCFA, sans centimes** (2000 = 2 000 FCFA), envoyés tels quels, jamais ×100 (`PositiveIntegerField` côté paiement).
- `lang=fr`. `reference` : ASCII nettoyé, max 30 car. (`_safe_reference`) ; Orange rejette une référence trop longue (HTTP 400 code 24, constaté le 27/09).
- `order_id` : max 24 car. (400 sinon), unique en base. `notif_token` : unique, indexé, 128 max.
- `verify=True` explicite sur les appels de paiement/statut ; messages d'erreur sans secret (corps de réponse jamais repris).

### 4.4 Sandbox / production

**Aucune bascule dans le code** : une seule adresse d'API (`orange_money.py` l. 17-18), pas de réglage sandbox. Ce sont **uniquement les clés** qui déterminent le mode.
Conséquence documentée (finding F-165, 02/11/2026) : staging et prod utilisent les mêmes identifiants, donc un paiement staging est un **vrai** paiement.
En dev : tunnel **ngrok** (`ORANGE_ML_BASE_URL=https://xxxx.ngrok-free.app`, HTTPS public obligatoire). Un test réel à 100 FCFA se fait via un « tarif spécial » (`SellerPriceOverride`, `docs/RUNBOOK_TEST_PAIEMENT.md`).

### 4.5 Modèles de données

- `SubscriptionPayment` : `id` (UUID), `seller`, `plan`, `provider` (orange/moov/wave — seul Orange est implémenté), `amount`, `phone`, `status`
  (**`pending`, `success`, `failed`, `cancelled`, `expired`**), `order_id`, `notif_token`, `txn_id`, `price_override`, `is_special_price`, `payment_url`, `raw_response`, `raw_callback`, `created_at`, `updated_at`, `paid_at`.
- `WebhookLog` : trace de **chaque** webhook (`payment` nullable, `notif_token`, `status`, `txn_id`, `raw_payload`, `processed`, `error_message`).
- `Subscription`, `PlanConfig` (tarifs/quotas administrables en base, sans redéploiement), `SellerPriceOverride` (tarif spécial borné : ≥ 100 FCFA, ≤ prix officiel, 30 j max, `max_uses`).

### 4.6 Erreurs, timeouts, doublons, webhooks perdus

- **Erreur d'initiation** : `OrangeMoneyError` → paiement `failed`, `raw_response={"error":…}`, message utilisateur générique (détail affiché en DEBUG seulement).
- **Timeout** : `ORANGE_MONEY_TIMEOUT` (défaut 20 s, plafonné à 120). **Pas de retry** ni de mise en cache du token ; un `requests` qui lève (réseau/timeout) est capté par la vue (« n'a pas pu être initié ») et par `sync_orange_payment_status` (retourne `""`, ne lève jamais).
- **Doublons** : idempotence du webhook (`status == success` → ignoré, tracé) + verrou `select_for_update` à l'activation. Rien n'empêche l'utilisateur de lancer plusieurs initiations successives (chacune crée un `order_id`).
- **Webhook non reçu** : filet = vérification au retour navigateur + tâche Celery toutes les 5 min (24 h max). Au-delà, le paiement reste `pending` (pas de passage automatique à `expired` par délai local).
- **Montant** : si le callback annonce un montant ≠ attendu → pas d'activation (fail-closed) ; le montant fait foi côté serveur.

### 4.7 Abonnements / renouvellements

Plans FREE (0 / 3 ventes), MEDIUM (2 000 / 10), PRO (5 000 / illimité), 31 jours — valeurs en base (`PlanConfig`, lues uniquement via `subscriptions/services/plans.py`).
**Pas de prélèvement récurrent** : chaque période est un paiement manuel ; payer le même plan avant l'échéance prolonge à partir de la date de fin. À l'expiration, retour sur les limites FREE. Quota fail-closed (`subscriptions/services/limits.py`).

### 4.8 Problèmes connus / historique utile

- 27/09 (`c5b299b`, `7c77277`) : le webhook ne retrouvait pas le paiement car Orange renvoie **son** `notif_token` → correctif + commande de régularisation + webhook orphelin journalisé.
- 27/09 : référence > 30 car. rejetée (HTTP 400 code 24) → référence courte fixe.
- 01/10 (`ebbc6b7`, F-61/F-62) : le webhook activait sur la seule foi du payload → vérification active obligatoire. **F-62 (passage à `failed` sans vérification) : voir le suivi `docs/releases/v1.0.0-rc1.md` pour son statut** ; le code actuel marque encore `failed` sur un statut non-SUCCESS du payload sans appeler Orange (`billing_views.py` branche `else`).
- 11/10 (`c9d168e`) : double préfixe `ORANGE_ML_*` / `ORANGE_MONEY_*` (le code lisait un nom, la doc l'autre).
- 03/11 (`16956f6`, F-166) : sans les 3 variables `*_URL`, `_om_urls` retombe sur les anciennes routes `/seller/abonnement/…` et le webhook ne laissait aucune trace → les deux routes partagent désormais `process_orange_webhook`.
- F-165 : identifiants communs staging/prod (voir §4.4).
- Incohérences mineures observées : `debug-om` (DEBUG) envoie encore `notif_url` vers l'ancienne route ; docstrings d'`order_id` divergentes (`HF-PRO-XXXX`, `HF-M-a1b2c3d4e5f6`) alors que le format réel est `HF-M-` + 8 hex en majuscules ; `CLAUDE.md` cite un endpoint `/…/pay` alors que le code appelle `/webpayment`. Pas de TODO/FIXME dans le module.

### 4.9 Réutilisable tel quel vs spécifique HayaFlash

| Réutilisable pour Dowba (copier) | Spécifique HayaFlash (à réécrire) |
|---|---|
| `config/settings/_orange.py` (lecture env, double préfixe) | `Subscription`, `PlanConfig`, `SellerPriceOverride`, quotas, `limits.py` |
| `orange_money.py` en entier (token, initiation, statut, `verify_callback`, `callback_amount_mismatch`, `_safe_reference`) — changer `reference="HayaFlash"` et le préfixe d'`order_id` | `activate_subscription_from_payment` (logique plan/durée/tarif spécial/commission partenaire) |
| Modèles `SubscriptionPayment` (renommer en `Payment`, FK générique) et `WebhookLog` | `_om_urls` : le repli sur les anciennes routes (à supprimer, imposer les 3 URLs) |
| `process_orange_webhook`, `sync_orange_payment_status` (squelette : verrou + vérification active + idempotence) | Vues checkout/plan, templates, tarifs spéciaux |
| Tâche Celery `check_pending_orange_payments` + entrée beat | Paiements `distrib` (références OM saisies à la main, pas d'API) et `payments` (COD/mock) |
| Tests (`tests_orange_*.py`) comme base | `regularize_orange_notif_token` (dette historique) |

---

## 5. Front-end

- **Templates** : moteur Django (`templates/` + templates d'apps). Pas de SPA.
- **CSS** : **Tailwind en build statique vendorisé** (`static/vendor/tailwind/tailwind-hayaflash.css`), reconstruction documentée dans `docs/FRONTEND_VENDORING.md` (pas de Node dans le dépôt).
- **JS** : **HTMX 2.0.0** + **Alpine.js 3.14.9** + Lucide (icônes) + Chart.js, tous vendorisés dans `static/vendor/` (aucun CDN). JS maison dans `static/js/` (`hf-base`, `hf-public`, `hf-seller`, `hf-charts`, `hf-components`, `hf-install`…).
- **CSP** : active en Report-Only, `script-src 'self' 'unsafe-eval'` **sans** `'unsafe-inline'` → aucun `<script>`/`on*=` inline (garde-fou `core/tests_csp.py`), données via `data-*` ou `json_script`.
- **PWA** : `static/manifest.json`, `manifest-buyer.json`, `manifest-distrib.json`, service worker `static/sw.js` (cache statique versionné, pré-cache, offline gracieux), `hf-install.js`, context processor `pwa_install`.
- **Polices** : Inter + Poppins, auto-hébergées (`static/fonts/`). Design system : primary `#E63946`, gold `#FFB800`, success `#22C55E`, bg `#F5F5F5`.
- **Composants réutilisables** : `static/js/hf-components.js`, partials `templates/partials/` (ex. `_promo_price.html`).
- **Images** : upload → `FileSystemStorage` (`MEDIA_ROOT`, volume Docker `media_data`) ; redimensionnement automatique max 1600 px par **Pillow** (`core/services/image_optimize.py`, best-effort, appelé depuis `save()`), réduction côté navigateur pour la saisie assistée (`hf-assist.js`) ; limite Nginx 10 Mo, `FILE_UPLOAD_MAX_MEMORY_SIZE` 5 Mo ; notes vocales servies via `X-Accel-Redirect` (accès authentifié). Statiques : WhiteNoise (`CompressedManifestStaticFilesStorage`, Brotli).

---

## 6. Services annexes

- **Celery** (+ Redis, `django-celery-beat`) : files `default`, `flash_sales`, `notifications`. Planning (`CELERY_BEAT_SCHEDULE`) : ouverture/fermeture des ventes (60 s), rappels (300 s), **vérification des paiements Orange (300 s)**, expiration des commandes (900 s), `core.celery_heartbeat` (60 s) ; Distrib (conditionnel) : réconciliation, auto-confirmation, paiements, relevés hebdo. `CELERY_TASK_TIME_LIMIT` 30 min.
- **E-mail** : SMTP (hébergeur LWS en prod) ; backend console en dev ; commande `send_test_email`.
- **SMS** : app `notifications` + API Orange SMS, **désactivée** (`SMS_NOTIFICATIONS_ENABLED=false` par défaut) ; l'OTP utilise un mock.
- **WhatsApp** : pas d'API, **liens `wa.me`** avec message préformaté (`notifications/services/whatsapp.py`) ; WhatsApp Business API prévue « V1.1 ».
- **QR codes** : lib `qrcode` (`analytics/services/qrcode.py`). **PDF** : Non trouvé (aucune lib PDF dans `requirements.txt`). Images : Pillow.
- **Cache** : LocMem en dev, `django-redis` si `REDIS_URL`. **Logs** : `LOGGING` console + filtre masquant les jetons privés ; Gunicorn (`config/gunicorn_logging.py`). **Monitoring** : Sentry (`before_send` masque téléphones/e-mails), healthcheck `/health/` (DB + cache + battement Celery), audit `AuditLog`.

---

## 7. Qualité et tests

- **pytest 9.1.1 + pytest-django 4.12** (`pytest.ini` : `config.settings.test`, fichiers `tests.py`, `tests_*.py`) ; ~150 fichiers de tests ; couverture `pytest-cov` (seuil CI **60 %**, `.coveragerc` omet migrations/settings/config).
- Données de test : créées dans les tests (helpers `accounts/testing_helpers.py`, `conftest.py`) ; seeds de démo : `seed_marche_demo`, `seed_demo_distrib`. Pas de factory_boy ; fixtures JSON : Non trouvé.
- **Lint** : CI = `ruff check . --select E,F,W --ignore E501` ; aucun `ruff.toml`/`pyproject.toml` ; **pas de pre-commit** (`.pre-commit-config.yaml` absent) ; pas de black/flake8 configurés.
- Sécurité : `bandit`, `pip-audit` (workflow `deps-audit.yml`), garde-fou CSP, `scripts/release_check.py`, gouvernance `GOVERNANCE_RELEASE.md` / `GOVERNANCE_SECURITE.md`.
- CI : Tests sur **PostgreSQL 16** (`test_pg`), `manage.py check`, `makemigrations --check`.

---

## 8. Git et déploiement

- **Branches** : ~98 réfs (locales + `origin`). Conventions : `feat/…`, `fix/…`, `docs/…`, `chore/…`, `audit/…`, `backup/…` (une ancienne `feature/distrib` coexiste). Branche principale `main`, PR numérotées (#NNN).
- **Commits** (5 derniers) : style **Conventional Commits en français**, `type(scope): message` :
  `feat(distrib): seed demo : categorie cosmetiques et deux robes…`, `feat(distrib): seed demo V2…`, `Feat/paiement om grossiste page vente (#107)` (message de merge de PR), `feat(distrib): seed de demo et captures automatiques (#106)`, `fix(subscriptions): l'ancienne route du webhook Orange… (F-166) (#105)`.
- **Déploiement** : `Dockerfile` multi-stage (python:3.12-slim, utilisateur non-root, `collectstatic`), `docker-compose.yml` (dev), `docker-compose.production.yml` (db, redis, web/gunicorn, nginx, worker, beat), `infra/nginx/prod.conf`, `infra/scripts/` (`deploy_vps.sh`, `backup*.sh`, `restore*.sh`, `smoke_test.sh`, `check_stack_isolation.sh`), cron de sauvegarde, CI GitHub Actions (`ci.yml`, `deploy.yml`, `deps-audit.yml`). Les jobs `deploy-staging/prod` de `deploy.yml` sont **en pause** (`if: false`) ; déploiement manuel via `deploy_vps.sh`. Pas de systemd.
- **Environnements** : local (SQLite), **staging** (`/srv/hayaflash`, port 8020), **production** (`/srv/hayaflash-prod`, port 8021), sur le même VPS (HestiaCP), un `.env` par pile.

---

## 9. Recommandations pour Dowba

**À copier**
- Découpage settings base/dev/staging/prod/test + `_orange.py`, `_csp.py`, `_sentry.py` ; `require_env` en staging/prod.
- Module Orange Money (§4.9) avec ses tests, `WebhookLog`, tâche Celery de rattrapage, règle « lookup par `notif_token` + vérification active + toujours 200 + idempotence verrouillée ».
- `User` à identifiant téléphone E.164, Argon2, django-axes, throttling DRF derrière proxy de confiance (`client_ip`).
- Vendorisation front (zéro CDN) + CSP sans `unsafe-inline`, HTMX/Alpine, PWA, WhiteNoise.
- Healthcheck `/health/` public, isolation staging/prod par projet Docker, scripts de sauvegarde/restauration, `AuditLog`, masquage PII dans Sentry.

**À ne pas reproduire**
- Aucun bac à sable : **staging et prod avec les mêmes clés Orange** (F-165). Prévoir des identifiants distincts ou, à défaut, un garde-fou (montant plafonné/flag) dès le départ.
- Deux jeux de routes de callback (`/seller/abonnement/…` et `/billing/…`) et le repli silencieux sur les anciennes : n'exposer que les URLs stables et exiger les 3 variables.
- Double préfixe de variables (`ORANGE_ML_*`/`ORANGE_MONEY_*`) : choisir un seul nom.
- OTP SMS en mock et SMS inactifs : décider tôt du canal de vérification (point crucial pour une app grand public).
- Python 3.11 local vs 3.12 CI/Docker ; absence de pre-commit/formatter ; lint CI minimal (E,F,W) ; seuil de couverture 60 %.
- Passage `failed` sur la foi d'un payload de webhook (F-62), absence de retry/cache du token OAuth, jetons de paiement non expirés localement.
- Docs de gouvernance très volumineuses et fichier `CLAUDE.md` qui dérive du code : garder une documentation courte, testée.

**Vigilance pour une app grand public mobile**
- Réseaux 3G/4G : images réduites côté client et serveur, JS léger, service worker prudent (versionner le cache, ne pas mettre en cache les vidéos).
- Webhook Orange imprévisible : conserver la vérification active et un état « en attente » clair pour l'utilisateur ; prévoir l'expiration et la relance.
- Idempotence et concurrence sur tout ce qui touche à l'argent (verrous `select_for_update`, montants entiers FCFA calculés côté serveur, jamais lus du formulaire).
- Pas de prélèvement récurrent possible → rappels d'échéance et parcours de renouvellement simples.
- Abus : limiter les initiations de paiement par utilisateur, normaliser les numéros (indicatifs), protéger les endpoints publics (rate limiting, CAPTCHA non couvert ici).
- Conformité : pages légales, politique de confidentialité, noindex sur staging, secrets uniquement dans les `.env` serveur.

---

## Résumé

1. HayaFlash = Django 5.2 monolithe (FBV, services), HTMX + Alpine + Tailwind vendorisé, sans Node ni CDN.
2. SQLite en dev, PostgreSQL 16 + Redis + Celery en prod, Docker/Gunicorn/Nginx sur VPS ; CI GitHub Actions (déploiement auto en pause).
3. Auth par téléphone (modèle custom, Argon2, axes) ; OTP SMS existant mais mocké.
4. Orange Money = OAuth2 → `webpayment` → webhook + `transactionstatus` ; module très réutilisable (`subscriptions/services/orange_money.py`, `payment.py`, `billing_views.py`).
5. Règles clés : `notif_token` d'Orange pour le lookup, vérification active avant activation, idempotence verrouillée, toujours HTTP 200, FCFA entiers, `order_id` ≤ 24.
6. Pas de sandbox dans le code : seules les clés décident ; staging et prod partagent les clés (F-165).
7. Filets : retour navigateur + tâche Celery 5 min ; pas de renouvellement automatique.
8. Qualité : pytest (~150 fichiers, couverture ≥ 60 %), ruff minimal, pas de pre-commit.
9. À copier : settings découpés, module OM, CSP/vendoring, healthcheck, sauvegardes ; à éviter : routes de callback doubles, clés partagées, SMS mock.
10. Point ouvert à trancher pour Dowba : canal OTP réel et environnement de test Orange séparé.
