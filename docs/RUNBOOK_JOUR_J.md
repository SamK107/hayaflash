# Runbook — jour J du déploiement VPS

> Checklist ordonnée pour mettre HayaFlash en ligne sur le VPS, créée au sprint
> gouvernance B (26/09/2026). Elle solde les 🔍 de `GOVERNANCE_SECURITE.md`
> (catégories 1, 2, 5, 6, 7). On la suit **dans l'ordre**, en cochant au fur et
> à mesure. Chaque étape donne la commande exacte, le résultat attendu et le
> retour arrière.
>
> Règles :
> - On ne passe à l'étape suivante que si le résultat attendu est obtenu.
> - Aucune étape n'est irréversible sans le dire explicitement.
> - Le jour même, on colle les preuves (sorties de commande) dans
>   `GOVERNANCE_SECURITE.md` et on met à jour « Dernière vérification ».

Conventions : `hayaflash` désigne l'utilisateur d'exploitation (celui qui lance
Docker) et `/srv/hayaflash` le dossier du dépôt déployé. Si l'un des deux
diffère, l'adapter partout, y compris `HAYAFLASH_DIR` pour le script d'audit.

---

## Étape 1 — Audit initial + durcissement (catégorie 7)

- [ ] **1.1 Audit de départ (lecture seule)**
  ```bash
  cd /srv/hayaflash
  sudo bash infra/scripts/vps_audit.sh > audit-avant-$(date +%F).md
  ```
  Attendu : un rapport Markdown, avec une synthèse ✅/❌/⚠️ à la fin. Les ❌ de
  cette étape servent de liste de travail. Le script ne modifie rien.
  Retour arrière : aucun (lecture seule).

- [ ] **1.2 Pare-feu**
  ```bash
  sudo apt install -y ufw
  sudo ufw default deny incoming && sudo ufw default allow outgoing
  sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
  sudo ufw enable
  ```
  Attendu : `sudo ufw status verbose` affiche `Status: active` et
  `deny (incoming)`.
  ⚠️ **Avant `ufw enable`, garder une deuxième session SSH ouverte** : si SSH
  est coupé, c'est elle qui permet de corriger.
  Retour arrière : `sudo ufw disable`.

- [ ] **1.3 fail2ban**
  ```bash
  sudo apt install -y fail2ban && sudo systemctl enable --now fail2ban
  ```
  Attendu : `sudo fail2ban-client status sshd` liste la jail sshd.
  Retour arrière : `sudo systemctl disable --now fail2ban`.

- [ ] **1.4 SSH par clé uniquement, root interdit**
  Vérifier d'abord qu'une connexion **par clé** avec l'utilisateur
  d'exploitation fonctionne, puis dans `/etc/ssh/sshd_config.d/99-hayaflash.conf` :
  ```
  PermitRootLogin no
  PasswordAuthentication no
  ```
  ```bash
  sudo sshd -t && sudo systemctl reload ssh
  ```
  Attendu : `sudo sshd -T | grep -Ei 'permitrootlogin|passwordauthentication'`
  → `no` / `no`. Tester une **nouvelle** connexion SSH avant de fermer
  l'ancienne.
  Retour arrière : supprimer `99-hayaflash.conf`, puis `sudo systemctl reload ssh`.

- [ ] **1.5 Mises à jour de sécurité automatiques**
  ```bash
  sudo apt install -y unattended-upgrades
  sudo dpkg-reconfigure -plow unattended-upgrades   # répondre Oui
  ```
  Attendu : `/etc/apt/apt.conf.d/20auto-upgrades` contient
  `APT::Periodic::Unattended-Upgrade "1";`.
  Retour arrière : `sudo dpkg-reconfigure -plow unattended-upgrades` → Non.

---

## Étape 2 — `.env` + secrets GitHub

- [ ] **2.1 Fichier de secrets du VPS**
  ```bash
  sudo install -m 600 -o hayaflash -g hayaflash /dev/null /srv/hayaflash/.env
  sudo -u hayaflash nano /srv/hayaflash/.env    # à partir de .env.example
  ```
  Minimum requis : `ENVIRONMENT=prod` (ou `staging`), `SECRET_KEY`,
  `ALLOWED_HOSTS`, `DATABASE_URL` ou `DB_*`, `REDIS_URL`, `PROD_DOMAIN`, les
  clés Orange Money, `OFFSITE_DIR`, `BACKUP_HEARTBEAT_URL` (étape 5).
  **Ne pas** définir `CSP_REPORT_ONLY` (défaut `true`, voir étape 6).
  Attendu : `stat -c '%a %U' /srv/hayaflash/.env` → `600 hayaflash`.
  Retour arrière : éditer le fichier. Il n'est jamais commité.

