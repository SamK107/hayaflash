# GOVERNANCE_SECURITE.md — HayaFlash

> Référence unique et suivie dans le temps sur l'état réel de la sécurisation et
> du monitoring du projet. Pas un vœu pieux — un état vérifié, catégorie par
> catégorie, avec la preuve (fichier lu, commande lancée) pour chaque ligne.
>
> **Dernière vérification : 2026-09-26** (sprint gouvernance B, branche
> `chore/governance-sprint-b` depuis `main` à `0bbab6a` : catégories 2, 4 et 7
> revues, preuves ci-dessous). Révision précédente : 2026-09-24 (sprint A).
>
> À remettre à jour à chaque changement d'infrastructure ou de déploiement
> majeur. Aucune action destructive ou irréversible ne doit être exécutée sans
> confirmation explicite préalable.

Généré à partir du référentiel inter-projets `checklist_surveillance_monitoring.md`
(issu de l'audit de services.symain.africa, septembre 2026), adapté à HayaFlash.

Légende : ✅ Fait · ⚠️ Partiel · ❌ Manquant · 🔍 À vérifier (nécessite accès serveur)

---

## 1. Erreurs applicatives (APM)

- ✅ **SDK de tracking installé et conditionné** — `sentry-sdk[django]==2.28.0` dans
  `requirements.txt` ; initialisation dans `config/settings/prod.py` sous
  `if SENTRY_DSN:` — jamais actif sans variable d'env.
- ✅ **Intégration Django + Celery + logging** — `DjangoIntegration`,
  `CeleryIntegration(monitor_beat_tasks=True)`, `LoggingIntegration` toutes
  déclarées dans `prod.py`.
- ✅ **`send_default_pii=False`** — présent explicitement dans l'appel
  `sentry_sdk.init(...)`.
- ✅ **Taux d'échantillonnage défini et non maximal** — `traces_sample_rate`
  réglable via `SENTRY_TRACES_SAMPLE_RATE` (défaut `0.1`), `profiles_sample_rate`
  via `SENTRY_PROFILES_SAMPLE_RATE` (défaut `0.05`).
- ✅ **Environnement étiqueté, staging couvert (24/09)** — initialisation
  factorisée dans `config/settings/_sentry.py::init_sentry(dsn, environment)`,
  appelée par `prod.py` (`environment="prod"`) **et** `staging.py`
  (`environment="staging"`). Opt-in : sans `SENTRY_DSN` dans le `.env` de
  l'environnement, rien n'est envoyé. `release=APP_RELEASE` (SHA git, déjà
  utilisé pour les ETag) pour relier une erreur à un déploiement.
- 🔍 **Règles d'alerte Sentry** — à configurer dans le dashboard : alerte
  email/Slack sur nouvelle erreur `environment:prod` (et sur les `logger.error`
  des webhooks paiement, catégorie 8).

---

## 2. Health checks & disponibilité

- ✅ **Endpoint `/health/` existe et est utilisé par le déploiement** —
  `config/api_urls.py:health` (alias racine dans `config/urls.py`), ciblé par
  le `HEALTHCHECK` du `Dockerfile`, par `docker-compose.production.yml`
  (service `web`), et par `infra/scripts/smoke_test.sh` appelé depuis
  `deploy.sh` avec rollback automatique si échec.
- ✅ **L'endpoint vérifie DB + cache (PR #20)** — `config/api_urls.py:health` :
  `SELECT 1` sur `connections["default"]` et aller-retour `cache.set/get`
  (Redis en staging/prod), chaque check isolé dans son `try/except`, **503**
  + `{"status": "degraded", "checks": {...}}` si l'un échoue. Accessible
  anonymement (Docker, Nginx, `smoke_test.sh`).
- ✅ **Celery (beat + worker) couvert par `/health/` (26/09, sprint B)** —
  tâche `core.celery_heartbeat` planifiée toutes les 60 s
  (`CELERY_BEAT_SCHEDULE`) : exécutée par le worker, elle écrit un timestamp
  dans le cache (`celery:heartbeat`, 600 s) → un battement récent prouve beat
  **et** worker. `config/api_urls.py:health` ajoute un check `celery` isolé :
  `ok` / `stale` (> `HEALTH_CELERY_MAX_AGE`, 180 s) / `missing` / `error` /
  `skipped` (eager ou sans `REDIS_URL`). `stale`/`missing` → `logger.error`
  (→ Sentry) mais **reste 200** par défaut : un 503 ferait échouer le
  HEALTHCHECK Docker et `smoke_test.sh` avant le premier battement → rollback
  d'une release saine. `HEALTH_CELERY_REQUIRED=true` pour le rendre bloquant.
  Preuve : `core/tests.py::CeleryHealthCheckTests` (8 tests : ok, stale,
  missing, required → 503, exception cache isolée, skipped).
  🔍 Reste à observer le passage `missing → ok` sur le VPS réel (runbook 3.2).
- 🔍 **Monitoring externe indépendant** (UptimeRobot, Better Uptime, Cloudflare
  Health Checks) — non visible dans le repo, ne peut pas l'être. À confirmer :
  existe-t-il un monitoring externe déjà configuré pour HayaFlash ?
- 🔍 **Alertes vers un canal réellement consulté** — dépend du point précédent
  et de la config Sentry (alertes email/Slack sur nouvelle erreur ?). À vérifier
  dans le dashboard Sentry / le service de monitoring externe.

---

## 3. Logs applicatifs

- ✅ **Logging structuré avec niveaux différenciés** — `config/settings/base.py`
  définit des formatters (`verbose`, `simple`) et des loggers dédiés par app
  critique (`accounts`, `orders`, `flash_sales`, `delivery` en `DEBUG` ;
  `django`, `celery` en `INFO`).
- ⚠️ **Rotation des logs** — pas de `RotatingFileHandler` Django (seul un
  handler `console` existe), mais la rotation est gérée au niveau Docker :
  `docker-compose.production.yml` configure le driver `json-file` avec
  `max-size: 20m` / `max-file: 5` pour web/worker/beat, et `10m`/`3` pour la DB.
  Fonctionnellement équivalent à l'exigence du référentiel, par un mécanisme
  différent — pas un manque en soi, mais à documenter comme choix assumé.
- ✅ **Loggers dédiés par app critique** — voir ci-dessus.
- N/A **Logs consultables sans root** — non applicable tel quel : les logs
  partent sur stdout/stderr capturés par Docker (`docker logs`), pas de fichier
  avec permissions à gérer. 🔍 à confirmer que l'utilisateur qui opère le VPS a
  bien accès à `docker logs` sans sudo systématique.

---

## 4. Sécurité applicative

- ⚠️ **CSP phase 1 faite (26/09, sprint B) — toujours Report-Only** —
  policy déplacée dans `config/settings/_csp.py` (partagée base/test) :
  `script-src 'self' 'unsafe-eval'` **sans `'unsafe-inline'`**,
  `media-src 'self' blob:` (messages vocaux), `CSP_REPORT_ONLY = True` par
  défaut (surchargeable par env pour un test local uniquement).
  - **Décision prise** : `'unsafe-eval'` conservé (exigé par Alpine standard,
    constructeur `AsyncFunction`) ; migration `@alpinejs/csp` écartée
    (18 templates Alpine à expressions inline, 0 `Alpine.data()`).
  - **Inline supprimé** : 44 `on*=` (9 templates) et 15 `<script>` inline
    migrés vers `static/js/hf-base.js` (commun + actions `data-hf-*` par
    délégation, liste blanche pour `data-hf-call`), `hf-public.js`,
    `hf-seller.js`, `hf-charts.js`. Données serveur via `data-*` ou
    `|json_script`. Chart.js (dernier CDN du projet) vendorisé.
  - **Mesure** : `CSP_REPORT_URI` par env (endpoint security Sentry), absent
    si vide. Pas de `report-to` (django-csp 3.8 n'émet pas l'en-tête
    `Reporting-Endpoints`).
  - **Garde-fou** : `core/tests_csp.py` échoue si un `on*=` ou un `<script>`
    sans `src` (hors JSON) réapparaît dans un template, et vérifie l'en-tête.
  - **Preuve** : parcours rejoués le 26/09 avec `CSP_REPORT_ONLY=false`
    **forcé localement** (variable d'env, non commitée), sur une copie de la
    base de dev — accueil, `/ventes/`, `/f/<slug>/` (live : commande + tiroir
    + zoom ; attente : chrono + alerte ; terminée : tiroir), inscription,
    tableau de bord, création de vente, Publication rapide, formulaire
    produit, paramètres/profil (copier), livraisons, modale d'upgrade,
    paiement en attente, statistiques PRO + admin plateforme (graphiques),
    `/admin/` Django : **0 violation CSP** dans la console.
  - Reste : `style-src 'unsafe-inline'` (attributs `style=`, hors périmètre) ;
    passage en mode bloquant = runbook étape 6, après 0 violation mesurée
    sur staging via `CSP_REPORT_URI`.
- ✅ **Headers sécurité prod** — dans `config/settings/prod.py` :
  `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_HTTPONLY`, `X_FRAME_OPTIONS=DENY`,
  `SECURE_HSTS_SECONDS=31536000` + `INCLUDE_SUBDOMAINS` + `PRELOAD`,
  `SECURE_REFERRER_POLICY`. Dupliqués aussi en headers Nginx dans
  `infra/nginx/prod.conf` (HSTS, `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`).
- ✅ **Rate limiting sur endpoints exposés** — géré côté Nginx
  (`infra/nginx/prod.conf`) avec trois zones : `general` (30 req/s),
  `api_orders` (10 req/s), `auth` sur `/login/` et `/otp/` (5 req/min,
  `limit_req_status 429`). Complété par le throttling DRF
  (`AnonRateThrottle`/`UserRateThrottle`, 30/min anon, 100/min user) dans
  `config/settings/base.py`.
- ✅ **Rate limiting sur cache partagé, pas mémoire locale** — le rate limiting
  HTTP est fait par Nginx (pas par worker Gunicorn, donc pas de problème de
  mémoire par process). Le throttling DRF utilise `CACHES["default"]`, qui
  bascule sur `django-redis` dès que `REDIS_URL` est défini (`base.py`) — donc
  cohérent entre workers en staging/prod.
- ✅ **Nouvelle surface API "Publication rapide" (20/09)** — `products/api.py`
  (`FlashSaleProductViewSet`) n'ajoute aucune exception au modèle d'auth
  existant : `DEFAULT_PERMISSION_CLASSES=IsAuthenticated` + throttling global
  s'appliquent déjà, et chaque action passe par `SellerOwnershipMixin`
  (`products/mixins.py`) pour verrouiller l'accès au vendeur propriétaire (ou
  à un staff avec `?seller_id=` explicite, jamais implicite). Suppression
  définitive d'un produit protégée par `on_delete=PROTECT` (`Order`/`OrderItem`)
  — refusée si des commandes existent, pas de perte d'historique possible via
  cette route. Toutes les mutations (`bulk-update`, `archive-product`,
  `delete-product`) sont journalisées via `core.models.audit()`.

---

## 5. Sauvegardes & reprise après sinistre

Stratégie actée dans [`docs/decisions/ADR-0001-strategie-sauvegardes.md`](docs/decisions/ADR-0001-strategie-sauvegardes.md).
**Code : complet. Exécution réelle : 0** — la catégorie reste la plus à risque
tant que rien n'a tourné sur le VPS.

- ✅ **Dump DB + archive médias** — `infra/scripts/backup.sh` (`pg_dump`
  compressé + `tar` des médias, rétention locale 14 j par défaut), testé en
  local via simulateur Docker (PR #18).
- ✅ **Chiffrement des sauvegardes hors-site (24/09)** —
  `infra/scripts/copy_offsite.sh` chiffre chaque fichier avec **age**
  (asymétrique) avant écriture sur le disque externe : seule la clé
  **publique** est sur le VPS (`/srv/hayaflash/backup_recipients.txt`), la clé
  privée reste dans le gestionnaire de mots de passe. Refus de copier si `age`
  est absent, si le fichier de clés est vide ou s'il contient une clé privée.
  Écriture via `.partial` + contrôle d'en-tête/taille + rename ; sha256 du
  clair conservé (`.src.sha256`) pour vérifier une restauration. Testé en
  local (24/09) : 3 cas de refus, copie, idempotence, aucun fichier en clair
  sur le disque, round-trip `age -d` → sha256 identique.
  Choix asymétrique plutôt que passphrase gpg : une passphrase aurait dû être
  stockée sur le VPS pour que le cron tourne sans interaction — interdit par
  l'ADR.
- ✅ **Copie hors-site (code)** — même script : fichier témoin
  `.hayaflash_backup_target` exigé à la racine du disque (pas de copie
  silencieuse sur le disque local si le disque n'est pas monté), idempotent,
  rétention hors-site 60 j par défaut.
- ✅ **Orchestration prête à planifier (24/09)** —
  `infra/scripts/backup_nightly.sh` enchaîne dump → copie chiffrée (sautée
  sans erreur si le disque n'est pas branché, ADR décision 1) → ping
  heartbeat (`BACKUP_HEARTBEAT_URL`, ex. healthchecks.io) uniquement en cas de
  succès : un cron mort ou un dump en échec se voit par l'absence de ping.
  `infra/cron/hayaflash-backup` (format `/etc/cron.d`, 02:30 UTC) —
  **volontairement non installé** (ADR décision 3).
- ✅ **Test de restauration (code)** — `infra/scripts/restore_test.sh`,
  validé en local. Pour une sauvegarde hors-site : `age -d -i <clé privée>`
  d'abord.
- ❌ **Première exécution réelle + restauration réelle** — checklist de
  déploiement final (ADR décision 4) : installer `age`, déposer la clé
  publique, brancher le disque + `touch .hayaflash_backup_target`, lancer
  `backup_nightly.sh` à la main, `restore_test.sh` sur ce dump, puis installer
  le cron.
- ✅ **Rétention documentée** — locale 14 j (`BACKUP_RETENTION_DAYS`),
  hors-site 60 j (`OFFSITE_RETENTION_DAYS`).
- ⚠️ **Limite 3-2-1 assumée** — disque externe au même endroit physique que
  le VPS (voir ADR, « Conséquences »).

---

## 6. Déploiement & rollback

- ✅ **Procédure de déploiement documentée et scriptée** —
  `infra/scripts/deploy.sh`, commenté en détail, invoqué par
  `.github/workflows/deploy.yml` via SSH.
- ✅ **Rollback automatique en cas d'échec** — `deploy.sh` sauvegarde le tag
  courant avant bascule (`.deploy_current_tag` → `.deploy_last_good_tag`),
  déploie, migre, `collectstatic`, lance `smoke_test.sh`, et si ça échoue
  redéploie automatiquement le dernier tag connu bon. Limite documentée dans le
  script lui-même : les migrations sont forward-only, un rollback d'image ne
  défait pas une migration DB incompatible.
- ✅ **CI avant `main`** — `.github/workflows/ci.yml` tourne sur toutes les
  branches/PR : `manage.py check`, `makemigrations --check --dry-run`, suite
  pytest avec couverture minimale (`--cov-fail-under=60`), lint ruff.
- ✅ **Point de reprise avant chaque déploiement** — `.deploy_last_good_tag`
  mis à jour avant chaque nouveau déploiement dans `deploy.sh`.
- ⚠️ **Déploiement automatique VPS actuellement désactivé** — dans
  `.github/workflows/deploy.yml`, les jobs `deploy-staging` et `deploy-prod` ont
  `if: false`, avec un commentaire daté du 13/09/2026 : pause volontaire, le VPS
  n'est pas encore prêt (`docker login ghcr.io`, secrets `STAGING_*`/`PROD_*`,
  `/srv/hayaflash/.env`). Le pipeline `test → build` continue de tourner sur
  chaque push vers `main`, mais rien ne se déploie automatiquement pour
  l'instant. **Rappel : réactiver (`if: true` ou retirer la ligne) une fois le
  VPS prêt.**

---

## 7. Durcissement infrastructure (VPS)

Non vérifiable depuis le code — ce sont des réglages serveur, pas des artefacts
du repo. **Scripté depuis le sprint B (26/09)** : `infra/scripts/vps_audit.sh`
(lecture seule, sortie Markdown ✅/❌/⚠️ à coller ici, dossier projet via
`HAYAFLASH_DIR`) couvre toutes les commandes ci-dessous plus les catégories 2
et 5 ; procédure complète dans `docs/RUNBOOK_JOUR_J.md`. Commandes unitaires
(aucune n'est destructive) :

```bash
# Pare-feu actif, ports ouverts
sudo ufw status verbose

# Anti brute-force SSH
sudo systemctl status fail2ban
sudo fail2ban-client status sshd

# SSH par clé uniquement, pas de root
sudo grep -E "^(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication)" /etc/ssh/sshd_config

# Mises à jour de sécurité automatiques
systemctl status unattended-upgrades 2>/dev/null || cat /etc/apt/apt.conf.d/20auto-upgrades

# PostgreSQL accessible uniquement en local
sudo grep -E "^listen_addresses" /etc/postgresql/*/main/postgresql.conf
# ou, si conteneurisé : vérifier qu'aucun port 5432 n'est publié dans
# docker-compose.production.yml (actuellement le cas — `db` n'a pas de
# section `ports:`, contrairement à docker-compose.yml en dev qui expose
# 5432 et 6379 volontairement pour le développement local).

# Permissions du fichier de secrets
ls -la /srv/hayaflash/.env
stat -c "%a %U:%G" /srv/hayaflash/.env   # attendu : 600, propriétaire du service
```

- 🔍 Pare-feu (ufw ou équivalent)
- 🔍 fail2ban
- 🔍 SSH par clé uniquement, `PermitRootLogin no`
- 🔍 Mises à jour de sécurité automatiques
- ✅ **DB accessible uniquement en local, côté conteneur** — confirmé par
  lecture de `docker-compose.production.yml` : le service `db` n'expose aucun
  port vers l'hôte (contrairement à `docker-compose.yml` en dev, qui publie
  `5432:5432` et `6379:6379` délibérément pour le développement local).
- 🔍 Permissions `.env` en `600` sur le VPS réel

---

## 8. Paiements & webhooks

- ✅ **Vérification cryptographique des webhooks** —
  `payments/services/webhooks.py:verify_webhook_signature()` : HMAC-SHA256 sur
  le corps brut, comparaison avec `hmac.compare_digest` (résistant aux attaques
  temporelles), secret requis (`PAYMENTS_WEBHOOK_SECRET`), aucune confiance
  sur l'IP source.
- ✅ **Notification admin sur webhook suspect / paiement FAILED (PR #21)** —
  `logger.error` (→ événement Sentry via `LoggingIntegration(event_level=ERROR)`)
  sur signature invalide ou configuration manquante (`payments/api.py`) et sur
  transition vers `FAILED` (`payments/services/webhooks.py`). Volontairement
  pas d'alerte sur `not_found`/`invalid` (bruit). 🔍 Effectif seulement une
  fois `SENTRY_DSN` + règle d'alerte configurés (catégorie 1).
- ✅ **Idempotence des traitements** — `apply_provider_webhook()` : transaction
  atomique, `select_for_update()` sur la ligne de paiement, retour anticipé si
  déjà `SUCCESS` ou déjà `FAILED` — un même événement reçu deux fois ne rejoue
  pas la comptabilisation (`append_balanced_entries_for_success`).

---

## 9. Dépendances & supply chain

- ✅ **Versions figées** — tout `requirements.txt` en `==`
  (`django-celery-beat==2.9.0` borné depuis la révision du 14/09).
- ✅ **Veille CVE automatisée (24/09)** — `.github/workflows/deps-audit.yml` :
  `pip-audit -r requirements.txt` chaque lundi 06:17 UTC, à chaque PR qui
  touche `requirements.txt`, et à la demande. Séparé de `ci.yml` (une CVE
  publiée la veille ne bloque pas un merge) ; un run planifié en échec envoie
  un email GitHub au propriétaire du repo. Chaque CVE corrigée → une ligne
  dans `docs/INCIDENTS.md`.
- ✅ **`.venv` exclu du dépôt git** — présent dans `.gitignore`. Pas de
  `node_modules` dans le projet (Tailwind chargé en CDN d'après le `CLAUDE.md`).

---

## 10. Gouvernance & documentation

- ⚠️ **Document de référence sur l'état réel de la prod** — HayaFlash a une
  documentation abondante (`docs/ARCHITECTURE.md`, `docs/CODEBASE_STATUS.md`,
  `docs/PLAN_PHASES.md`, `docs/PROJECT_SPEC.md`, `docs/API_CONTRACT.md`,
  `docs/QA_PLAN.md`, les `docs/workflows/WORKFLOW_P*.md`, `CLAUDE.md`), mais
  jusqu'ici rien qui joue spécifiquement le rôle de ce fichier — une référence
  datée et vérifiée sur la sécurisation/monitoring. **Ce document comble ce
  manque à partir d'aujourd'hui.**
- 🔍 **Checklist de déploiement suivie à chaque mise en prod** — le process est
  scripté (`deploy.sh`), donc suivi par construction dès que le pipeline sera
  réactivé (point 6) ; pas de checklist manuelle nécessaire tant que le script
  couvre tout.
- ✅ **Registre des incidents/correctifs de sécurité (24/09)** —
  `docs/INCIDENTS.md` (format, sources de détection, journal vide : pas encore
  de production).
- ✅ **Décisions d'architecture tracées** — `docs/decisions/` (ADR-0001).

---

## Synthèse des priorités (révision 2026-09-26)

Le code couvre toutes les catégories vérifiables depuis le repo, et le jour du
déploiement est scripté : **`docs/RUNBOOK_JOUR_J.md`** (ordre, commandes
exactes, résultat attendu, retour arrière) et **`infra/scripts/vps_audit.sh`**
(preuves à coller ici).

**Faits au sprint B (26/09)**

- Celery couvert par `/health/` (catégorie 2).
- CSP phase 1 : plus aucun JS inline, `script-src` sans `'unsafe-inline'`,
  mesure via `CSP_REPORT_URI` ; reste Report-Only (catégorie 4).
- Audit VPS scripté + runbook (catégories 5, 6, 7).

**Jour du déploiement VPS (runbook, dans l'ordre)**

1. Audit + durcissement (catégorie 7) — étape 1.
2. `.env` (600) + secrets GitHub — étape 2.
3. `deploy-staging` seulement (retrait de `if: false`) — étape 3.
4. Sentry DSN + règles d'alerte (dont battement Celery) + `CSP_REPORT_URI` +
   UptimeRobot sur `/health/` — étape 4.
5. Sauvegarde manuelle → `restore_test.sh` → cron + heartbeat — étape 5.
6. Après N jours stables : `deploy-prod`, puis `CSP_REPORT_ONLY=false` si
   0 violation mesurée — étape 6.

Le jour même : coller le rapport `vps_audit.sh` ici et passer les 🔍 en ✅/❌.
