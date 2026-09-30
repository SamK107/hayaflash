# Audit anti-bot — Section 0 (lecture seule)

> Branche `feat/anti-bot-hardening`. Aucun code modifié, aucune action sur le VPS.
> Date : 2026-09-30. Tout ce qui suit est lu dans le dépôt ; ce qui n'a pas pu
> l'être est marqué **INCONNU**.

## Synthèse — ce qui change le plan

1. **Le login appelle déjà `authenticate(request, ...)`** → django-axes se déclencherait (point 10 levé).
2. **Un rate limit + un honeypot existent déjà** sur `/login/` et `/register/` (PR #37). Axes (B), ratelimit (C2) et honeypot (D) **recouvrent** l'existant → arbitrage demandé (voir « Décisions »).
3. **Les API DRF `/api/v1/accounts/auth/login|register/` sont publiques et sans aucune protection propre** (seul le throttle DRF global 30/min anon). Elles contournent le rate limit par téléphone et le honeypot des vues HTML. C'est le vrai trou.
4. **La commande acheteur est du COD** → Section E non applicable (mais le stock est bien réservé à la création : voir point 5).
5. **L'IP client vue par Django est probablement l'IP de l'hôte pour tous** tant que `set_real_ip_from` reste commenté dans `infra/nginx/prod.conf` : tous les acheteurs partageraient le même compteur.

## 1. Settings et cache

- `config/settings/{base,dev,prod,staging,test,test_pg}.py`. Prod = `config.settings.prod` (`docker-compose.production.yml:18`), qui importe `base`.
- `CACHES` (`base.py:75-97`) : **Redis (`django_redis`) si `REDIS_URL` défini, sinon LocMem**. Prod n'impose pas `REDIS_URL` (pas de garde dans `prod.py`). Le compose fournit Redis (mot de passe via `--requirepass`) et `env_file: /srv/hayaflash/.env` ; `REDIS_URL` doit donc y figurer — **non vérifiable depuis le dépôt** (le `.env` du VPS n'est pas lu). Si absent : LocMem par process (3 workers Gunicorn → compteurs non partagés) **sans erreur visible**.
- Test : LocMem (`test.py:88`).

## 2. Login vendeur

- HTML : `core/views.py:95 login_view` (FBV), `POST /login/`. Appelle `authenticate(request, username=phone, password=password)` (`core/views.py:127`) → **`request` bien passé**.
- API : `accounts/views.py:26 LoginView` → `accounts/services/auth.py:31 login_user` → `authenticate(request, phone=..., password=...)` (`request` passé aussi).
- Backend : `accounts/backends.py:9 PhoneAuthBackend.authenticate(self, request, phone=None, password=None, **kwargs)` ; accepte aussi `username=`. Normalise le téléphone, compare le mot de passe, retourne l'utilisateur ou `None`.
- Admin Django : utilise `authenticate(request, username=..., password=...)` → passe par `PhoneAuthBackend` (via `username`).

## 3. `AUTHENTICATION_BACKENDS`

`base.py:267` et `test.py:117` : `["accounts.backends.PhoneAuthBackend", "django.contrib.auth.backends.ModelBackend"]`.

## 4. Formulaires / endpoints publics (non authentifiés)

| URL | Type | Protection actuelle |
|---|---|---|
| `POST /login/` | Formulaire Django HTML (FBV, pas de `forms.Form`) | rate limit IP 20/15 min + échecs par téléphone 5/15 min (`core/views.py:26-30,105-121`) ; nginx zone `auth` 5r/min |
| `POST /register/` | HTML (FBV) | rate limit IP 5/h + honeypot `website` (`core/views.py:33-36,164-183`, `register.html:123`) |
| `POST /api/v1/accounts/auth/login/` | **DRF/JSON** (AllowAny) | **aucune** hors throttle DRF anon 30/min par IP |
| `POST /api/v1/accounts/auth/register/` | **DRF/JSON** (AllowAny) | **aucune** hors throttle DRF anon 30/min |
| `POST /api/v1/orders/` | **DRF/JSON** (AllowAny, sans auth), appelé via `fetch` depuis `/order/` et `/f/<slug>/` | `enforce_public_order_rate_limit` 30/min/IP (`orders/services/client_order.py:26-48`) ; nginx zone `api_orders` 10r/s burst 20 |
| `POST /f/<slug>/interest/` | JSON, `@csrf_exempt` (`analytics/views.py:143`) | `allow_tracking_request` (bot UA + IP + fingerprint) ; **crée une `SaleInterest` par appel, sans dédoublonnage** |
| `POST /track/wa/` | JSON, `@csrf_exempt` | `allow_tracking_request` |
| pages GET `/f/…`, `/s/…`, `/ventes/`, `/order/`, `/health/` | lecture | throttle nginx `general` |
| Formulaire de contact | **n'existe pas** (aucune route `contact`) | — |

Le honeypot de la Section D ne peut donc s'appliquer qu'à **inscription** (déjà fait). « Contact » : rien à protéger. Commande : **DRF/JSON → non implémenté, listé ici** (conforme à la consigne).

