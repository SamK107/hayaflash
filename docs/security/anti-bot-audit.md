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

## Décisions du mainteneur (30/09) et suite donnée

| # | Décision | Suite |
|---|---|---|
| 1 | axes + retrait du verrou téléphone-seul | Fait (section B) |
| 2 | Protéger l'API DRF d'auth (**bloquant**) | **F-19 non traité** : ⬜ dans `docs/releases/v1.0.0-rc1.md:537`, l'API est **toujours routée** (`config/api_urls.py:125`). Donc protégée (B, C) ; retirer l'API plus tard (F-19) rendrait ces protections API superflues, sans les rendre nuisibles |
| 3 | Pas de django-ratelimit, étendre `rate_limit.py` | Fait (section C2) |
| 4 | Honeypot en helper + partial | Fait (section D) |
| 5 | Zones Nginx auth étendues ; zone commandes à trancher | Auth fait. **Zone commandes inchangée** (10 r/s burst 20) en attendant ta décision : estimation ci-dessous |
| 6 | IP passerelle Docker en Phase 4 | Commande documentée ci-dessous, aucune mesure faite |
| 7 | Section E : proposition seulement + nouveau finding | **F-59** ouvert dans le suivi ; proposition ci-dessous |
| 8 | Garde `REDIS_URL` prod/staging | Fait (`config/settings/prod.py`, `staging.py`) |

## Section A — IP client : validation

`core/services/client_ip.py` est la seule fonction de résolution d'IP (15 tests, `core/tests_client_ip.py`). Axes la lit (`AXES_CLIENT_IP_CALLABLE = core.services.client_ip.get_client_ip`), ainsi que `rate_limit.py`, le throttling DRF, les CGU et l'audit. Aucune seconde fonction créée ; aucune relecture de `HTTP_X_REAL_IP` ailleurs. Test axes ↔ en-tête de proxy de confiance : `core/tests_axes.py::test_ip_comes_from_trusted_proxy_header`.

Écarts restants (non corrigeables sans le VPS, Phase 4) :

- `set_real_ip_from` reste commenté dans `infra/nginx/prod.conf` : tant que rien n'est posé, tous les clients partagent l'IP de la passerelle → **toutes les limites par IP (Nginx et Django, axes compris) se partagent une seule clé**. À lever avant d'ouvrir au trafic réel.
- `TRUSTED_PROXY_NETWORKS` (RFC 1918) est large ; à resserrer sur le sous-réseau réel.
- Le `proxy_set_header X-Forwarded-For $remote_addr` du Nginx conteneur **écrase** (pas de concaténation) : conforme.

### À lancer en Phase 4, sur le VPS, avec ta validation (rien de fait ici)

```bash
docker network inspect hayaflash_default --format '{{range .IPAM.Config}}{{.Subnet}} gw={{.Gateway}}{{end}}'
```

Puis, une fois le conteneur Nginx démarré, l'IP source qu'il voit pour une requête venant de l'hôte :

```bash
curl -sS -H 'X-Forwarded-For: 203.0.113.7' http://127.0.0.1:8010/health/ >/dev/null
docker compose -p hayaflash -f docker-compose.production.yml logs --tail=5 nginx   # 1er champ = IP source vue
```

Renseigner alors `set_real_ip_from <passerelle>;` dans `infra/nginx/prod.conf` et `TRUSTED_PROXY_NETWORKS=<sous-réseau>` dans `/srv/hayaflash/.env`.

### Snippet HestiaCP (à appliquer par toi ; non modifié ici)

Dans le vhost du domaine (le `location /` qui fait `proxy_pass` vers `127.0.0.1:8010`) :

```nginx
proxy_set_header Host              $host;
proxy_set_header X-Forwarded-For   $remote_addr;   # ÉCRASE : jamais $proxy_add_x_forwarded_for (le client en forgerait le début)
proxy_set_header X-Forwarded-Proto $scheme;
```

### Vérification manuelle post-déploiement

1. Depuis un téléphone en 4G (IP publique connue via un site « mon IP ») : ouvrir `https://<domaine>/login/` et saisir **un** mauvais mot de passe.
2. Sur le VPS : `docker compose -p hayaflash -f docker-compose.production.yml exec web python manage.py shell -c "from axes.models import AccessAttempt as A; print(list(A.objects.values_list('ip_address', flat=True)[:5]))"`.
3. L'IP affichée doit être l'IP publique du téléphone, **pas** 172.x / 10.x / 192.168.x / 127.0.0.1. Sinon : realip inactif (écarts ci-dessus).
4. Depuis un second appareil (autre IP) : 5 échecs sur un numéro de test ne doivent pas bloquer le premier appareil.

