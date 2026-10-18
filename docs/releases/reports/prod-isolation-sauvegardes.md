# Compte rendu — Lots 1 et 2 : isolation de la prod et sauvegardes

> Branche `fix/prod-isolation-sauvegardes` (depuis `main` à jour), 17–18/10/2026.
> **Rien n'a été joué sur le VPS.** Statut de chaque item : « fait dans la branche, à valider sur le VPS ».

## 1. Fichiers modifiés ou créés

**Lot 1 — isolation et fiabilité**

| Fichier | Changement |
|---|---|
| `docker-compose.production.yml` | `name: ${HAYAFLASH_PROJECT:-hayaflash}`, `env_file: .env` (relatif, 3 occurrences), port `127.0.0.1:${HAYAFLASH_HTTP_PORT:-8020}:80`, image `${DOCKER_IMAGE:-hayaflash}:${IMAGE_TAG:-latest}` (déjà là) ; worker en `CMD-SHELL` ; beat `healthcheck: disable: true` |
| `.env.example` | variables de pile (staging / prod), `HAYAFLASH_ALLOW_DEMO_SEED` (« staging uniquement — JAMAIS en production »), e-mail SMTP LWS, variables `BACKUP_*` |
| `infra/scripts/check_stack_isolation.sh` (+ `lib_stack.sh`) | contrôle d'isolation, lecture seule |
| `config/settings/prod.py`, `core/demo_data.py`, `core/management/commands/seed_marche_demo.py` | garde-fou démo ; liste d'hôtes de prod en source unique (`core/demo_data.py:PRODUCTION_HOSTS` / `has_production_host`) |
| `Dockerfile` | `useradd -m -d /home/hayaflash` (F-118) |
| `infra/nginx/prod.conf` | `resolver 127.0.0.11 valid=10s ipv6=off;`, `set $hf_upstream "web:8000";`, 6 × `proxy_pass http://$hf_upstream;`, bloc `upstream` supprimé |
| `config/settings/base.py`, `core/management/commands/send_test_email.py` | e-mail lu dans l'environnement ; commande de test |
| `infra/scripts/deploy_vps.sh` | déploiement manuel outillé en 7 étapes |
| Tests | `core/tests_security_settings.py` (+9), `core/tests_send_test_email.py` (4), `core/tests_nginx_dynamic_upstream.py` (4), `core/tests_private_token_logs.py` (1 attente adaptée) |

**Lot 2 — sauvegardes**

| Fichier | Changement |
|---|---|
| `infra/scripts/backup.sh` | réécrit : `<dossier_pile> [--dry-run]` ; `pg_dump -Fc`, médias, `SHA256SUMS`, écriture atomique, rétention 14 j + 8 dimanches, `rclone` optionnel, journal |
| `infra/scripts/restore_test.sh` | réécrit : PostgreSQL jetable isolé, « RESTAURATION OK » |
| `infra/scripts/restore.sh` | nouveau : vraie restauration, double confirmation |
| `infra/scripts/windows/pull_backups.ps1` | nouveau : copie vers D: |
| `infra/cron/hayaflash-backup`, `infra/scripts/backup_nightly.sh` | cron `sam` prod à 03:17 UTC ; `backup_nightly.sh` marqué obsolète et adapté à la nouvelle signature |
| Docs | `docs/SAUVEGARDES.md` (nouveau), `docs/RUNBOOK_JOUR_J.md` (réaligné), `docs/releases/POINT_PRE_PROD.md` § 5, `docs/releases/v1.0.0-rc1.md` (F-01, F-63, F-83, F-117, F-118 → 🔄 ; nouveau F-146) |

## 2. Décisions prises