## 5. Flux de commande et stock

- `orders/services/create_order.py:160-161` : `Product.objects.filter(..., stock_available__gte=need).update(stock_available=F(...)-need)` à **la création de la commande**, + mouvements `RESERVATION` (`:182`). Aucun paiement en ligne n'intervient.
- Aucune expiration/restitution pour commandes non honorées trouvée (`grep unpaid|expire|release_stock` sur `orders`, `payments`, `flash_sales/tasks.py`, `config/celery.py` : rien).
- Conséquence : un bot qui passe des commandes bidon **vide le stock**. Le COD ne l'empêche pas. Le seul frein actuel est le rate limit par IP (30/min), qui tombe s'il est mal calibré (voir point 7).

## 6. Nginx conteneur (`infra/nginx/prod.conf`)

- Transmis à Gunicorn (dans les 3 `location` proxy) : `Host $host`, `X-Real-IP $remote_addr`, `X-Forwarded-For $remote_addr` (écrase, ne concatène pas), `X-Forwarded-Proto $hf_forwarded_proto`.
- `location = /health/` ne pose ni `X-Real-IP` ni `X-Forwarded-For`.
- `set_real_ip_from` **commenté** (`:62`) → realip inactif : `$remote_addr` = IP de l'hôte/passerelle. Django reçoit donc `X-Real-IP` = IP de l'hôte pour **tous** les clients, et `limit_req_zone $binary_remote_addr` agrège aussi tout le monde sous une seule clé.
- Gunicorn : `expose: 8000` seulement (`docker-compose.production.yml`), `--bind 0.0.0.0:8000` dans le conteneur ; pas de `ports:` sur `web`. Le seul port publié est celui du Nginx conteneur, `127.0.0.1:8010:80` (provisoire). Gunicorn n'est donc atteignable que depuis le réseau Docker du projet.
- Zones existantes : `general` 30r/s, `api_orders` 10r/s (burst 20), `auth` **5r/min** (burst 5) sur `^/(login|otp)/`. **`/register/` n'est pas dans la zone `auth`** ; `/api/v1/accounts/auth/*` non plus.

## 7. Sous-réseau Docker et IP source vue par le Nginx conteneur

**INCONNU — non déterminé.** Le réseau est `hayaflash_default` (compose `name: hayaflash`, pas de `networks:` explicite). Le sous-réseau réel n'est pas dans le dépôt ; il faut `docker network inspect hayaflash_default` **sur le VPS**, ce qui est interdit sans ta validation explicite. Le Docker de ce poste de dev ne reflète pas le VPS. Idem pour l'IP source des requêtes de l'hôte : avec un `ports: "127.0.0.1:8010:80"` en bridge, le conteneur voit généralement la passerelle du bridge (`172.x.0.1`), mais **je ne le déduis pas** : à mesurer (log d'une requête réelle).
`TRUSTED_PROXY_NETWORKS` en prod = `172.16.0.0/12, 10.0.0.0/8, 192.168.0.0/16` (`prod.py:47`), volontairement large.

## 8. Versions

- Django installé dans `.venv` : **5.2.17** (épinglé `requirements.txt`).
- `django-axes` : dernière **8.3.1** (Django 4.2/5.2/6.0, Python ≥ 3.10). Python du poste : 3.11.9. Compatible.
- `django-ratelimit` : dernière **4.1.0** (Python ≥ 3.7). Métadonnées PyPI sans borne Django. Ni l'un ni l'autre n'est dans `requirements*.txt`.
- Note : `axes` a besoin d'une migration (tables) et d'un middleware `AxesMiddleware`.

## 9. Mécanismes anti-abus déjà en place

| Élément | Couvre | Comment |
|---|---|---|
| `core/services/rate_limit.py` | utilitaire : `hit` / `is_limited` / `reset` / `phone_key` | cache Django, clés `rl:`, téléphone haché (sha256[:16]), **fail-open** si cache KO. Utilisé seulement par `login_view` et `register_view` |
| `core/throttling.py` | DRF : throttle anon 30/min et user 100/min | identifie via `get_client_ip` (et non XFF brut) |
| Login HTML | IP 20 tentatives/15 min (429) ; 5 échecs/15 min **par téléphone seul** (429), remis à zéro au succès | `core/views.py:95-141` |
| Inscription HTML | IP 5/h (429) ; honeypot `website` (champ rempli → erreur générique) | `core/views.py:144-183` ; template `register.html:120-125` |
| Commande | 30/min/IP, compteur dans `orders/services/client_order.py` (pas `rate_limit.py`) | `cache.incr` sans `add` atomique propre |
| Tracking public | `analytics/services/abuse.py` : UA bot + IP + fingerprint | pour `interest` et `track/wa` |
| Client IP | `core/services/client_ip.py` : `X-Real-IP` cru seulement si `REMOTE_ADDR` ∈ `TRUSTED_PROXY_NETWORKS`, XFF jamais lu | tests `core/tests_client_ip.py` (15 tests) |

