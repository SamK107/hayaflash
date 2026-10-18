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

Conventions : l'utilisateur d'exploitation est **`sam`** (celui qui lance Docker ;
**il n'existe aucun utilisateur système `hayaflash`**). Deux piles vivent sur le
même VPS, chacune dans son propre clone git avec son propre `.env` :

| | Staging | Production |
|---|---|---|
| Dossier | `/srv/hayaflash` | `/srv/hayaflash-prod` |
| Projet Compose | `hayaflash` | `hayaflash-prod` |
| Port local | `127.0.0.1:8020` | `127.0.0.1:8021` |
| Image | `hayaflash:latest` | `hayaflash-prod:latest` |
| Volumes / réseau | `hayaflash_*` | `hayaflash-prod_*` |
| Domaine | celui du staging | `hayaflash.com` (nginx de HestiaCP) |

`symain.africa` et `services.symain.africa` tournent sur le même VPS : **aucune**
commande de ce runbook ne doit les toucher (voir l'étape 5 bis).

**Règles absolues sur ce serveur partagé** (valables pour tout le runbook) :

- **Jamais** `docker compose down -v`, `docker volume rm`, `docker volume prune` ni
  `docker system prune` (ni `docker image prune -a`) : ils détruisent des volumes ou des
  images d'autres piles (staging, prod, sites voisins). Pour arrêter une pile : `docker compose stop`.
- **`sudo nginx -t` avant tout rechargement** du nginx de HestiaCP (`systemctl reload nginx`),
  puis **vérifier `symain.africa` et `services.symain.africa`** (code HTTP identique à celui
  noté avant). Si `nginx -t` échoue : ne rien recharger, corriger ou annuler d'abord.
- Le `.env` de la **prod** ne contient **jamais** `HAYAFLASH_ALLOW_DEMO_SEED` ; son
  `ALLOWED_HOSTS` contient `localhost` (le healthcheck du conteneur interroge `localhost`).
- Un `docker compose restart` **ne relit pas** le `.env` : pour appliquer un changement de
  variable, recréer les conteneurs avec `deploy_vps.sh` (ou `up -d --force-recreate`).
Déploiement : `infra/scripts/deploy_vps.sh <dossier_pile>` (manuel outillé).
L'ancien `infra/scripts/deploy.sh` (images GHCR) ne sert plus tant que les jobs
`deploy-*` de GitHub Actions sont en `if: false`.

---

## Étape 1 — Audit en lecture seule du VPS (catégorie 7, F-39)

> ℹ️ Le VPS est **partagé** avec `symain.africa` et `services.symain.africa` : le
> pare-feu, SSH et HestiaCP sont communs. Cette étape ne **modifie rien** (l'ancienne
> version installait ufw, fail2ban et durcissait `sshd` : supprimé, voir F-39). Toute
> évolution du pare-feu ou de SSH est une décision séparée, validée par le mainteneur
> pour cette action précise.

- [ ] **1.1 Audit de départ (lecture seule)**
  ```bash
  cd /srv/hayaflash
  sudo bash infra/scripts/vps_audit.sh > audit-avant-$(date +%F).md
  ```
  Attendu : un rapport Markdown, avec une synthèse ✅/❌/⚠️ à la fin. Les ❌ de
  cette étape servent de liste de travail. Le script ne modifie rien.
  Retour arrière : aucun (lecture seule).

- [ ] **1.2 Prérequis de la production (lecture seule)**
  ```bash
  bash infra/scripts/check_prod_prereqs.sh
  ```
  Attendu : aucun `ECHEC` (DNS de `hayaflash.com` et `www`, seuls 22/80/443/8083
  ouverts au public, ports 8020/8021 en `127.0.0.1`, PostgreSQL d'hôte non exposé,
  disque et mémoire suffisants, `symain.africa` et `services.symain.africa` en HTTPS).
  Relire chaque `ATTENTION`. Le script ne modifie rien.

- [ ] **1.3 Référence avant toute intervention sur l'hôte**
  ```bash
  sudo nginx -t
  curl -s -o /dev/null -w '%{http_code}
' https://symain.africa/
  curl -s -o /dev/null -w '%{http_code}
' https://services.symain.africa/
  ```
  Attendu : `syntax is ok` / `test is successful` et deux `200`. À refaire **après**
  toute action sur le nginx de HestiaCP.

**Ce que ce runbook ne fait pas** : installer ou reconfigurer `ufw`, `fail2ban`,
`unattended-upgrades` ou `sshd_config` sur ce serveur.

---

## Étape 2 — `.env` + secrets GitHub

- [ ] **2.1 Fichier de secrets du VPS**
  ```bash
  install -m 600 /dev/null /srv/hayaflash/.env       # en tant que sam
  nano /srv/hayaflash/.env                           # à partir de .env.example
  ```
  Minimum requis : `ENVIRONMENT=prod` (ou `staging`), `SECRET_KEY`,
  `ALLOWED_HOSTS`, `DATABASE_URL` ou `DB_*`, `REDIS_URL`, `PROD_DOMAIN`, les
  clés Orange Money, variables e-mail `EMAIL_*` (`.env.example`).
  **Ne pas** définir `CSP_REPORT_ONLY` (défaut `true`, voir étape 6).
  Attendu : `stat -c '%a %U' /srv/hayaflash/.env` → `600 sam`.
  Retour arrière : éditer le fichier. Il n'est jamais commité.

- [ ] **2.2 Registre d'images**
  ```bash
  docker login ghcr.io   # jeton GitHub read:packages (seulement si le flux GHCR est réactivé)
  ```
  Attendu : `Login Succeeded`.
  Retour arrière : `docker logout ghcr.io`.

- [ ] **2.3 Secrets GitHub** (Settings → Environments `staging` / `production`) :
  `STAGING_HOST`, `STAGING_USER`, `STAGING_SSH_KEY` ; plus tard `PROD_HOST`,
  `PROD_USER`, `PROD_SSH_KEY`, `PROD_DOMAIN`. La clé SSH est une clé
  **dédiée au déploiement**, jamais la clé personnelle.
  Attendu : secrets visibles (valeurs masquées) dans chaque environnement.
  Retour arrière : supprimer le secret, puis retirer la clé publique de
  `~sam/.ssh/authorized_keys`.

---

## Étape 3 — Déploiement : **manuel outillé** (catégorie 6)

Le déploiement continu GitHub Actions reste en pause (`if: false`, voir CLAUDE.md
point 10). On déploie à la main avec un script unique qui enchaîne contrôle
d'isolation, sauvegarde, revue des changements, construction, migrations,
vérification de `/health/` et affichage du retour arrière.

- [ ] **3.1 Essai à blanc (staging)**
  ```bash
  cd /srv/hayaflash && git fetch origin
  bash infra/scripts/deploy_vps.sh /srv/hayaflash --dry-run
  ```
  Attendu : les 7 étapes affichées, rien de modifié.
- [ ] **3.2 Déploiement réel (staging)**
  ```bash
  bash infra/scripts/deploy_vps.sh /srv/hayaflash
  ```
  Attendu : liste des commits et des changements sensibles, confirmation à taper
  (`oui`), puis `✓ Deploiement termine`. À **chaque** déploiement, après la recréation de
  `web`, le script crée le conteneur `nginx` s'il manque, puis lance `nginx -t` et
  `nginx -s reload` dedans (si `nginx -t` échoue : aucun rechargement et échec clair —
  c'est ce qui évite le 502 constaté le 18/10 quand le dépôt était déjà sur le commit cible). `docker compose ps` : tous les services
  `healthy` (web, worker) ; `beat` n'a volontairement pas de healthcheck.
- [ ] **3.3 Vérification externe**
  ```bash
  curl -s https://<domaine-staging>/health/
  ```
  Attendu : `"status": "ok"`, `database` et `cache` à `ok`, et `celery` à `ok`
  dans les ~2 minutes (`missing` juste après le démarrage est normal).
  Retour arrière : la commande exacte est imprimée à la fin de `deploy_vps.sh`
  (retour au commit précédent + tag `<image>:previous`).
  ⚠️ Les migrations sont forward-only : un retour d'image ne défait pas une migration.

---

## Étape 4 — Observabilité (catégories 1, 2, 4)

- [ ] **4.1 Sentry** : un projet Sentry **distinct** pour la prod (celui du
  staging garde son propre DSN). Ajouter **à la main** la ligne `SENTRY_DSN=...`
  dans `/srv/hayaflash-prod/.env` (600), puis recréer les conteneurs avec
  `bash infra/scripts/deploy_vps.sh /srv/hayaflash-prod` : un simple `restart`
  **ne relit pas** le `.env`.
  Puis déclencher une erreur de test (`cd /srv/hayaflash-prod && docker compose -f docker-compose.production.yml
  exec -T web python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('test prod')"`) et vérifier dans
  Sentry : l'événement arrive avec `environment: prod`, **sans** numéro de
  téléphone, e-mail ni variable locale (filtre `config/settings/_sentry.py`).
  Retour arrière : retirer `SENTRY_DSN`, puis recréer les services
  (`deploy_vps.sh`).
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

Tout est détaillé dans `docs/SAUVEGARDES.md`. Ordre imposé par l'ADR-0001
(décision 4) : on ne planifie rien tant qu'une restauration réelle n'a pas réussi.

- [ ] **5.1 Dossier des sauvegardes** (une fois) :
  `sudo install -d -o sam -m 700 /srv/backups /srv/backups/hayaflash /srv/backups/hayaflash-prod`
- [ ] **5.2 Sauvegarde manuelle (staging d'abord)**
  ```bash
  bash /srv/hayaflash/infra/scripts/backup.sh /srv/hayaflash --dry-run
  bash /srv/hayaflash/infra/scripts/backup.sh /srv/hayaflash
  ```
  Attendu : `✓ Sauvegarde terminee`, un dossier `AAAA-MM-JJ_HHMM` en `700` avec
  `db.dump`, `media.tar.gz`, `backup.info`, `SHA256SUMS`, une ligne `OK` dans
  `backup.log`, et l'avertissement « sauvegarde locale uniquement » (voulu).
- [ ] **5.3 Restauration réelle (test)**
  ```bash
  bash /srv/hayaflash/infra/scripts/restore_test.sh /srv/backups/hayaflash/<AAAA-MM-JJ_HHMM>
  ```
  Attendu : `RESTAURATION OK` (base jetable isolée, supprimée ; aucune pile touchée).
- [ ] **5.4 Copie chiffrée vers le disque D: du PC** : `docs/SAUVEGARDES.md` § 5 (paire de clés
  `age` dont la clé privée est **hors du PC**, clé SSH dédiée, `pull_backups.ps1`, tâche
  planifiée) puis le test manuel du § 8.
  Attendu : `AAAA-MM-JJ_HHMM.tar.age` sur D: (SHA256 validés avant chiffrement), **aucun fichier
  en clair** sur D:, `decrypt_backup.ps1` redonne `OK` avec la clé de secours. Les sauvegardes du
  VPS restent en clair sur le VPS.
- [ ] **5.5 Planification (prod seulement, après l'étape 5 bis)** : ligne `crontab` de
  `infra/cron/hayaflash-backup` (installation sans écraser la crontab de `sam`).
  Attendu : le lendemain, `/srv/backups/hayaflash-prod/backup.log` montre `OK`.
  Retour arrière : `crontab -l | grep -v '# hayaflash-prod-backup' | crontab -`.
- [ ] **5.6 Audit de fin de journée**
  ```bash
  sudo bash infra/scripts/vps_audit.sh > audit-jourJ-$(date +%F).md
  ```
  Attendu : plus aucun ❌. Coller le rapport dans `GOVERNANCE_SECURITE.md`
  (catégories 2, 5, 7) et mettre à jour « Dernière vérification ».

---

## Étape 5 bis — Créer la pile de production isolée (PP-04)

> Ne rien exécuter ici sans validation explicite du mainteneur pour chaque
> action (CLAUDE.md « Release readiness »). Le staging n'est pas modifié par
> cette étape ; `symain.africa` et `services.symain.africa` non plus.

- [ ] **5b.1 Contrôle de référence (avant)**
  ```bash
  for u in https://symain.africa https://services.symain.africa; do curl -s -o /dev/null -w "%{http_code} $u\n" "$u"; done
  sudo nginx -t
  ```
  Attendu : le code habituel pour les deux sites, `nginx -t` OK. Noter les codes.
- [ ] **5b.2 Clone et `.env` propres à la prod**
  ```bash
  sudo install -d -o sam -m 755 /srv/hayaflash-prod
  git clone <url-du-depot> /srv/hayaflash-prod
  cd /srv/hayaflash-prod && git checkout --detach origin/main
  install -m 600 /dev/null .env && nano .env     # à partir de .env.example
  ```
  Dans ce `.env` : `ENVIRONMENT=prod`, `HAYAFLASH_PROJECT=hayaflash-prod`,
  `HAYAFLASH_HTTP_PORT=8021`, `DOCKER_IMAGE=hayaflash-prod`, `IMAGE_TAG=latest`,
  `PROD_DOMAIN=hayaflash.com`, `ALLOWED_HOSTS=hayaflash.com,www.hayaflash.com,localhost`,
  `CSRF_TRUSTED_ORIGINS=https://hayaflash.com,https://www.hayaflash.com`, **nouveau**
  `SECRET_KEY`, **nouveaux** mots de passe `DB_PASSWORD` / `REDIS_PASSWORD`, clés
  Orange Money de production, `EMAIL_*`. **Sans `HAYAFLASH_ALLOW_DEMO_SEED`**
  (la prod refuse de démarrer s'il vaut `1`). Ne rien copier du `.env` du staging.
- [ ] **5b.3 Contrôle d'isolation**
  ```bash
  bash /srv/hayaflash-prod/infra/scripts/check_stack_isolation.sh /srv/hayaflash-prod
  bash /srv/hayaflash/infra/scripts/check_stack_isolation.sh /srv/hayaflash
  ```
  Attendu : `✓ Isolation OK` deux fois ; prod = projet `hayaflash-prod`, port 8021,
  image `hayaflash-prod:latest`, volumes et réseau en `hayaflash-prod_*`.
- [ ] **5b.3 bis Sauvegarde fraîche du staging, AVANT de démarrer la prod**
  ```bash
  bash /srv/hayaflash/infra/scripts/backup.sh /srv/hayaflash
  ```
  Attendu : `✓ Sauvegarde terminee` et un dossier `AAAA-MM-JJ_HHMM` tout récent dans
  `/srv/backups/hayaflash/`. Ne pas démarrer la prod sans cette sauvegarde du staging.
- [ ] **5b.4 Premier déploiement**
  ```bash
  bash /srv/hayaflash-prod/infra/scripts/deploy_vps.sh /srv/hayaflash-prod --dry-run
  bash /srv/hayaflash-prod/infra/scripts/deploy_vps.sh /srv/hayaflash-prod
  ```
  Puis créer le compte administrateur :
  `docker compose --project-directory /srv/hayaflash-prod -f /srv/hayaflash-prod/docker-compose.production.yml exec web python manage.py createsuperuser`.
  Attendu : pas de sauvegarde (aucune base encore), `/health/` OK sur `127.0.0.1:8021`.
  Test e-mail : `… exec web python manage.py send_test_email <votre-adresse>`.
- [ ] **5b.4 bis Vérifier les volumes (8 attendus) — juste après ce premier démarrage**
  ```bash
  docker volume ls --format '{{.Name}}' | grep '^hayaflash' | sort
  docker volume ls --format '{{.Name}}' | grep -c '^hayaflash'
  ```
  Attendu : **8** volumes — 4 de staging (`hayaflash_postgres_data`, `hayaflash_redis_data`,
  `hayaflash_media_data`, `hayaflash_static_data`) et 4 de prod (`hayaflash-prod_postgres_data`,
  `hayaflash-prod_redis_data`, `hayaflash-prod_media_data`, `hayaflash-prod_static_data`).
  **Si le compte n'est pas 8 : arrêt immédiat** — ne rien supprimer, **jamais `-v`** —
  (`docker compose … stop` de la pile prod seulement), puis analyse avec le mainteneur
  (une pile partageant ou écrasant les volumes de l'autre est la panne la plus grave possible).
- [ ] **5b.5 Sauvegarde et test de restauration AVANT l'ouverture** :
  étapes 5.2, 5.3 et 5.4 sur `/srv/hayaflash-prod` (chemin `/srv/backups/hayaflash-prod`).
  Attendu : `RESTAURATION OK` sur la sauvegarde de la prod. **Pas d'ouverture sans cela.**
- [ ] **5b.6 Domaine** (F-65, F-145) : vhost HestiaCP de `hayaflash.com` en `proxy_pass` vers
  `127.0.0.1:8021` (modèle copié, aucun fichier Hestia existant modifié).
  1. Créer le domaine dans HestiaCP **sans `access_log`** (le journal d'accès de l'hôte
     contiendrait les URL privées ; ne **pas** appliquer `hestia_masque_jeton.conf` tant que
     l'hôte ne journalise pas) et ajouter l'alias `www.hayaflash.com` (étape 5 ter) ;
  2. activer SSL (Let's Encrypt, `www` inclus) ;
  3. relire le vhost **généré** (`/home/admin/conf/web/hayaflash.com/nginx.conf` et
     `nginx.ssl.conf`) : Hestia a déjà réintroduit trois fois un bloc `location /media/ { alias … }`
     parasite et remis `proxy_pass` sur un port par défaut (8002/8010) après chaque
     modification faite dans le panneau — corriger vers `127.0.0.1:8021` et supprimer ce bloc ;
  4. `sudo nginx -t` **avant** chaque rechargement ; vérifier `symain.africa` et
     `services.symain.africa` juste après ;
  5. **après toute future modification de ce domaine dans le panneau Hestia**, refaire les points
     3 et 4 (le panneau régénère le vhost).
- [ ] **5b.7 Contrôle de non-régression (après)**
  ```bash
  for u in https://symain.africa https://services.symain.africa; do curl -s -o /dev/null -w "%{http_code} $u\n" "$u"; done
  sudo nginx -t
  curl -s https://hayaflash.com/health/
  bash /srv/hayaflash/infra/scripts/check_stack_isolation.sh /srv/hayaflash
  ```
  Attendu : mêmes codes qu'en 5b.1 pour `symain.africa` et `services.symain.africa`,
  `nginx -t` OK, `/health/` de la prod `ok`, staging toujours isolé et en service.
  Retour arrière : `docker compose … stop` de la pile prod seulement (jamais `down -v`) ;
  retirer le vhost copié puis `sudo nginx -t && sudo systemctl reload nginx`.
- [ ] **5b.8 IP réelle du client (F-26)** — de bout en bout :
  ```bash
  curl -s -o /dev/null -H 'X-Forwarded-For: 203.0.113.7' http://127.0.0.1:8021/health/
  docker compose --project-directory /srv/hayaflash-prod -f /srv/hayaflash-prod/docker-compose.production.yml logs --tail 3 nginx
  ```
  Attendu : la ligne de journal commence par `203.0.113.7` (pas par l'adresse de la passerelle
  Docker `172.x.0.1`). Puis, **depuis un téléphone sur le réseau mobile**, ouvrir le site et vérifier
  que le journal du conteneur nginx montre l'IP publique du téléphone, pas celle du serveur.
  Resserrer ensuite `HF_REAL_IP_FROM` dans le `.env` de la prod sur le sous-réseau réel
  (`docker network inspect hayaflash-prod_default`) et recréer `nginx` avec `deploy_vps.sh`.
  Sans cela, les limites par IP et les verrous partageraient une seule clé pour tous les clients.
- [ ] **5b.9 Test fonctionnel des numéros hachés (F-98), sur le staging** : passer une
  commande de test, puis `docker compose … logs web | grep 'tel:'` ne doit montrer que
  `tel:<16 caractères hexadécimaux>` (jamais le numéro en clair) ; recommander plusieurs
  fois avec le même numéro doit déclencher la limite par numéro. Consigner le résultat dans le
  suivi (`v1.0.0-rc1.md`, F-98).

---

## Étape 5 ter — Hôtes : `www`, HSTS prudent, staging non indexable (D8, D14)

- [ ] **5 ter.1 `www.hayaflash.com` est redirigé vers `hayaflash.com`** (301, chemin et
  requête conservés) par l'application (`core.middleware.CanonicalHostMiddleware`, réglage
  `CANONICAL_HOST_REDIRECTS` de `config/settings/prod.py`). Pour que cela marche :
  1. le domaine `www.hayaflash.com` doit être **déclaré dans HestiaCP** comme **alias** du
     domaine `hayaflash.com` (même vhost → même `proxy_pass` vers `127.0.0.1:8021`) ;
  2. le **certificat Let's Encrypt** du domaine doit **couvrir `www`** (cocher « SSL » pour
     l'alias ; sinon le navigateur affiche une erreur de certificat avant la redirection) ;
  3. `ALLOWED_HOSTS` de la prod contient `hayaflash.com`, `www.hayaflash.com` **et
     `localhost`** (le healthcheck du conteneur interroge `localhost`) ;
  4. enregistrement DNS `A` pour `www` (voir `docs/releases/PREREQUIS_PROD.md`).
  Vérification : `curl -sI https://www.hayaflash.com/f/x/?a=1` → `301` et
  `Location: https://hayaflash.com/f/x/?a=1`.
  Après toute modification du vhost dans HestiaCP : `sudo nginx -t`, relire le vhost généré
  (F-65), vérifier `symain.africa` et `services.symain.africa`.
- [ ] **5 ter.2 HSTS prudent** : `max-age` de 180 jours, **sans** `includeSubDomains` ni
  `preload` (Django et Nginx du conteneur). Vérification :
  `curl -sI https://hayaflash.com/ | grep -i strict-transport` → `max-age=15552000` seul.
  Ne pas soumettre le domaine à la liste de préchargement HSTS avant plusieurs mois stables.
- [ ] **5 ter.3 Staging non indexable** : aucun réglage à faire. Sur tout hôte **qui n'est
  pas** un hôte de production (`hayaflash.com`, `www.hayaflash.com`), l'application sert un
  `robots.txt` qui interdit tout (sans `Sitemap`) et ajoute `X-Robots-Tag: noindex, nofollow`
  à chaque réponse. Vérification sur le staging :
  `curl -sI https://<hote-staging>/ | grep -i x-robots-tag` ; sur la prod, **aucune** ligne
  `X-Robots-Tag`. Garde-fou : `HAYAFLASH_NOINDEX=1` avec un hôte de production empêche le
  démarrage.

---

## Étape 6 — Critères d'ouverture (décisions D12 et D15)

Critères avant d'ouvrir la prod (D12 : **48 à 72 h** de stabilité sur le staging, au lieu de 7 jours) :

- 48 à 72 h sans erreur Sentry nouvelle non traitée, `/health/` vert en continu
  (UptimeRobot), une nuit de sauvegarde réussie, et **zéro violation CSP** remontée par
  `CSP_REPORT_URI` sur les parcours réels (acheteur + vendeur) ;
- le **scénario complet joué sur de vrais téléphones** (inscription vendeuse, création d'une
  vente, commande acheteuse, livraison, paiement d'abonnement Orange Money à 100 FCFA,
  note vocale, QR code, « M'alerter ») ;
- une **restauration réussie** : `restore_test.sh` sur une sauvegarde récente de la prod
  (`RESTAURATION OK`) et le test de la copie chiffrée sur D: (`docs/SAUVEGARDES.md` § 8).

**Ordre d'ouverture (D15)** : (1) les vendeuses pilotes d'abord, (2) puis le public, (3) puis le
programme partenaires. Chaque étape est une décision explicite du mainteneur.

- [ ] **6.1 Déploiement prod** : **manuel** (D11) avec
  `bash infra/scripts/deploy_vps.sh /srv/hayaflash-prod`. Ne **pas** retirer `if: false` de
  `deploy-prod` dans GitHub Actions : le job ferait `cd /srv/hayaflash` et déploierait sur la pile
  staging.
  Attendu : `/health/` prod `ok`, nginx rechargé après `nginx -t`.
  Retour arrière : la commande imprimée par `deploy_vps.sh` (étape 3.3).
- [ ] **6.2 CSP en mode bloquant** : **seulement si 0 violation** sur la
  période. Ajouter `CSP_REPORT_ONLY=false` dans le `.env` **prod**, puis
  redémarrer `web`.
  Attendu : l'en-tête devient `Content-Security-Policy` (plus `-Report-Only`).
  Parcours à rejouer à la main : accueil, `/ventes/`, `/f/<slug>/` (commande +
  tiroir, alerte), connexion, tableau de bord vendeur, création de vente,
  Publication rapide, abonnement, installation PWA. Console sans « Refused to… ».
  Retour arrière (immédiat, sans redéploiement) : retirer
  `CSP_REPORT_ONLY=false` du `.env`, puis redémarrer `web`.