- **Un seul compose, un `.env` par clone** : le nom de projet porte l'isolation. Les volumes et le réseau prennent le nom du projet (`hayaflash-prod_postgres_data`, `hayaflash-prod_default`…) sans rien déclarer de plus, ce qui garde les noms du staging inchangés.
- **Garde-fou démo = erreur au démarrage** (D1 recommandée), dans `prod.py` ; la liste d'hôtes n'existe qu'une fois (`core/demo_data.py`).
- **beat sans healthcheck** (`disable: true`) : aucune sonde fiable (pas de pidfile ; `celery inspect ping` ne cible que les workers). Sa vivacité est visible via le check `celery` de `/health/` (battement émis par beat + consommé par le worker). Sans cette ligne il hériterait du `curl :8000` du Dockerfile et serait toujours « unhealthy ».
- **Nginx : variable + resolver, sans `restart nginx` systématique.** Perte assumée : le `keepalive` vers Gunicorn (il exige un bloc `upstream`) ; une connexion TCP locale par requête est négligeable ici. `deploy_vps.sh` ne redémarre nginx que s'il est arrêté ou si `infra/nginx/prod.conf` change (le gabarit n'est lu qu'au démarrage du conteneur).
- **Deux scripts de déploiement** : `deploy_vps.sh` (manuel, image construite sur le VPS) est le seul à utiliser ; `deploy.sh` (images GHCR, CI en `if: false`) est laissé intact comme demandé.
- **Médias sauvegardés par `exec web tar`** (`web` doit tourner), identique à l'ancien script.
- **Rétention** : dernière sauvegarde de chaque jour (14 jours) + de chaque dimanche (8) ; la plus récente jamais supprimée ; aucune purge si la sauvegarde échoue ; seuls les dossiers conformes avec `SHA256SUMS` sont candidats.
- **Copie hors VPS = disque D:** (décision du porteur) ; `BACKUP_REMOTE` reste vide → avertissement visible à chaque sauvegarde, voulu. Ce n'est pas du 3-2-1 complet (voir `docs/SAUVEGARDES.md` § 4).
- **`restore.sh`** refuse une sauvegarde d'un autre projet (sauf `--allow-other-project`) et n'emploie ni `down -v`, ni `volume rm`, ni `DROP DATABASE`.
- **Hors périmètre, relevé sans correction** : F-146 (scripts mono-pile `deploy.sh`, `smoke_test.sh` défaut 8010, `copy_offsite.sh`, `vps_audit.sh`).

## 3. Preuve que le staging reste identique

Comparaison de `docker compose -f docker-compose.production.yml config` **avant / après**, avec le `.env` type du staging (aucune variable de pile), faite en local (Docker Compose v2.40) :

```
diff before.out after.out
  + healthcheck: disable: true            (beat)
  - test: [CMD, celery, ..., celery@$$HOSTNAME]   timeout: 15s
  + test: [CMD-SHELL, "celery -A config inspect ping -t 10 -d celery@$$HOSTNAME || exit 1"]  timeout: 20s, start_period: 40s   (worker)
  - env_file: ./.env  →  env_file: .env      (même fichier, écriture différente)
```

Inchangés : nom de projet `hayaflash`, port `8020`, image `hayaflash:latest`, volumes `hayaflash_{postgres,redis,media,static}_data`, réseau `hayaflash_default`, commandes, limites, dépendances. Les seules différences sont les healthchecks demandés (F-63). Avec les trois variables de la prod : projet `hayaflash-prod`, port `8021`, image `hayaflash-prod:latest`, volumes et réseau préfixés `hayaflash-prod`.

`check_stack_isolation.sh` éprouvé en local sur deux dossiers factices : staging OK, prod OK, prod avec le `.env` du staging → 10 violations et code 1, staging pointant vers la prod → violations et code 1. `nginx -t` OK sur la nouvelle `prod.conf` (`nginx:1.27-alpine`).

**À rejouer sur le VPS** (voir § 5, étape 2) pour comparer le compose réel du staging : la commande exacte y est donnée.

## 4. Vérifications faites en local