Écarts avec le prompt :
- **Verrouillage par téléphone seul** (existant) : c'est exactement ce que la Section B interdit (« jamais le téléphone seul : n'importe qui bloquerait un vendeur en pleine vente »). Aujourd'hui, 5 mauvais mots de passe de n'importe qui bloquent le vendeur 15 min, même avec le bon mot de passe (test `test_sixth_attempt_...` l'acte explicitement).
- Le honeypot existant n'a **pas de timestamp signé** ni de temps minimal.
- Le mot de passe minimum est de 6 caractères (`_phone_errors`), ce qui rend le brute force plus rentable.

## 10. `authenticate()` dans le login

Oui (HTML `core/views.py:127`, API `accounts/services/auth.py:31`), avec `request`. Axes peut donc fonctionner sans adaptation. Point d'attention : le champ credentials transmis à axes est `username` (HTML) mais `phone` (API) → à normaliser via `AXES_USERNAME_FORM_FIELD = "phone"` ou un `AXES_USERNAME_CALLABLE` pour que les deux routes comptent sur la même clé (et que le téléphone soit normalisé de la même façon : `+223…` vs saisie brute).

## 11. Paiement des commandes acheteur

**COD confirmé** : `docs/PROJECT_SPEC.md:93` (R6) et `:283-292` ; `create_order` n'appelle aucun fournisseur de paiement ; Orange Money ne sert qu'aux abonnements vendeurs (`subscriptions/`). **Section E = non applicable comme « expiration de paiement »**, mais le stock est réservé sans engagement (point 5) : la proposition de la Section E (plafond de commandes non honorées par téléphone/vente, restitution de stock) reste pertinente sous une autre forme (annulation vendeur → restitution, plafond par téléphone). À arbitrer.

---

## Décisions demandées avant de continuer

**D1 — Verrouillage login (B) vs existant.**
a) *Recommandé* : ajouter axes (verrou téléphone+IP, 5 échecs / 30 min) **et retirer** le verrou « téléphone seul » de `login_view` (il contredit la consigne) ; garder le plafond IP 20/15 min. Les tests `tests_auth_rate_limit.py` liés au verrou téléphone sont à réécrire.
b) Ne pas installer axes ; transformer le verrou de `rate_limit.py` en clé `téléphone+IP`. Moins de dépendance, mais pas de couverture admin automatique ni d'historique.
c) Empiler les deux (déconseillé : deux compteurs, deux messages).

**D2 — Endpoints DRF login/register.** Les protéger est le gain le plus net. Je propose de faire passer leur logique par les **mêmes** garde-fous que les vues HTML (axes couvre le login DRF automatiquement via `authenticate`; pour register : même compteur IP que l'HTML). Hors périmètre strict du prompt → OK pour les inclure ?

**D3 — `django-ratelimit` (C2).** Il dupliquerait `core/services/rate_limit.py` (déjà Redis-capable, fail-open, avec `phone_key`). Reco : **ne pas l'installer** ; étendre `rate_limit.py` pour (i) commande par téléphone acheteur 10/10 min (sur `api_v1_orders_create`, réponse 429 JSON), (ii) constantes dans les settings. Accord ? Sinon j'installe la 4.1.0.

**D4 — Honeypot (D).** Reco : extraire le champ `website` existant en **partial + helper réutilisable** et y ajouter timestamp signé (`django.core.signing`, ≥ 3 s, ≤ 2 h). « Mixin de formulaire » n'a pas de sens ici (aucune `forms.Form`, vues FBV) : je ferais un helper `core/services/honeypot.py` + partial, appliqué à l'inscription HTML et, si tu veux, au login. Contact : n'existe pas. OK ?

**D5 — Nginx conteneur (C1).** Les zones existent (`auth` 5r/min, `api_orders` 10r/s). Reco : ajuster `auth` à 10r/min burst 5, l'étendre à `/register/` et `/api/v1/accounts/auth/`, et renommer/recaler la zone commandes à 60r/min burst 20 (**≈ 1r/s, plus strict que l'actuel 10r/s** : à confirmer, vu le CGNAT). Préalable : `set_real_ip_from` (point 6) — sans lui, toutes les limites par IP partagent une clé unique. Il faut l'IP réelle de la passerelle (point 7).

**D6 — Section A.** `client_ip.py` est correct. Écarts à traiter : `set_real_ip_from` commenté, `TRUSTED_PROXY_NETWORKS` large, et `X-Real-IP` posé par le Nginx conteneur dépend de ce realip. Je ne peux pas fermer cela sans l'info du point 7 (mesure sur le VPS, avec ta validation) ou une valeur que tu me donnes.

**D7 — Section E.** Proposition (non implémentée) à rédiger dans le rapport : plafond de commandes `PENDING` par téléphone/vente, restitution du stock à l'annulation/expiration. OK pour la rédiger seulement ?

**D8 — `REDIS_URL`.** Prod démarre sans erreur avec LocMem si `REDIS_URL` manque. Je peux ajouter un garde dans `prod.py` (lever `ImproperlyConfigured`), hors périmètre : OK ?

Autre point, hors périmètre : `/f/<slug>/interest/` crée une ligne par appel sans dédoublonnage (spam de la liste vendeur). Non traité.