## Section B — django-axes (fait)

- `django-axes==8.3.1` épinglé (`requirements.txt`) ; `axes` dans `INSTALLED_APPS`, `AxesMiddleware` en dernier, `AxesStandaloneBackend` **en premier** ; `PhoneAuthBackend` conservé. Migrations : celles d'axes (`manage.py migrate`) ; `makemigrations --check` vert.
- Réglages (`config/settings/base.py`, bloc « Anti-bot ») : `AXES_FAILURE_LIMIT = 5`, `AXES_COOLOFF_TIME = 30 min`, `AXES_RESET_ON_SUCCESS = True`, `AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]` (**téléphone + IP**, jamais téléphone seul).
- Champ téléphone : `core/services/axes_hooks.py::lockout_username`. Le HTML et l'admin envoient `username`, l'API `phone` ; tout est normalisé vers **une seule clé** (les trois routes partagent le même compteur : `test_html_and_api_share_the_same_counter`).
- Le verrou « téléphone seul » de `login_view` est **supprimé** (il laissait n'importe qui bloquer un vendeur). Le plafond par IP reste.
- Page de verrouillage : `templates/accounts/lockout.html` (429), message demandé ; JSON `{"detail": [msg]}` pour `/api/`.
- Piège DRF corrigé : `accounts/services/auth.py` passe l'`HttpRequest` sous-jacent à `authenticate()` ; avec le wrapper DRF, le verrou ne remontait jamais au middleware (403 au lieu de 429).
- À savoir : l'échec qui atteint la limite (le 5ᵉ) renvoie déjà 429.
- Tests : `core/tests_axes.py` : verrou après 5 échecs, autre IP non bloquée, autre téléphone non bloqué, remise à zéro au succès, IP via proxy de confiance, formats de numéro, API, admin. Axes désactivé par défaut en test (`AXES_ENABLED = False`).

## Section C — Rate limiting (fait, sauf zone commandes)

### C1 — Nginx conteneur (`infra/nginx/prod.conf` ; `nginx -t` OK sur `nginx:1.27-alpine`, en local)

- Zone `auth` : **10 r/min**, burst 5, 429 ; appliquée à `/login/`, `/register/`, `/otp/` **et** `/api/v1/accounts/auth/`.
- Réponse 429 **JSON** (`@rate_limited_json`) sur l'API d'auth et `/api/v1/orders/` : le front Alpine lit le premier message de l'objet ; un 429 HTML faisait afficher « Connexion impossible ».
- Rien sur `/static/` ni `/media/` (test). **Zone commandes `api_orders` inchangée** (voir plus bas).
- La zone `auth` est commune aux 4 routes, par IP : elle dépend de `set_real_ip_from` (section A).

### C2 — Django (`core/services/rate_limit.py`, constantes `RATELIMIT_*` dans les settings)

- Cache : Redis en prod, **imposé** par la garde `REDIS_URL`.
- Login : **10/min/IP** (`RATELIMIT_LOGIN_IP`), remplace l'ancien 20/15 min. Inscription : **5/h/IP** (`RATELIMIT_REGISTER_IP`). **Mêmes clés** pour le HTML et l'API DRF (changer de route ne donne pas un second quota).
- Commande : **10 / 10 min par numéro acheteur** (`RATELIMIT_ORDER_PHONE`). Clé = 8 derniers chiffres (`+22370000001` et `70 00 00 01` partagent le quota). Compté seulement pour une **nouvelle** commande (un rejeu idempotent ne consomme rien). 429 JSON en français : `{"detail": ["Trop de commandes avec ce numéro. …"]}`.
- Limite déjà en place, conservée et non touchée : 30/min/IP sur `/api/v1/orders/` (`orders/services/client_order.py`, PS-09).
- `RATELIMIT_ENABLE = False` en test, activé par `override_settings` dans les tests dédiés (`core/tests_auth_rate_limit.py`, `core/tests_auth_api_rate_limit.py`, `orders/tests_order_phone_limit.py`). Nginx : `core/tests_nginx_ratelimit.py`.
- Limite assumée : la limite par téléphone ne gêne pas un bot qui change de numéro à chaque commande ; c'est F-59 qui traite ce cas.

### Zone commandes Nginx : estimation pour ta décision

Trois plafonds s'empilent sur `/api/v1/orders/` pour **une même IP** :

1. Nginx `api_orders` aujourd'hui : 10 r/s (600/min), burst 20.
2. Nginx proposé : 60 r/min (1 r/s), burst 20 nodelay → admis : 30 requêtes sur les 10 premières secondes, 80 sur la première minute, 60/min ensuite.
3. **Django, déjà en place : 30 POST/min/IP** (PS-09), fenêtre fixe, compté à chaque POST (rejeux et doubles-clics compris).

Le plafond réellement actif est donc **30/min** : passer Nginx à 60 r/min **ne change rien tant que Django reste à 30**. Il faut relever les deux ensemble pour que ça serve.

Capacité en acheteurs distincts derrière une même IP CGNAT (hypothèse : 1,3 POST par acheteur, doubles-clics et retries compris) :

- plafond Django 30/min → **≈ 23 acheteurs/min** ;
- Nginx 60 r/min → ≈ 46 acheteurs/min (si Django était relevé) ;
- Nginx actuel 10 r/s → non limitant.

Comparaison avec un pic. **Ce sont des hypothèses, pas des mesures** : je n'ai aucune donnée sur le nombre d'abonnés par IP chez les opérateurs maliens ni sur le trafic de vos ventes.

| Vente | Commandes/min au pic (toutes IP) | Part des acheteurs sur une même IP CGNAT | POST/min sur cette IP | Limite 30 (Django) | Nginx 60 r/min |
|---|---|---|---|---|---|
| modeste | 10 | 100 % | 13 | passe | passe |
| populaire | 30 | 50 % | 20 | passe | passe |
| populaire | 30 | 100 % | 39 | **bloque** (~9 POST/min refusés) | passe |
| très populaire | 100 | 30 % | 39 | **bloque** | passe |
| très populaire | 100 | 100 % | 130 | bloque | **bloque** |

Deux effets de bord : (a) un bot derrière la **même** IP consomme le quota des acheteurs légitimes de cette IP ; (b) à 30 ou 60 commandes/min, un bot avec des numéros différents vide un stock de quelques dizaines d'unités en une minute. **Aucune limite d'IP compatible CGNAT ne protège le stock** : c'est F-59.

Recommandation : Nginx `api_orders` à **120 r/min (2 r/s), burst 40**, et Django `ORDER_SUBMIT_RATE_MAX_PER_WINDOW` à **120/min**, relevés ensemble. La finesse repose sur la limite par téléphone (10/10 min) et sur F-59. Sinon, garder l'existant (10 r/s et 30/min) en sachant qu'il bloque les IP partagées dès ~23 acheteurs/min. **Rien modifié en attendant ta décision.**

## Section D — Honeypot (fait)

- Existant réutilisé et complété, pas dupliqué : `core/services/honeypot.py` (champ piège `website`, jeton `form_ts` signé par `django.core.signing` ; rejet si < 3 s, > 2 h, signature invalide ou absente ; **un seul message générique** côté utilisateur, le motif n'est que journalisé) + templatetag `{% honeypot_fields %}` (`core/templatetags/hf_honeypot.py`) + partial `templates/partials/_honeypot.html` (hors écran en CSS, pas `type="hidden"`, `tabindex="-1"`, `autocomplete="off"`).
- Appliqué à l'inscription HTML (`core/views.py`, `templates/accounts/register.html`). **Contact : aucun formulaire de contact dans le dépôt** (rien à protéger).
- **Commande acheteur : DRF/JSON appelé via `fetch` Alpine → non implémenté**, comme demandé. Idem **API d'inscription JSON** : aucun front ne l'appelle (F-19) et un client scripté ne « voit » jamais le champ ; elle est couverte par axes et la limite IP.
- Tests : `core/tests_honeypot.py` (champ rempli, trop rapide, signature altérée, payload altéré, autre salt, jeton absent/illisible, expiré, soumission normale, message non révélateur). Les tests qui postent sur l'inscription HTML fournissent un jeton valide (`core/testing_helpers.py::honeypot_ok`).
- Limite connue : une page restée ouverte plus de 2 h puis soumise est rejetée avec le message générique ; l'utilisateur recharge et réessaie.

## Garde REDIS_URL (décision 8)

`config/settings/prod.py` et `staging.py` lèvent `ImproperlyConfigured` si `REDIS_URL` est vide (tests : `core/tests_security_settings.py`). Conséquences à reporter dans le déploiement :

- `/srv/hayaflash/.env` doit contenir `REDIS_URL` **avec le mot de passe** (le compose lance Redis avec `--requirepass ${REDIS_PASSWORD}`) : `redis://:<REDIS_PASSWORD>@redis:6379/1`. Sans mot de passe dans l'URL, Redis refuse les commandes et `rate_limit.py` (fail-open) **laisse tout passer en silence** : à vérifier avant le premier déploiement.
- `scripts/release_check.py` passe désormais un `REDIS_URL` factice à `check --deploy` (sinon la garde le ferait échouer).

## F-59 — stock réservé sans expiration (nouveau finding, ajouté au suivi)

Constat : `orders/services/create_order.py:160-161` décrémente `Product.stock_available` dès la création d'une commande COD ; aucune tâche ni règle ne restitue le stock d'une commande jamais honorée (rien de tel dans `orders`, `payments`, `flash_sales/tasks.py`, `config/celery.py`). Un bot (ou un acheteur de mauvaise foi) peut vider le stock d'une vente sans jamais payer.

Proposition (non implémentée, à arbitrer) :

1. **Plafond de commandes non honorées par téléphone** (et par vente) : refuser une nouvelle commande si ce numéro a déjà N commandes `PENDING` (ex. 2 par vente, 3 au total), dans `orders/services/create_order.py` (dans la transaction) ou `orders/services/client_order.py`.
2. **Expiration** : tâche Celery beat qui passe en `CANCELLED` les commandes `PENDING` non prises en charge par le vendeur après un délai paramétrable (ex. 30–60 min) — `orders/tasks.py` (à créer), `config/celery.py`.
3. **Restitution du stock** : à l'annulation ou l'expiration, `Product.stock_available += quantité` + `StockMovement` inverse, en transaction et idempotent (`orders/services/cancel_order.py`, à créer).
4. Annulation manuelle par le vendeur : même chemin de restitution.

Fichiers : `orders/services/create_order.py`, `orders/models.py`, `products/models.py` (StockMovement), `config/celery.py`, tests dédiés. Décisions produit à prendre : délai d'expiration, valeur des plafonds, statut exact d'une commande « prise en charge ».

## Section E

Non implémentée (conditionnelle) : la section 0 a confirmé le COD. Le risque est porté par **F-59**.

## Hors périmètre (finding, non touché)

- **F-60** : `/f/<slug>/interest/` crée une `SaleInterest` par appel sans dédoublonnage (`analytics/views.py:143-179`).

## Section F — vérification finale (30/09)

| Contrôle | Résultat |
|---|---|
| `manage.py check --deploy --fail-level WARNING --settings=config.settings.prod` (env factice : `DEBUG=false`, `SECURE_SSL_REDIRECT=true`, `REDIS_URL` factice) | **0 warning** |
| `pytest --ds=config.settings.test` | **602 passed**, 3 skipped (base de départ : 561) |
| Couverture | **89 %** (11 721 lignes) — identique à la base de départ (89 %) |
| `ruff check . --select E,F,W --ignore E501` | vert |
| `makemigrations --check --dry-run` | aucun changement (les migrations d'`axes` viennent du paquet) |
| `pip-audit -r requirements.txt` | **aucune vulnérabilité connue** (dont `django-axes==8.3.1`) |
| `nginx -t` (`nginx:1.27-alpine`, local, `web` résolu en factice) | OK |

Remarques :

- La suite comptait 561 tests (et non 70) au départ.
- `check --deploy` avec le `.env` local échoue sans `DEBUG=false` / `SECURE_SSL_REDIRECT=true` : `scripts/release_check.py` les fixe déjà, c'est l'environnement du poste qui les contredit.
- Coverage non mesurée avec `test_pg` (PostgreSQL) : CI seulement.

### À faire par toi (rien de fait côté VPS / HestiaCP)

1. Décider de la zone Nginx commandes (estimation plus haut).
2. Phase 4 : `docker network inspect`, puis `set_real_ip_from` + `TRUSTED_PROXY_NETWORKS` ; snippet HestiaCP (section A).
3. `/srv/hayaflash/.env` : `REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/1` (obligatoire désormais, sinon le démarrage échoue). `manage.py migrate` (tables `axes_*`).
4. Vérification post-déploiement (section A).