- [ ] **2.2 Registre d'images**
  ```bash
  sudo -u hayaflash docker login ghcr.io   # jeton GitHub read:packages
  ```
  Attendu : `Login Succeeded`.
  Retour arrière : `docker logout ghcr.io`.

- [ ] **2.3 Secrets GitHub** (Settings → Environments `staging` / `production`) :
  `STAGING_HOST`, `STAGING_USER`, `STAGING_SSH_KEY` ; plus tard `PROD_HOST`,
  `PROD_USER`, `PROD_SSH_KEY`, `PROD_DOMAIN`. La clé SSH est une clé
  **dédiée au déploiement**, jamais la clé personnelle.
  Attendu : secrets visibles (valeurs masquées) dans chaque environnement.
  Retour arrière : supprimer le secret, puis retirer la clé publique de
  `~hayaflash/.ssh/authorized_keys`.

---

## Étape 3 — Déploiement continu : **staging seulement** (catégorie 6)

- [ ] **3.1** Dans `.github/workflows/deploy.yml`, retirer la ligne `if: false`
  du job `deploy-staging` **uniquement**. `deploy-prod` garde `if: false`
  (étape 6). Passer par une PR, comme d'habitude.
  Attendu : au merge, le run `Deploy` enchaîne `test → build → deploy-staging`
  et passe au vert. `deploy.sh` lance `smoke_test.sh` et fait un rollback
  automatique en cas d'échec.
- [ ] **3.2 Vérification**
  ```bash
  curl -s https://<domaine-staging>/health/
  ```
  Attendu : `"status": "ok"`, `database` et `cache` à `ok`, et `celery` à
  `ok` dans les ~2 minutes qui suivent le démarrage de worker et beat
  (`missing` juste après le démarrage est normal).
  Retour arrière : remettre `if: false` sur `deploy-staging` (PR). Pour
  revenir à l'image précédente sur le VPS :
  ```bash
  cd /srv/hayaflash
  DOCKER_IMAGE=ghcr.io/<org>/hayaflash HAYAFLASH_TAG=$(cat .deploy_last_good_tag) \
    bash infra/scripts/deploy.sh http://localhost:8000
  ```
  ⚠️ Les migrations sont forward-only : un retour d'image ne défait pas une
  migration.

---

## Étape 4 — Observabilité (catégories 1, 2, 4)

- [ ] **4.1 Sentry** : `SENTRY_DSN=...` dans `/srv/hayaflash/.env`, puis
  redéployer (ou `docker compose -f docker-compose.production.yml up -d web worker beat`).
  Attendu : l'événement de test apparaît dans Sentry avec la bonne étiquette
  `environment:` (staging/prod).
  Retour arrière : retirer `SENTRY_DSN`, puis redémarrer les services.
- [ ] **4.2 Règles d'alerte Sentry** (dashboard) : e-mail sur nouvelle erreur
  `environment:prod`, et sur les `logger.error` suivants :
  - webhooks paiement (catégorie 8) ;
  - `Healthcheck: battement Celery perime` / `aucun battement Celery` (nouveau, sprint B).
  Attendu : une alerte de test reçue sur un canal réellement lu.
- [ ] **4.3 Endpoint CSP** : Sentry → Project Settings → Security Headers →
  copier l'URL « Report URI » dans `CSP_REPORT_URI=...` (`.env`), puis
  redémarrer `web`.
  Attendu : `curl -sI https://<domaine>/ | grep -i content-security` contient
  `report-uri https://...sentry.io/...`. On reste en **Report-Only** : les
  violations sont remontées, rien n'est bloqué.
  Retour arrière : retirer `CSP_REPORT_URI`.
- [ ] **4.4 Monitoring externe** : UptimeRobot (ou équivalent), sonde HTTPS
  sur `https://<domaine>/health/` toutes les 5 minutes, mot-clé `"status":"ok"`,
  alerte e-mail.
  Attendu : sonde « Up ». Couper `web` 5 minutes en heure creuse doit
  déclencher l'alerte.
  Retour arrière : mettre la sonde en pause.
  Note : `/health/` reste en 200 si seul Celery est en panne
  (`HEALTH_CELERY_REQUIRED=false`). Celery est surveillé via Sentry (4.2).
  Pour une alerte UptimeRobot sur Celery, utiliser une sonde mot-clé
  `"celery":"ok"` plutôt que de passer `HEALTH_CELERY_REQUIRED` à `true`.

