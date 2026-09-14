# GOVERNANCE_SECURITE.md — HayaFlash

> Référence unique et suivie dans le temps sur l'état réel de la sécurisation et
> du monitoring du projet. Pas un vœu pieux — un état vérifié, catégorie par
> catégorie, avec la preuve (fichier lu, commande lancée) pour chaque ligne.
>
> **Dernière vérification : 2026-09-14** (audit direct du code source dans
> `C:\projets\hayaflash`, session Claude/Cowork).
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
- ⚠️ **Environnement étiqueté** — `environment="prod"` codé en dur dans
  `prod.py`. `staging.py` n'initialise pas Sentry du tout (choix documenté dans
  `.env.example` : "Sentry — production uniquement") → **zéro visibilité sur les
  erreurs en staging**. À décider : est-ce voulu, ou faut-il un DSN staging avec
  `environment="staging"` ?

---

## 2. Health checks & disponibilité

- ✅ **Endpoint `/health/` existe et est utilisé par le déploiement** —
  `config/api_urls.py:health` (alias racine dans `config/urls.py`), ciblé par
  le `HEALTHCHECK` du `Dockerfile`, par `docker-compose.production.yml`
  (service `web`), et par `infra/scripts/smoke_test.sh` appelé depuis
  `deploy.sh` avec rollback automatique si échec.
- ❌ **L'endpoint ne vérifie aucune dépendance critique** — il renvoie
  systématiquement `{"status": "ok", "service": "HayaFlash"}` sans tester la
  connexion DB, Redis ou Celery. Un healthcheck "vert" ne garantit donc pas que
  l'app peut réellement servir une requête si la DB ou Redis est down.
  **Action recommandée** : ajouter une vérification `connections["default"].cursor()`
  et un ping cache, avec un code 503 si l'un échoue.
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

- ❌ **CSP (Content-Security-Policy)** — aucun package `django-csp` dans
  `requirements.txt`, aucun header CSP dans `config/settings/prod.py` ni dans
  `infra/nginx/prod.conf`. Manquant.
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

---

## 5. Sauvegardes & reprise après sinistre

- ❌ **Backup base de données automatique** — aucun script de backup dans
  `infra/scripts/` (seuls `deploy.sh` et `smoke_test.sh` y figurent), aucun cron
  ni tâche Celery Beat de dump visible dans `config/settings/base.py`
  (`CELERY_BEAT_SCHEDULE` ne contient que les tâches métier flash-sales).
- ❌ **Backup des fichiers médias** — rien trouvé.
- ❌ **Chiffrement des sauvegardes** — sans objet tant qu'il n'y a pas de
  sauvegarde.
- ❌ **Copie hors-site** — rien trouvé.
- ❌ **Test de restauration** — rien trouvé.
- ❌ **Rétention documentée** — rien trouvé.

**C'est la catégorie la plus en retard du projet.** Si une sauvegarde existe
déjà au niveau du VPS (HestiaCP, snapshot du provider), elle n'est documentée
nulle part dans le repo — donc invisible et non vérifiable en cas de succession
ou de changement d'opérateur. Priorité haute.

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
du repo. Section à compléter avec un accès SSH en lecture seule au(x) VPS de
staging/prod. Commandes suggérées (aucune n'est destructive) :

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
- ❌ **Notification admin en cas d'échec de paiement ou de webhook suspect** —
  aucune alerte visible (pas de `logger.warning`/capture Sentry explicite sur
  signature invalide dans `webhooks.py`, pas de notification déclenchée sur
  transition vers `FAILED`).
- ✅ **Idempotence des traitements** — `apply_provider_webhook()` : transaction
  atomique, `select_for_update()` sur la ligne de paiement, retour anticipé si
  déjà `SUCCESS` ou déjà `FAILED` — un même événement reçu deux fois ne rejoue
  pas la comptabilisation (`append_balanced_entries_for_success`).

---

## 9. Dépendances & supply chain

- ⚠️ **Versions figées** — `requirements.txt` utilise `==` pour la quasi-totalité
  des paquets, **sauf** `django-celery-beat>=2.8.0` qui n'est pas borné en haut.
- 🔍 **Veille CVE** — aucun processus visible dans le repo (normal, c'est une
  habitude d'équipe plus qu'un artefact de code). À confirmer avec toi : y a-t-il
  une routine (même manuelle, ex. `pip list --outdated` mensuel) ?
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
- 🔍 **Historique des incidents/correctifs de sécurité conservé** — non trouvé
  dans le repo. À confirmer : y a-t-il un endroit (Notion, fichier, autre) où
  les incidents passés sont notés ?

---

## Synthèse des priorités

1. **Sauvegardes (catégorie 5)** — le point le plus en retard, à traiter en
   premier : au minimum un dump PostgreSQL quotidien + copie hors-site.
2. **Health check applicatif (catégorie 2)** — faire vérifier DB/Redis par
   `/health/` plutôt qu'un `200 OK` statique.
3. **CSP (catégorie 4)** — ajouter `django-csp` avec `default-src 'self'`.
4. **Notification admin sur webhook suspect (catégorie 8)** — capturer les
   signatures invalides vers Sentry ou une alerte dédiée.
5. **Durcissement VPS (catégorie 7)** — à vérifier par SSH avec les commandes
   ci-dessus dès qu'un accès est disponible.
6. Rappel opérationnel : réactiver `deploy-staging`/`deploy-prod` dans
   `.github/workflows/deploy.yml` une fois le VPS prêt (catégorie 6).
