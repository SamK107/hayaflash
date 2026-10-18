# Point de gouvernance avant la mise en production

> Établi le 2026-10-17 sur `main` à `1b5dbd5` (Feat/marche vitrine, #82), en **lecture seule** :
> aucun code modifié, rien exécuté sur le VPS. Sources : `CLAUDE.md`, `docs/releases/v1.0.0-rc1.md`,
> `GOVERNANCE_RELEASE.md`, `docs/RUNBOOK_JOUR_J.md`, `docs/INCIDENTS.md`, comptes rendus
> `docs/releases/reports/`, `docker-compose.production.yml`, `Dockerfile`, `.env.example`,
> `.github/workflows/deploy.yml`, `config/settings/prod.py`, `infra/`.
> Aucune valeur secrète n'est recopiée ici.
> Catégories : **BLOQUANT** (avant production) · **Avant ouverture** (avant ouverture au public) · **Après prod**.
> Effort : S (< ½ jour) · M (≈ 1 jour) · L (> 1 jour ou délai externe).

## 0. Constats d'ensemble

1. Le suivi `v1.0.0-rc1.md` s'arrête à F-145 (#77). Les PR #78 à #82 n'y ont **aucun finding** ; les
   phases P2, P3, P5, P6, P7 y sont encore en ⬜ (sauf F-123 : paiement réel de 100 FCFA du 13/10 sur
   staging). Le dernier `release_check` (29/09) est en **ÉCHEC** (couverture ≥ 90 % et pip-audit).
   Sans mise à jour, un Go/No-Go (P7-1) n'est pas décidable.
2. Le dépôt suppose **une seule pile** sur le serveur (détail en PP-04) : `env_file` figé sur
   `/srv/hayaflash/.env`, port 8020, `-p hayaflash` dans les scripts, chemins `/srv/hayaflash`.
   Un `docker compose` de production lancé tel quel depuis le dépôt chargerait les secrets **de staging**.
3. Staging et production se déclarent tous deux `prod` (`docker-compose.production.yml:15-16`,
   `config/settings/prod.py:15`) : mêmes réglages et même étiquette Sentry (PP-09).
4. Le registre mentionne des statuts « codé, en attente de déploiement » (F-115, F-121, F-122, F-127,
   F-137, F-141, F-142, F-144) : F-144 est sur la branche de #76, déployée sur staging ; **statuts à
   reconfirmer sur staging** avant de les compter.

## 1. État de la release depuis le dernier point du registre (#77, 16/10)

| PR / commit | Date | Contenu |
|---|---|---|
| #76 `c8d96a5` | 15/10 | Chantier « avant prod 1 » : F-98 (empreinte HMAC), F-129, F-133, F-144 (notes vocales protégées, `X-Accel-Redirect`), déployé sur staging |
| #77 `b169bec` | 16/10 | Suivi : déploiements du 13 au 16/10, F-123 fermé (paiement réel 100 FCFA, 13/10), F-131, F-132, F-145, RM-30 |
| #78 `ac794dc` | 16/10 | Accueil : section vidéo « Découvrez HayaFlash en 2 minutes » |
| #79 `e5cebd8` | 17/10 | Guide : carrousel « Ta première vente flash, étape par étape » |
| `b1e87ca` | 17/10 | Le Marché phase 1 : `/ventes/` vivant (comptes à rebours, tiroir M'alerter, état calme) |
| `9cbdc98`, `1ff9f9a`, `f1b90b4`, merge `0180f72` | 17/10 | Le Marché phase 2a : indices publics du jour (seuils anti-bruit), sparkline |
| #80 `5853eb8` | 17/10 | Admin : bilans vendeurs (liste des boutiques, fiche mensuelle, comparaison, signaux, résumé) |
| #81 `ee03d30` | 17/10 | Seed de démo enrichi, staging contrôlé (`HAYAFLASH_ALLOW_DEMO_SEED`), accès visible au Marché |
| #82 `1b5dbd5` | 17/10 | Vitrine produits du Marché : miniatures WebP 200/480 px, entrée accueil, cartes « En direct » |

## 2. Travaux restants

### 2.1 BLOQUANT avant production

| ID | Sujet | Qui | Effort | Source |
|---|---|---|---|---|
| PP-01 | **Garde-fou `HAYAFLASH_ALLOW_DEMO_SEED`** : refuser de démarrer si la variable vaut `1` et qu'un hôte de production est dans `ALLOWED_HOSTS` (voir § 2.5). Aujourd'hui seule la commande `seed_marche_demo` est gardée ; le démarrage de l'application ne l'est pas, et `demo_data_visible()` (`core/demo_data.py:23`) rendrait visibles les boutiques de démo | Claude Code (code + tests) ; porteur (checklist) | S | point du 17/10 ; `core/demo_data.py`, `seed_marche_demo.py:10` |
| PP-02 | **Base de production sans donnée de démo** (comptes `+22379990…`, clients `+22378880…`) : contrôle à faire avant ouverture et à ajouter à la checklist | Porteur | S | point du 17/10 ; § 3 étape 7 |
| PP-03 | **Compose du VPS ≠ dépôt ?** `diff` du fichier réellement exécuté sur staging contre `docker-compose.production.yml` (noms de volumes/réseau explicites annoncés, healthchecks worker/beat, etc.) ; tout écart devient un finding | Porteur (lance), Claude Code (analyse) | S | point du 17/10 ; § 3 étape 2 |
| PP-04 | **Pile prod isolée** : projet `hayaflash-prod`, port 8021, volumes/réseau suffixés `-prod`, `env_file` propre, sous-réseau fixé. Points mono-pile du dépôt : `docker-compose.production.yml:12` (`name`), `:20`, `:48`, `:124` (`/srv/hayaflash/.env`), `:132` (8020), `:134` (chemin relatif de `prod.conf`) ; `-p hayaflash` dans `deploy.sh:30`, `backup.sh:29`, `restore_test.sh:21` ; `/srv/hayaflash` dans `backup.sh:30`, `backup_nightly.sh:23`, `copy_offsite.sh:49,51`, `infra/cron/hayaflash-backup:16`, `vps_audit.sh:35`. Génération du compose par copie réécrite + contrôles (`hfp config`, volumes, réseaux), sans `down -v` | Les deux | M | procédure donnée dans la conversation du 16-17/10 ; F-21 |
| PP-05 | **Ne jamais casser `symain.africa` / `services.symain.africa`** : `sudo nginx -t` avant tout rechargement, contrôle HTTP des deux sites avant et après, aucun fichier Hestia existant modifié (copies de modèles seulement) | Porteur | S | point du 17/10 ; CLAUDE.md « Release readiness » |
| F-145 / F-65 | Domaine `hayaflash.com` dans Hestia **sans `access_log`**, modèle de proxy copié (port 8021), certificat Let's Encrypt, **vérifier que Hestia ne régénère pas le vhost** (bloc `/media/` parasite, `proxy_pass` remis à un port par défaut, observé 3 fois le 02/10) ; ne pas appliquer `hestia_masque_jeton.conf` | Porteur | M | registre F-145, F-65 |
| F-26 / P4-7 | IP réelle du client derrière le double proxy : `set_real_ip_from` (commenté, `prod.conf:93`) à renseigner avec la passerelle du **nouveau** sous-réseau, `TRUSTED_PROXY_NETWORKS` resserré ; vérifier de bout en bout (sinon limites par IP et verrous `axes` partagés par tous) | Les deux | M | registre F-26 (bloquant, décision 29/09) |
| F-21 | Clore : port dédié. `8010` encore cité dans `prod.conf:50`, `smoke_test.sh:14`, `deploy.yml:125-130`, `RUNBOOK_JOUR_J.md:133` (réel : 8020 staging, 8021 prod) | Claude Code | S | registre F-21, P4-5 |
| F-83 | Après recréation de `web`, `nginx` garde l'ancienne IP → 502. Correctif durable : `resolver 127.0.0.11 valid=10s` + `proxy_pass` via variable dans chaque `location` de `infra/nginx/prod.conf` (perte du `keepalive` de l'upstream à mesurer) ; à défaut, `restart nginx` dans la séquence de déploiement. `/health/` répond 405 à HEAD (sonde externe) | Claude Code | M | registre F-83 ; point du 17/10 |
| F-63 = F-117 | Healthchecks `worker`/`beat`. Constat dépôt : `beat` n'en a pas et hérite du `curl :8000` du Dockerfile ; `worker` est en forme `CMD` avec `celery@$$HOSTNAME`, jamais résolu (`docker-compose.production.yml:147-152`). Correctif : `beat` → `healthcheck: disable: true`, `worker` → `CMD-SHELL`. **Catégorie** : maintenue BLOQUANT (3 lignes) car le statut Docker doit être fiable pour les contrôles du jour J ; **F-117 est un doublon de F-63, à fermer** | Claude Code | S | registre F-63, F-117 ; point du 17/10 |
| F-59 | Stock réservé sans expiration : expiration faite (`fix/expiration-stock`), **plafond de commandes non honorées par numéro en attente de décision** ; contrepartie du relèvement des limites à 120/min | Porteur (décision), Claude Code | M | registre F-59, P7-8 |
| F-37 / RM-33 | Durées de conservation annoncées dans la politique de confidentialité sans purge implémentée : aligner le texte sur la réalité (option retenue) | Claude Code (texte), porteur | S | registre F-37, `privacy.html:90-93` |
| F-98 | Test fonctionnel sur staging de l'empreinte HMAC des numéros (déployé par #76) | Porteur | S | registre F-98 |
| PP-06 | **Sauvegardes de la base de production** : aucune n'existe pour la pile prod. Le dépôt livre les scripts mais le cron est « PAS ENCORE INSTALLÉ » (`infra/cron/hayaflash-backup:1`) et tous visent `/srv/hayaflash` ; staging utilise `/home/sam/hf-backup-db.sh` (hors dépôt, non lu). À faire : script prod (dump + médias, écriture atomique), cron décalé, **restauration réelle testée**, copie hors-site chiffrée (`age`) ou limite 3-2-1 assumée par écrit | Les deux | M | GS-5.1 à 5.8, ADR-0001, runbook étape 5 |
| PP-07 | **Identifiants Orange Money de production** : fournis par l'environnement (`_orange.py`), jamais copiés de staging si celui-ci est en bac à sable ; **URLs retour/annulation/notification de `hayaflash.com` enregistrées chez Orange** (CLAUDE.md « URLs stables enregistrées ») ; paiement réel de 100 FCFA rejoué sur la prod (P6-1 à P6-4), tarif spécial épuisé ensuite | Porteur | M | CLAUDE.md ; `RUNBOOK_TEST_PAIEMENT.md` ; F-123 (staging fait) |
| PP-08 | **Sentry de production distinct** : `environment="prod"` est figé (`prod.py:15`) ; un second projet/DSN évite de mélanger les erreurs de staging (coût : S) ; option code : lire l'étiquette dans une variable | Porteur (projet), Claude Code | S | `config/settings/prod.py:15` |
| PP-09 | **Environnement de production** (§ 2.4) : `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `REDIS_URL`, `SECRET_KEY`, `APP_RELEASE` = SHA (F-40), `LEGAL_*` complets, `CSP_REPORT_ONLY=true`, **aucune** variable de démo ; corriger `.env.example` (`app.hayaflash.com` → `hayaflash.com`, exemples `ALLOWED_HOSTS`/`CSRF`) | Porteur ; Claude Code (`.env.example`) | S | `prod.py`, `.env.example:72,141,182` |
| PP-10 | **Go / No-Go outillé** : relancer `scripts/release_check.py` (dernier = ÉCHEC : couverture, pip-audit), gitleaks sur l'historique complet, ZAP baseline sur staging, mise à jour des phases P2 à P7 du suivi avec preuves | Les deux | M | `v1.0.0-rc1.md` P0-3, P2-x, P3-2 à P3-4, P7-1 à P7-5 |
| PP-11 | **Textes légaux validés par un juriste** (CGU, confidentialité, mentions) | Porteur | L (délai externe) | RM-32, P5-5, `terms.html:3` |
| PP-12 | **Runbook aligné sur le VPS réel** (§ 3.2) et séquence de déploiement manuelle écrite | Claude Code | M | F-39, F-10, point du 17/10 |
| F-39 | Étape 1 du runbook (ufw, fail2ban, `sshd_config`) **à ne pas exécuter** sur le VPS partagé : remplacer par l'audit en lecture seule | Claude Code | S | registre F-39 |

### 2.2 Avant ouverture au public

| ID | Sujet | Qui | Effort | Source |
|---|---|---|---|---|
| PP-13 | **Staging non indexable** : `templates/robots.txt` autorise tout et annonce le sitemap, aucune en-tête `X-Robots-Tag` dans `prod.conf` ni (à vérifier) dans l'hôte. Ajouter `X-Robots-Tag: noindex, nofollow` sur le vhost staging (hôte) ; mot de passe HTTP **seulement** avec exemption du webhook Orange et de `/billing/` (sinon les paiements de test échouent). **À faire dès maintenant** | Porteur (Hestia) | S | P4-9, point du 17/10 |
| PP-14 | **Politique de confidentialité et CGU** : ajouter l'analyse des ventes des boutiques pour les bilans mensuels et conseils, et l'analyse de résumés anonymisés par des outils d'IA (aucune mention aujourd'hui : recherche `bilan`, `IA` dans `templates/core/legal/` sans résultat). Entreprise individuelle : aucune occurrence de « SUARL », 5 de « individuelle » dans les pages légales | Claude Code (rédaction), porteur / juriste (validation) | S | point du 17/10 ; RM-30, #75 |
| PP-15 | **Déployer sur staging** ce qui est « codé » : F-115 (témoignages retirés ; **F-82 est le même sujet, à fermer**), F-121, F-122, F-127, F-137, F-141, F-142 | Porteur | S | registre |
| F-81 / F-88 | « M'alerter » : promesse partielle ; clés Orange SMS vides ; envois SMS en appel direct (jusqu'à 10 s par échec). Décision : activer le SMS (puis F-88 devient bloquant) ou retirer la promesse | Porteur (décision), Claude Code | M | registre F-81, F-88 |
| F-01 | **E-mail** : `base.py:356-360` ne lit que `EMAIL_BACKEND` et `DEFAULT_FROM_EMAIL` ; `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_SSL`, identifiants **ne sont pas lus** : la cible SMTP LWS (`mail.hayaflash.com`, 465 SSL) ne peut pas être configurée. Le code n'envoie aucun e-mail aujourd'hui | Claude Code (si e-mail voulu) ; porteur (SPF/DKIM/DMARC, P5-3/4) | S à M | registre F-01 |
| F-05 / P3-O2 | Code OTP dormant : `print` du code en clair (`accounts/services/sms.py:6`) | Claude Code | S | registre F-05 |
| F-57 | Enregistrement vocal : repli `audio/ogg` sur Safari/iOS à tester | Porteur (test iPhone), Claude Code | M | registre F-57 |
| F-60 | `/f/<slug>/interest/` : une inscription par appel, sans dédoublonnage | Claude Code | S | registre F-60 |
| F-62 | Webhook Orange : un `status` non SUCCESS passe un paiement en FAILED sans vérification active | Claude Code | S | registre F-62 |
| F-71 / F-78 | `max_orders` jamais appliqué ; fonctions annoncées dans les plans mais non bloquées par plan ou sans code | Porteur (décision), Claude Code | M | registre F-71, F-78 |
| F-97 | Carte « Commandes livrées » affiche toutes les commandes (`analytics_dashboard.html:26`) | Claude Code | S | registre F-97 |
| F-38 | Tests de charge (locust) absents, avant le premier live promu | Claude Code | L | registre F-38 |
| F-144 | Notes vocales : rejouer sur la prod (200, `Accept-Ranges`, accès direct `/media/delivery/audio/` = 404) ; statut du registre à corriger | Porteur | S | registre F-144 |
| PP-16 | Bilans admin — points ouverts à trancher : pas de statut « refusé » sur `Order` (classé « échec de livraison »), « livrée non encaissée » hors alerte 20 %, critère « vente réalisée » = début de vente dans le mois | Porteur | S | `reports/admin-bilans-A.md` § Points ouverts 1 à 4 |
| PP-17 | Marché : test réel sur téléphone (bandeau, tiroir, faible bande passante) | Porteur | S | `reports/marche-phase1.md` § Points ouverts |
| **Partenaires** | F-104, F-105, F-106, F-110, F-112, F-113, F-116, F-137, F-141, F-142 : « avant ouverture aux partenaires » (lot juriste, scan du QR sur staging, gel de la migration `0001`) ; F-129, F-133 : test fonctionnel à faire | Les deux | L | registre |

### 2.3 Après production

| ID | Sujet | Qui | Effort | Source |
|---|---|---|---|---|
| PP-18 | Sous-titre du Marché : « Bamako » en dur (`templates/flash_sales/public_calendar.html:3,184`, `analytics/seller_public.html:3`) à rendre dépendant de la ville/du pays | Claude Code | S | point du 17/10 ; F-87 |
| PP-19 | Miniatures WebP non purgées à la suppression d'un produit hors seed | Claude Code | S | `reports/marche-vitrine.md` |
| PP-20 | Vraies photos de produits pour la démo (le catalogue du seed est optionnel) | Porteur | M | point du 17/10 |
| PP-21 | « Stock qui dort » des bilans utilise le stock actuel ; normaliser les téléphones clients pour « déjà clientes » ; meilleur créneau limité aux commandes du mois | Claude Code | M | `reports/admin-bilans-B.md` § Limites ; `-A.md` point 5 |
| PP-22 | Idées validées : ventes privées pour clientes fidèles (PRO), suggestions « produit d'appel », accompagnement automatisé du tableau de bord vendeur | Les deux | L | point du 17/10 |
| PP-23 | Paramétrer le dépôt pour plusieurs piles (`HF_STACK_DIR`, port, nom de projet) et les scripts `backup*`, `deploy`, `restore_test` | Claude Code | M | PP-04 |
| Décisions connues | Pas d'heure de livraison promise (phase 2b du Marché abandonnée, 17/10) ; régularisation APDP après les premiers revenus | — | — | point du 17/10 |
| Registre | F-11 (relecteurs requis si le déploiement automatique est réactivé), F-23 (récupération de compte, V2), F-24, F-27, F-28, F-30, F-32, F-33, F-34, F-43, F-44, F-45, F-47, F-48, F-49, F-51, F-55, F-58 (sans objet en prod : aucun ancien fichier), F-64, F-69, F-73, F-74, F-76, F-77, F-79, F-80, F-87, F-93, F-96, F-108, F-111, F-114, F-118 (`HOME`, `Dockerfile:51`, avec la PR de F-63), F-119, F-120, F-124, F-131, F-132, F-136, F-139 | selon le cas | S à M | registre |

### 2.4 Contrôle de la configuration de production (lecture de `prod.py` et `.env.example`)

| Exigence | État |
|---|---|
| `DEBUG=False` | ✅ forcé (`prod.py:17`) ; refus si `DEBUG=true` avec `ENVIRONMENT=prod` (`base.py`) |
| `SECRET_KEY` | ✅ obligatoire, refus de démarrer si vide (`prod.py:29-31`) |
| `ALLOWED_HOSTS` | ✅ obligatoire (`prod.py:35-45`) ; y inclure `localhost,127.0.0.1` pour le healthcheck du conteneur (à confirmer, staging est « healthy ») |
| `REDIS_URL` | ✅ obligatoire en prod (`prod.py:21-26`) |
| `CSRF_TRUSTED_ORIGINS` | ⚠️ lue de l'environnement seulement si renseignée (`prod.py`) : la renseigner pour `hayaflash.com` |
| Identifiants Orange Money | ✅ lus de l'environnement (`_orange.py`), vides dans `.env.example` ; à fournir en production (PP-07) |
| SMTP LWS | ❌ non câblé (F-01) |
| Sentry | ⚠️ `SENTRY_DSN` lu de l'environnement ; étiquette `prod` figée (PP-08) |
| Sauvegardes automatiques | ❌ aucune pour la prod ; cron du dépôt non installé (PP-06) |
| `HAYAFLASH_ALLOW_DEMO_SEED` | ❌ absente de `.env.example`, aucun garde-fou au démarrage (PP-01) |

### 2.5 Garde-fou proposé pour `HAYAFLASH_ALLOW_DEMO_SEED` (non implémenté)

- **Où** : `config/settings/prod.py`, juste après le calcul de `ALLOWED_HOSTS`, dans le style des `ImproperlyConfigured` déjà présents.
- **Quoi** : si `os.environ.get("HAYAFLASH_ALLOW_DEMO_SEED") == "1"` et si `ALLOWED_HOSTS` contient `hayaflash.com` ou `www.hayaflash.com` (**comparaison exacte**, sinon `staging.hayaflash.com` serait refusé), lever `ImproperlyConfigured`. Un check Django seul ne suffit pas : Gunicorn ne le lance pas, seul un échec à l'import des settings empêche le démarrage.
- **Pourquoi pas `ENVIRONMENT`** : staging et prod valent tous deux `prod` (compose figé).
- **En plus** : `demo_data_visible()` renvoie faux si un hôte de production est présent ; commentaire dans `.env.example` : « staging uniquement, jamais en production » ; test sur le modèle de `core/tests_security_settings.py`.

## 3. Checklist du jour J

### 3.1 Dans l'ordre (rattachée au runbook)

| # | Étape | Runbook |
|---|---|---|
| 0 | **J-7 à J-1** : blocants § 2.1 soldés ; DNS (A pour `@` et `www`, TTL 300 s, pas d'AAAA parasite, CAA éventuel) ; identifiants Orange de production et URLs enregistrées ; projet Sentry ; texte juridique validé ; 7 jours de staging sans nouvelle erreur Sentry, `/health/` vert, une nuit de sauvegarde, 0 violation CSP | étape 6 (critères) |
| 1 | **Lecture seule du VPS** : `free -m`, `df -h`, `ss -ltnp`, `docker compose ls`, sous-réseaux Docker libres, `sudo nginx -t` de référence, statut HTTP de `symain.africa` et `services.symain.africa` ; `diff` du compose de staging contre le dépôt (PP-03) | 1.1 (audit seul) |
| 2 | Dossier `/srv/hayaflash-prod` : compose généré (noms `-prod`, port 8021), `prod.conf` avec `set_real_ip_from`, wrapper `hfp` ; `hfp config` ne doit contenir ni `/srv/hayaflash/` ni `8020` | — (nouveau) |
| 3 | `.env` en 600, secrets **neufs** ; **`grep -c '^HAYAFLASH_ALLOW_DEMO_SEED' /srv/hayaflash-prod/.env` = 0** (variable de démo interdite en production) | 2.1 |
| 4 | Domaine Hestia sans `access_log`, certificat, modèle copié ; `sudo nginx -t` **avant** chaque rechargement ; relire le vhost généré (F-65) | — (F-145) |
| 5 | Image au SHA validé sur staging, `migrate`, `collectstatic`, compte équipe ; vérifier les trois `PlanConfig` (migration `0008`) | 3 (adapté) |
| 6 | `restart nginx` après toute recréation de `web` (tant que F-83 n'est pas corrigé) ; `hfp ps` : tous les services `healthy` | — |
| 7 | **Aucune donnée de démo** : `User` dont le téléphone commence par `+22379990` = 0 ; `Order` dont `customer_phone` commence par `+22378880` = 0 ; pas de boutique de démo sur `/ventes/` | — (PP-02) |
| 8 | Isolation : volumes et réseaux de la pile `-prod` seulement ; staging inchangé ; IP réelle vue par Django (F-26) | — |
| 9 | Sauvegarde manuelle, **restauration réelle** sur base éphémère, cron décalé de celui de staging | 5.3, 5.4, 5.5 |
| 10 | Parcours : `/health/`, inscription, paiement Orange 100 FCFA (tarif spécial), webhook et `WebhookLog`, QR de vente, note vocale (200 + `Accept-Ranges`, accès direct = 404) ; fermer le tarif spécial | `RUNBOOK_TEST_PAIEMENT.md` |
| 11 | **Après** : `sudo nginx -t`, `symain.africa` et `services.symain.africa` toujours en 200, Sentry de prod reçoit, sonde externe en place | 4.1 à 4.4 |
| 12 | **J+1** : Sentry, journaux, `/health/`, sauvegarde de la nuit ; CSP **reste en Report-Only** | 6.2 (plus tard) |

### 3.2 Étapes du runbook qui ne correspondent plus au VPS

| Étape | Écart |
|---|---|
| Conventions (`:15-17`), 2.1, 2.2, 5.1 à 5.5 | Utilisateur système `hayaflash` (`sudo -u hayaflash`, `install -o hayaflash`) **inexistant** : le dossier appartient à `sam` |
| 1 (F-39) | Écrite pour un VPS dédié ; ufw/SSH sont communs avec symain : ne pas exécuter |
| 2.2, 2.3, 3 | Suppose GHCR, secrets GitHub et `deploy.sh` ; en réalité : `git checkout --detach origin/main`, `docker build` sur le VPS, `up -d --no-deps web worker beat`, `restart nginx`, `collectstatic` à la main (`deploy.yml` en `if: false`) |
| 3.2 (retour arrière) | Commande avec le port 8010 et une image GHCR ; réel : 8020 (staging) / 8021 (prod) |
| 5 | Chemins `/srv/hayaflash`, cron `hayaflash` ; staging utilise `/home/sam/hf-backup-db.sh` hors dépôt |
| 6.1 | « Retirer `if: false` sur `deploy-prod` » : **dangereux** tant que `deploy.yml:152` fait `cd /srv/hayaflash` (déploierait sur la pile staging) |
| Absent | Création du domaine Hestia (F-145), pile prod séparée, vérification de symain, contrôle d'absence de données de démo |

## 4. Décisions du porteur du projet (toutes prises le 18/10/2026)

| # | Sujet | Décision |
|---|---|---|
| D1 | Garde-fou démo (PP-01) | **Erreur au démarrage** (fait, #84) |
| D2 | Commandes non honorées (F-59) | **Blocage d'un numéro après 3 livraisons refusées ou injoignables en 30 jours** ; déblocage par la vendeuse concernée (sa boutique) et par l'admin (global). Fait : `5e2099e` |
| D3 | SMS « M'alerter » (F-81, F-88) | **Retirer toute promesse de SMS pour le lancement.** Fait : `5e2099e` (envoi inactif sauf `SMS_NOTIFICATIONS_ENABLED=true`) |
| D4 | E-mail (F-01) | **SMTP LWS câblé** (fait, #84) |
| D5 | Sentry | **Projet distinct pour la prod** ; DSN ajouté à la main dans le `.env` de prod (documenté : `RUNBOOK_JOUR_J.md` 4.1, `0486f5f`) |
| D6 | Healthchecks Celery (F-63) | **Corrigés** (fait, #84) |
| D7 | Nginx et IP de `web` (F-83) | **Résolveur Docker + variable** (fait, #84) ; complété par le rechargement systématique de `deploy_vps.sh` (`0486f5f`) |
| D8 | Staging public (PP-13) | **`noindex` seul, sans mot de passe.** Fait : `88a5f85` |
| D9 | Pile prod | **Dépôt paramétré par pile** (fait, #84) |
| D10 | Sauvegardes hors VPS | **Disque D: du PC, chiffrées avec `age`.** Fait : `e372c14` |
| D11 | Déploiement | **Manuel outillé par `deploy_vps.sh`** (fait) |
| D12 | Critères d'ouverture | **48 à 72 h de stabilité sur le staging**, scénario complet sur vrais téléphones, restauration réussie (voir § 7) |
| D13 | Texte juridique | **Lancer avec des textes alignés sur la réalité.** Fait : `88a5f85` |
| D14 | Hôtes | **`www.hayaflash.com` → `hayaflash.com` (301) ; pas de HSTS `preload` ni `includeSubDomains`.** Fait : `88a5f85` |
| D15 | Ordre d'ouverture | **Vendeuses pilotes, puis public, puis programme partenaires** (voir § 7) |
| R1 | Failles `pip-audit` | Mettre à jour vers la version corrigée la plus proche. Constat du 18/10 : **aucune faille connue** (`pip-audit -r requirements.txt` : « No known vulnerabilities found »), rien à mettre à jour |
| R2 | Couverture sous le seuil | **Écrire les tests manquants, ne pas abaisser le seuil.** Fait : `61f62f0` (63 tests) |
| Connue | APDP | Régularisation après les premiers revenus (décision prise, non bloquante) |

### Risques

- **Mémoire** : 8 Gi sur le VPS (P4-2) ; une pile peut réserver jusqu'à 2,5 Go (`mem_limit`) ; staging + prod + symain + bitiki : à mesurer avant (P4-8).
- **Hôte partagé** : un `nginx -t` en échec ou un vhost régénéré touche tous les sites.
- **Statuts du suivi non à jour** : risque d'un Go/No-Go sur des preuves périmées (PP-10).

## 5. Avancement des lots « isolation de la prod » et « sauvegardes » (18/10/2026)

Statut : **fait dans la branche `fix/prod-isolation-sauvegardes`, à valider sur le VPS** (rien n'a été joué sur le VPS). Détail, preuves et commandes dans `docs/releases/reports/prod-isolation-sauvegardes.md`.

| ID | Statut | Preuve (dépôt) |
|---|---|---|
| PP-01 | Fait dans la branche, à valider sur le VPS | `config/settings/prod.py` (`ImproperlyConfigured` « Variable de démo interdite en production ») ; source unique `core/demo_data.py:has_production_host` ; tests `core/tests_security_settings.py` (5 hôtes refusés, prod sans variable, staging avec variable) ; `.env.example` |
| PP-04 | Fait dans la branche, à valider sur le VPS | `docker-compose.production.yml` (`name`, `env_file: .env`, port, image paramétrés) ; `infra/scripts/check_stack_isolation.sh` ; comparaison `docker compose config` avant/après du staging ; `.env.example` |
| PP-06 | Fait dans la branche, à valider sur le VPS | `infra/scripts/backup.sh`, `restore_test.sh`, `restore.sh`, `windows/pull_backups.ps1`, `infra/cron/hayaflash-backup`, `docs/SAUVEGARDES.md`. Copie hors VPS : disque D: du PC (décision du porteur) ; `BACKUP_REMOTE` vide. **Restauration réelle sur la prod : à tester avant l'ouverture** |
| PP-12 | Partiel | `docs/RUNBOOK_JOUR_J.md` réaligné (utilisateur `sam`, deux piles, `deploy_vps.sh`, étape 5 bis) ; reste à confronter au VPS réel |
| F-83 | Fait dans la branche, à valider sur le VPS | `infra/nginx/prod.conf` ; `core/tests_nginx_dynamic_upstream.py` |
| F-63 = F-117 | Fait dans la branche, à valider sur le VPS | `docker-compose.production.yml` (worker `CMD-SHELL`, beat `disable: true`) |
| F-118 | Fait dans la branche, à valider sur le VPS | `Dockerfile` (`HOME` de l'utilisateur applicatif) |
| F-01 | Fait dans la branche, à valider sur le VPS | `config/settings/base.py`, `send_test_email`, tests |

## 6. Statut après les lots « avant production » (18/10/2026)

Branche `release/pre-prod-lots`, un commit par lot : A `0486f5f` · B `61f62f0` · C `5e2099e` · D `88a5f85` · E `e372c14` · F `56a2b00` · G (ce commit). Rien n'a été joué sur le VPS ni poussé. Détail : `docs/releases/reports/pre-prod-lots.md`. « À valider VPS » = code fait dans le dépôt, vérification à jouer par le porteur.

### 6.1 Bloquants (§ 2.1)

| ID | Statut | Preuve / raison |
|---|---|---|
| PP-01 | Fait | #84 (`core/tests_security_settings.py`) |
| PP-02 | Action porteur | Contrôle « aucune donnée de démo » : `RUNBOOK_JOUR_J.md` + `PREREQUIS_PROD.md` § 7 |
| PP-03 | Action porteur | `diff` du compose réel contre le dépôt, à lancer sur le VPS |
| PP-04 | Fait, à valider VPS | #84 ; vérification des 8 volumes : `RUNBOOK_JOUR_J.md` 5b.4 bis (lot G) |
| PP-05 | Documenté | Règles absolues du serveur partagé en tête du runbook (lot G) ; `check_prod_prereqs.sh` (lot F, `56a2b00`) |
| F-145 / F-65 | Procédure écrite, action porteur | `RUNBOOK_JOUR_J.md` 5b.6 (lot G) |
| F-26 | Fait côté dépôt, à valider VPS | `5e2099e` : `set_real_ip_from` actif ; test de bout en bout : runbook 5b.8 |
| F-21 | Fait | `5e2099e` : plus de référence active au port 8010 |
| F-83 | Fait, à valider VPS | #84 ; `0486f5f` (rechargement nginx à chaque déploiement) |
| F-63 = F-117 | Fait, à valider VPS | #84 ; F-117 fermé comme doublon (lot G) |
| F-59 | Fait | `5e2099e` (`orders/tests_unhonored.py`, 22 tests) |
| F-37 / RM-33 | Fait | `5e2099e` (`privacy.html` § 6 aligné sur la réalité) |
| F-98 | Procédure écrite, action porteur | Test fonctionnel staging : runbook 5b.9 |
| PP-06 | Fait, test manuel porteur | #84 ; `e372c14` (copie chiffrée `age`) ; procédure `SAUVEGARDES.md` § 8 |
| PP-07 | Action porteur | `PREREQUIS_PROD.md` § 2 (clés de production, URL `hayaflash.com`) |
| PP-08 | Action porteur (DSN) | `0486f5f` + runbook 4.1 ; projet Sentry distinct à créer |
| PP-09 | Partiel | `.env.example` corrigé (lot G) ; `.env` de prod à remplir par le porteur |
| PP-10 | Fait en partie | `release_check` relancé (lot B / G, voir `v1.0.0-rc1.md` § Rapports) ; gitleaks et ZAP : porteur |
| PP-11 | Décidé (D13) | Textes alignés, validation juridique non bloquante : `88a5f85` |
| PP-12 | Fait | Runbook réaligné (lots A, D, E, F, G) |
| F-39 | Fait | `5e2099e` (étape 1 en lecture seule) |

### 6.2 Avant ouverture (§ 2.2) et autres

| ID | Statut | Preuve / raison |
|---|---|---|
| PP-13 | Fait (à déployer sur staging) | `88a5f85` : `noindex` automatique hors hôte de production (`core/tests_seo_hosts.py`) |
| PP-14 | Fait | `88a5f85` : bilans, IA anonymisée, blocage, Sentry, LWS (`core/tests_legal_reality.py`) |
| PP-15 | Action porteur | Déployer sur staging F-115, F-121, F-122, F-127, F-137, F-141, F-142 ; **F-82 fermé comme doublon de F-115** |
| F-81 / F-88 | Fait | `5e2099e` (D3) |
| F-01 | Fait | #84 |
| PP-23 | Fait | #84 (D9) |
| Autres lignes (F-05, F-57, F-60, F-62, F-71, F-78, F-97, F-38, F-144, PP-16 à PP-22, partenaires) | Inchangées | Hors périmètre des lots |

## 7. Critères d'ouverture (D12 et D15)

**Avant d'ouvrir la production (D12)** — tous requis :

1. **48 à 72 h de stabilité sur le staging** : `/health/` vert en continu, aucune nouvelle erreur Sentry non traitée, une nuit de sauvegarde réussie, zéro violation CSP sur les parcours réels.
2. **Scénario complet sur de vrais téléphones** : inscription vendeuse, création et publication d'une vente, commande acheteuse, mise en livraison et livraison, paiement d'abonnement Orange Money à 100 FCFA (tarif spécial), note vocale, QR code, « M'alerter ».
3. **Restauration réussie** : `restore_test.sh` → `RESTAURATION OK` sur une sauvegarde de la prod, et test de la copie chiffrée sur D: (`SAUVEGARDES.md` § 8).
4. `check_prod_prereqs.sh` sans ÉCHEC ; `sudo nginx -t` OK et `symain.africa` / `services.symain.africa` inchangés.

**Ordre d'ouverture (D15)** : (1) les **vendeuses pilotes** d'abord ; (2) puis le **public** ; (3) puis le **programme partenaires** (lot juriste, scan du QR sur staging, gel de la migration `0001` : voir « Partenaires » en § 2.2). Chaque passage est une décision explicite du mainteneur.

## 8. Ajouts du 18/10/2026 (branche `fix/deploy-nginx-recreate`)

| ID | Sujet | Catégorie | Statut | Registre |
|---|---|---|---|---|
| PP-24 | `deploy_vps.sh` : nginx **recréé** (pas redémarré) quand le compose, `infra/nginx/*` ou l'environnement de nginx changent, après validation dans un conteneur jetable ; sinon `nginx -t` + reload (incident du 18/10 à 12:57, `HF_REAL_IP_FROM`) | BLOQUANT | **Fait** dans cette branche ; exécution réelle sur le VPS à jouer par le porteur | F-152 |
| PP-25 | `Strict-Transport-Security` envoyé deux fois : défini une seule fois, par Django (180 jours, sans `preload` ni `includeSubDomains`) | Avant production | **Fait** dans cette branche | F-153 |
| PP-26 | `/ventes/` sans style après une longue pause de l'onglet (cache vers d'anciens statiques hachés ? service worker `sw.js` ?) | Non bloquant, à diagnostiquer | En attente d'une capture F12 (Réseau, Console) | F-154 |
| PP-27 | Motif d'échec de livraison (refus, injoignable, problème de livraison) ; seuls les deux premiers comptent pour le blocage F-59 | Après phase pilote | À faire | F-155 |
| PP-28 | Jour J : renseigner `LEGAL_ENTITY_RCCM` dans le `.env` de prod et vérifier les pages légales | BLOQUANT (configuration) | Checklist du porteur | F-156 |
| PP-29 | Avant un 2ᵉ pays : la clé du numéro (blocage F-59, limite de débit) doit inclure l'indicatif | Avant ouverture d'un 2ᵉ pays | À faire | F-157 |