---

## Étape 5 — Sauvegardes : manuel → restauration → cron (catégorie 5)

Ordre imposé par l'ADR-0001 (décision 4) : on ne planifie rien tant qu'une
restauration réelle n'a pas réussi.

- [ ] **5.1 Chiffrement** : `sudo apt install -y age`. Sur **ton poste**
  (jamais sur le VPS) : `age-keygen -o hayaflash-backup.key` → gestionnaire
  de mots de passe, puis `age-keygen -y hayaflash-backup.key` → copier la clé
  **publique** dans `/srv/hayaflash/backup_recipients.txt`.
  Attendu : l'audit (1.1) passe « Clé publique age présente, aucune clé
  privée » à ✅.
- [ ] **5.2 Disque hors-site** : brancher et monter le disque sur
  `OFFSITE_DIR`, puis **une seule fois** :
  `sudo -u hayaflash touch "$OFFSITE_DIR/.hayaflash_backup_target"`.
  Attendu : `mountpoint "$OFFSITE_DIR"` → `is a mountpoint`.
- [ ] **5.3 Sauvegarde manuelle**
  ```bash
  sudo -u hayaflash bash /srv/hayaflash/infra/scripts/backup_nightly.sh
  ```
  Attendu : `✓ Sauvegarde terminee`, des fichiers `.age` sur le disque
  externe, et un ping reçu sur healthchecks.io si `BACKUP_HEARTBEAT_URL` est défini.
- [ ] **5.4 Restauration réelle**
  ```bash
  cd /srv/hayaflash
  DB_USER=hayaflash bash infra/scripts/restore_test.sh "$(ls -t backups/db_*.sql.gz | head -1)"
  ```
  Attendu : restauration OK dans une base éphémère, supprimée à la fin (la base
  servie n'est jamais touchée). Pour tester aussi une copie hors-site :
  `age -d -i hayaflash-backup.key` sur ton poste, puis `restore_test.sh`.
- [ ] **5.5 Planification + heartbeat**
  ```bash
  sudo install -m 644 -o root -g root infra/cron/hayaflash-backup /etc/cron.d/hayaflash-backup
  sudo install -d -m 750 -o hayaflash -g hayaflash /srv/hayaflash/logs
  ```
  Attendu : le lendemain, `/srv/hayaflash/logs/backup.log` montre la nuit
  passée, et healthchecks.io a reçu le ping (sinon il alerte).
  Retour arrière : `sudo rm /etc/cron.d/hayaflash-backup`.

- [ ] **5.6 Audit de fin de journée**
  ```bash
  sudo bash infra/scripts/vps_audit.sh > audit-jourJ-$(date +%F).md
  ```
  Attendu : plus aucun ❌. Coller le rapport dans `GOVERNANCE_SECURITE.md`
  (catégories 2, 5, 7) et mettre à jour « Dernière vérification ».

---

## Étape 6 — Après N jours stables sur staging (décision explicite)

Critères avant d'ouvrir la prod : au moins 7 jours sans erreur Sentry
nouvelle non traitée, `/health/` vert en continu (UptimeRobot), une nuit de
sauvegarde réussie, et **zéro violation CSP** remontée par `CSP_REPORT_URI`
sur les parcours réels (acheteur + vendeur).

- [ ] **6.1 Déploiement prod** : retirer `if: false` sur `deploy-prod` (PR).
  Attendu : `deploy-staging → deploy-prod` au vert, `/health/` prod `ok`.
  Retour arrière : remettre `if: false`, puis revenir à l'image précédente comme en 3.2.
- [ ] **6.2 CSP en mode bloquant** : **seulement si 0 violation** sur la
  période. Ajouter `CSP_REPORT_ONLY=false` dans le `.env` **prod**, puis
  redémarrer `web`.
  Attendu : l'en-tête devient `Content-Security-Policy` (plus `-Report-Only`).
  Parcours à rejouer à la main : accueil, `/ventes/`, `/f/<slug>/` (commande +
  tiroir, alerte), connexion, tableau de bord vendeur, création de vente,
  Publication rapide, abonnement, installation PWA. Console sans « Refused to… ».
  Retour arrière (immédiat, sans redéploiement) : retirer
  `CSP_REPORT_ONLY=false` du `.env`, puis redémarrer `web`.