- `ruff check . --select E,F,W --ignore E501` : propre sur les fichiers suivis. (Le dépôt local contient un fichier non suivi `Telecharger-Images.py`, qui n'est pas du Python et génère 308 erreurs : il n'est pas à moi et n'est pas commité.)
- Tests : `pytest --ds=config.settings.test` complet → **1720 passed, 4 skipped** (avant le dernier commit de documentation, sans effet sur le code).
- **Essai réel en local** (Docker Desktop, projet jetable `hftest-prod`, supprimé ensuite ; la pile de développement `hayaflash` de ce poste n'a pas été touchée) : image construite avec le nouveau Dockerfile (`HOME=/home/hayaflash`, aucune erreur « Control server »), `worker` **healthy** en `CMD-SHELL`, `beat` sans statut, **F-83 prouvé** (IP de `web` changée 172.25.0.6 → .8 : nginx répond 200 sans redémarrage), `backup.sh` réel (dump `-Fc`, médias, SHA256) puis `restore_test.sh` → **RESTAURATION OK** (52 tables, conteneur jetable supprimé), sauvegarde corrompue → refus (`empreintes invalides`, code 1), `restore.sh` refuse une sauvegarde d'un autre projet, rétention vérifiée avec 41 dossiers factices.
- `deploy_vps.sh` : seul `--dry-run` a été joué (sur un clone local), pas le déploiement réel ; un `git checkout` en cours de route ne peut pas casser le script (tout est dans une fonction).
- `shellcheck` : non disponible sur ce poste (ni Windows, ni Git Bash) → relecture soignée, `bash -n` sur chaque script, et essais réels de `check_stack_isolation.sh`.
- `pull_backups.ps1` : syntaxe validée par le parseur PowerShell ; **non exécuté de bout en bout** (il faut le VPS et la clé SSH).

## 5. Commandes VPS à jouer, dans l'ordre, par le porteur

> Chaque action sur le VPS demande ta validation (CLAUDE.md). Aucune ne touche `symain.africa` / `services.symain.africa`. Utilisateur : `sam`.

**Staging d'abord**

1. Mettre la branche à disposition (après revue et merge dans `main`, ou en testant la branche) :
   ```bash
   cd /srv/hayaflash && git fetch origin
   ```
2. Comparer le compose réel du staging (lecture seule) — **avant** de rien changer :
   ```bash
   cd /srv/hayaflash
   docker compose config > /tmp/staging-avant.yml
   git checkout --detach origin/main            # ou la branche à tester
   docker compose -f docker-compose.production.yml config > /tmp/staging-apres.yml
   diff /tmp/staging-avant.yml /tmp/staging-apres.yml
   ```
   Attendu : seulement les healthchecks worker/beat (et, si l'ancien compose contenait `/srv/hayaflash/.env`, la forme du `env_file`). Le projet, le port 8020, l'image et les volumes `hayaflash_*` doivent être identiques. Si une autre ligne diffère : s'arrêter.
3. Contrôle d'isolation du staging :
   ```bash
   bash infra/scripts/check_stack_isolation.sh /srv/hayaflash
   ```
4. Dossier des sauvegardes puis sauvegarde du staging (essai puis réel) :
   ```bash
   sudo install -d -o sam -m 700 /srv/backups /srv/backups/hayaflash /srv/backups/hayaflash-prod
   bash infra/scripts/backup.sh /srv/hayaflash --dry-run
   bash infra/scripts/backup.sh /srv/hayaflash
   ```
5. Test de restauration sur cette sauvegarde :
   ```bash
   bash infra/scripts/restore_test.sh /srv/backups/hayaflash/<AAAA-MM-JJ_HHMM>
   ```
6. Déploiement du staging avec le nouvel outil (essai puis réel) :
   ```bash
   bash infra/scripts/deploy_vps.sh /srv/hayaflash --dry-run
   bash infra/scripts/deploy_vps.sh /srv/hayaflash
   docker compose ps
   ```
   Attendu : `web` et `worker` « healthy » (beat sans statut), pas de 502 après la recréation de `web`, plus de « Control server error » dans `docker compose logs web`.
7. Contrôles d'e-mail (si le `.env` du staging contient les variables `EMAIL_*`) :
   `docker compose exec web python manage.py send_test_email <votre-adresse>`.

**Puis la production** (suite de `docs/RUNBOOK_JOUR_J.md`, étape 5 bis)

8. Contrôles de référence : codes HTTP de `symain.africa` et `services.symain.africa`, `sudo nginx -t`.
9. `sudo install -d -o sam -m 755 /srv/hayaflash-prod && git clone <url> /srv/hayaflash-prod`, puis créer `/srv/hayaflash-prod/.env` (mode 600) avec `HAYAFLASH_PROJECT=hayaflash-prod`, `HAYAFLASH_HTTP_PORT=8021`, `DOCKER_IMAGE=hayaflash-prod`, nouveaux secrets, `EMAIL_*`, **sans** `HAYAFLASH_ALLOW_DEMO_SEED`.
10. `bash /srv/hayaflash-prod/infra/scripts/check_stack_isolation.sh /srv/hayaflash-prod` (doit afficher `✓ Isolation OK`).
11. `bash /srv/hayaflash-prod/infra/scripts/deploy_vps.sh /srv/hayaflash-prod --dry-run`, puis sans `--dry-run` ; créer le superutilisateur ; `send_test_email`.
12. Sauvegarde de la prod, puis **`restore_test.sh` → `RESTAURATION OK`** (obligatoire avant l'ouverture) ; installer la ligne `crontab` de `infra/cron/hayaflash-backup`.
13. Sur le PC : clé SSH dédiée, `pull_backups.ps1 -SimulationSeulement`, puis réel, puis la tâche planifiée (`docs/SAUVEGARDES.md` § 5).
14. Vhost HestiaCP de `hayaflash.com` → `127.0.0.1:8021` (`sudo nginx -t` avant chaque rechargement).
15. Contrôles après : `symain.africa` et `services.symain.africa` répondent comme au point 8, `nginx -t`, `/health/` de la prod, `check_stack_isolation.sh` des deux piles.
