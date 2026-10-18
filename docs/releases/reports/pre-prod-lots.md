# Compte rendu — lots « avant production » (18/10/2026)

Branche `release/pre-prod-lots`, partie de `main` à `0282b97` (#84). Un commit par lot, dans l'ordre.
**Rien n'a été poussé, aucune PR, aucune connexion au VPS, aucun `.env` réel touché, aucun secret dans le dépôt,
aucune migration destructive.** Fichiers non suivis laissés tels quels : `.claude/`, `.coverage`,
`docs/motion-design-*`, `docs/releases/reports/pending/`.

| Lot | Commit | État |
|---|---|---|
| A — Déploiement et Sentry | `0486f5f` | Terminé |
| B — Contrôle de release | `61f62f0` (+ résultat final dans le lot G) | Terminé : contrôle final **OK** |
| C — Findings bloquants | `5e2099e` | Terminé (F-26, F-98, F-65, F-145 : reste une vérification côté VPS) |
| D — Textes légaux, staging, www/HSTS | `88a5f85` | Terminé |
| E — Sauvegardes chiffrées vers D: | `e372c14` | Terminé (non testable sur Windows ici) |
| F — Prérequis de la production | `56a2b00` | Terminé |
| G — Gouvernance et runbook | commit portant ce compte rendu | Terminé |

Aucun lot bloqué. Suite `pytest --ds=config.settings.test` verte à chaque commit (1 726 → 1 854 tests) et
`ruff check . --select E,F,W --ignore E501` propre.

## Lot A — Déploiement et Sentry (`0486f5f`)

- **Fait.** `infra/scripts/deploy_vps.sh` : à **chaque** déploiement, après la recréation de `web`, nginx est créé
  s'il manque, redémarré si `prod.conf` a changé, puis `nginx -t` et `nginx -s reload` dans le conteneur ; si
  `nginx -t` échoue, aucun rechargement et arrêt avec un message clair. `--dry-run` conservé (affiche les
  commandes). Commande de retour arrière mise à jour. Sentry (`config/settings/_sentry.py`) :
  `send_default_pii=False` conservé, `include_local_variables=False`, `before_send` et `before_breadcrumb` qui
  masquent téléphones (internationaux `+223…`, `00223…`, nationaux à 8 chiffres) et e-mails.
  `RUNBOOK_JOUR_J.md` 4.1 : `SENTRY_DSN=` à ajouter à la main, recréation par `deploy_vps.sh` (un `restart` ne relit pas
  le `.env`), erreur de test à vérifier sans donnée personnelle.
- **Tests ajoutés** : `core/tests_sentry_scrub.py` (6). `deploy_vps.sh` : `bash -n` ; pas d'exécution réelle possible ici.
- **Décisions prudentes** : le filtre parcourt tout l'événement sauf des clés techniques (horodatages, identifiants)
  pour ne pas abîmer les dates ; un nombre de 8 chiffres isolé dans un message est masqué (sur-masquage accepté).

## Lot B — Contrôle de release (`61f62f0`)

- **Premier contrôle** (`…_20261018-030209.md`) : **ÉCHEC** uniquement sur la couverture (subscriptions 88,6 %,
  orders 82,3 %, `subscriptions/views.py` 57,0 %, `create_order.py` 84,7 %). `pip-audit` : **aucune faille connue**
  (rien à mettre à jour, R1 sans objet) ; bandit haute 0 / moyenne 8.
- **Tests ajoutés (63)** : `subscriptions/tests_views_billing.py` (23), `orders/tests_seller_actions.py` (12),
  `orders/tests_create_order_validation.py` (9), `orders/tests_public_payload.py` (19). Seuil non modifié.
- **Contrôle final** (`…_20261018-092507.md`, code à `56a2b00`) : **OK** — 2 384 tests PostgreSQL 16, 0 skipped ;
  subscriptions 93,8 %, orders 93,6 %, payments 95,6 %, fichiers critiques ≥ 93,7 % ; `check --deploy` OK ;
  pip-audit OK ; bandit haute 0. Consigné dans `v1.0.0-rc1.md` (P2-1 à P2-5, P3-2, P3-3, Rapports).

## Lot C — Findings bloquants (`5e2099e`)

- **F-59 / D2** : modèles `UnhonoredOrder` et `PhoneUnblock` (migration **additive** `orders/0007`),
  `orders/services/unhonored.py` (constantes `UNHONORED_ORDERS_THRESHOLD = 3`, `UNHONORED_WINDOW_DAYS = 30`),
  enregistrement quand la vendeuse marque une livraison « Échec », vérification dans `submit_public_order_api`
  (1 requête indexée), message « Ce numéro ne peut plus commander pour le moment. Contacte la boutique. »,
  bandeau et bouton « Débloquer ce numéro pour ma boutique » dans les commandes, action admin « Débloquer … (toutes les
  boutiques) ». Tests : `orders/tests_unhonored.py` (22) — blocage au 3ᵉ échec et pas avant, formats de numéro,
  expiration à 30 jours, commande annulée non comptée, déblocage vendeuse et admin, rejeu idempotent, coût en requêtes.
- **F-81 / F-88 / D3** : plus aucune promesse de SMS (plan Pro : valeurs de secours + **migration de données**
  `subscriptions/0010` car le texte est stocké en base ; page réglages vendeuse ; politique de confidentialité).
  Envoi inactif sauf `SMS_NOTIFICATIONS_ENABLED=true` (rappels, confirmation de commande, `send_sms`). « M'alerter » garde
  son libellé exact (« <boutique> vous préviendra sur WhatsApp… », la vendeuse prévient par les liens wa.me) : le bouton
  n'a donc pas été masqué. Tests : `flash_sales/tests_sms_disabled.py` (11).
- **F-26** : `set_real_ip_from ${HF_REAL_IP_FROM};` actif (défaut `172.16.0.0/12`, plages bridge Docker, le port n'étant
  publié que sur `127.0.0.1`). Tests `core/tests_nginx_real_ip.py` (4). **Reste** : vérification de bout en bout sur le VPS.
- **F-21** : références au port 8010 retirées (`smoke_test.sh`, `deploy.yml`, commentaires). **F-37** : politique de
  confidentialité § 6 alignée (aucune purge automatique) ; test mis à jour. **F-39** : étape 1 du runbook réécrite en
  lecture seule.
- **F-117** fermé comme doublon de F-63 ; **F-82** fermé comme doublon de F-115 (statut dans `v1.0.0-rc1.md`, lot G).
- **F-98, F-65, F-145** : relèvent du porteur (test sur staging, vhost Hestia) ; procédures écrites au runbook (5b.6, 5b.9).
- **Décisions prudentes** : « non honorée » = livraison marquée « Échec » (le modèle n'a pas de statut distinct « refusée » /
  « injoignable ») ; le blocage vaut pour **toutes** les boutiques, la vendeuse le lève pour la sienne ; une commande
  ensuite annulée par la vendeuse ne compte plus ; un rejeu idempotent n'est jamais refusé ; message neutre, sans accusation ;
  aucune donnée personnelle ajoutée au journal d'audit du déblocage.

## Lot D — Textes légaux, staging, www/HSTS (`88a5f85`)

- **Textes (D13)** : mentions légales (ABEXPERTISES, entreprise individuelle, RCCM de Bamako, `contact@hayaflash.com`,
  « L'équipe HayaFlash », hébergeur par défaut « LWS (France) », aucun nom ni téléphone), confidentialité et CGU
  (bilans mensuels, résumés anonymisés analysés par des outils d'IA, blocage après 3 échecs en 30 jours, Sentry sans
  données personnelles, paiement à la livraison, abonnements Orange Money, aucune mention de SMS). Date 18/10/2026,
  versions `2026-10`. Registre du vouvoiement conservé (c'était celui des pages). Tests : `core/tests_legal_reality.py` (8)
  — les chiffres du texte sont comparés aux constantes du code.
- **Staging (D8)** : `SITE_NOINDEX` — `robots.txt` interdit tout (sans sitemap) et `X-Robots-Tag: noindex, nofollow` sur
  chaque réponse, **automatiquement sur tout hôte non production** ; prod inchangée ; `HAYAFLASH_NOINDEX=1` avec un hôte de
  production empêche le démarrage. **www/HSTS (D14)** : `CanonicalHostMiddleware` (301, chemin et requête conservés),
  HSTS 180 jours **sans** `includeSubDomains` ni `preload` côté Django **et** Nginx du conteneur (qui envoyait encore
  `preload`), `security.W005/W021` ignorés explicitement. Tests : `core/tests_seo_hosts.py` (20).
- **Décisions prudentes** : le numéro de RCCM vient de l'environnement (jamais inventé) ; la durée HSTS de 180 jours est un
  choix prudent pour un premier lancement (à relever après plusieurs mois stables) ; changer la version des textes
  n'impose aucune ré-acceptation aux comptes existants (la version n'est enregistrée qu'à l'inscription).

## Lot E — Sauvegardes chiffrées vers D: (`e372c14`)

- `pull_backups.ps1` complété (pas réécrit) : prérequis `age`/`tar`/`ssh`, copie `scp` et vérification SHA256 dans un dossier
  temporaire du **disque système**, archive `tar`, chiffrement `age` (clé **publique**), écriture sur D: sous `.tmp-…` puis
  renommage en `AAAA-MM-JJ_HHMM.tar.age`, nettoyage du clair même en cas d'échec, rétention 30 + 12, journal, alerte à 48 h,
  avertissement si d'anciens dossiers en clair traînent sur D:. `decrypt_backup.ps1` ajouté. `docs/SAUVEGARDES.md` : paire de
  clés `age`, clé privée hors du PC, clé SSH, tâche planifiée, restauration depuis D:, **test manuel pas à pas (§ 8)**.
- **Non testé sur Windows** (pas d'`age` ni de VPS ici) : analyse syntaxique PowerShell sans erreur, relecture complète.
  Le test manuel du § 8 est à dérouler par le porteur. Les sauvegardes du VPS restent en clair.

## Lot F — Prérequis de la production (`56a2b00`)

- `infra/scripts/check_prod_prereqs.sh` : strictement en lecture seule — DNS (`dig` sur 1.1.1.1 et 8.8.8.8), `ufw status verbose`,
  ports 8020/8021 en `127.0.0.1` (`ss -ltnp`), PostgreSQL d'hôte (`listen_addresses`, `pg_hba.conf`), disque, mémoire, HTTPS de
  `symain.africa` et `services.symain.africa` ; OK / ATTENTION / ÉCHEC par ligne et résumé. Essayé en local (Git Bash) : les
  contrôles qui exigent Linux sortent en ATTENTION, les sites voisins répondent 200. `docs/releases/PREREQUIS_PROD.md` :
  checklist du porteur.

## Lot G — Gouvernance et runbook (ce commit)

- `POINT_PRE_PROD.md` : D1 à D15, R1, R2 décidées, statut de chaque ligne (§ 6), critères d'ouverture D12/D15 (§ 7).
- `RUNBOOK_JOUR_J.md` : règles absolues du serveur partagé (jamais `down -v`, `volume prune`, `system prune` ; `sudo nginx -t`
  avant tout rechargement puis contrôle de symain), `ALLOWED_HOSTS` de prod avec `localhost`, aucune variable de démo,
  sauvegarde fraîche du staging avant la prod (5b.3 bis), vérification de **8 volumes** `hayaflash*` (5b.4 bis, arrêt sans
  `-v` sinon), vhost Hestia (F-65/F-145), IP réelle (5b.8), test F-98 (5b.9), étape 6 réécrite (D12/D15), déploiement prod
  manuel. `v1.0.0-rc1.md` : statuts et preuves des findings traités, 5 nouveaux findings (F-147 à F-151), rapports.
  `CLAUDE.md` : point 18. `.env.example` : exemples de prod corrigés (`hayaflash.com`).

## Actions du porteur du projet, dans l'ordre

**Sur le PC**
1. Relire la branche (`git log --oneline main..release/pre-prod-lots`), puis la pousser et ouvrir la PR (je n'ai rien poussé).
2. Installer `age` (`winget install FiloSottile.age`), créer la paire de clés, **mettre la clé privée sur une clé USB séparée
   et une copie papier / gestionnaire de mots de passe, puis la retirer du PC** (`docs/SAUVEGARDES.md` § 5.0) ; noter la clé
   publique (`HAYAFLASH_AGE_RECIPIENT`).
3. Créer la clé SSH `ed25519` dédiée (§ 5.1).

**Sur GitHub**
4. Laisser tourner la CI de la PR, fusionner. **Ne pas** retirer `if: false` de `deploy-staging` / `deploy-prod`
   (déploiement manuel, D11).

**Chez LWS / sur les services externes**
5. DNS : enregistrements `A` pour `hayaflash.com` et `www` vers `31.207.39.116`, sans AAAA parasite
   (`PREREQUIS_PROD.md` § 1).
6. Boîte `contact@hayaflash.com` : SMTP, SPF, DKIM, DMARC (§ 4). Projet Sentry **de prod** et son DSN (§ 3). Clés Orange Money
   **de production** et URL de retour / annulation / notification sur `hayaflash.com` (§ 2).

**Sur le VPS — staging**
7. `bash infra/scripts/check_prod_prereqs.sh` (lecture seule) ; traiter tout ÉCHEC.
8. Ajouter la clé publique SSH de sauvegarde dans `~/.ssh/authorized_keys` de `sam`.
9. Déployer le staging : `deploy_vps.sh /srv/hayaflash --dry-run`, puis réel (applique les migrations `orders/0007` et
   `subscriptions/0010`). Vérifier : `/health/`, `X-Robots-Tag: noindex` et `robots.txt` du staging, F-115 / F-121 / F-122 /
   F-127 / F-137 / F-141 / F-142 (PP-15), test F-98 (runbook 5b.9), test F-144 si pas encore fait.
10. Sauvegarde + `restore_test.sh` sur le staging, première copie chiffrée vers D: et test manuel § 8, tâche planifiée Windows.
11. Laisser le staging stable **48 à 72 h** ; jouer le scénario complet sur de vrais téléphones (`POINT_PRE_PROD.md` § 7).

**Pour la production**
12. Dossier `/srv/hayaflash-prod`, `.env` neuf (`ALLOWED_HOSTS=hayaflash.com,www.hayaflash.com,localhost`, `SENTRY_DSN`,
    Orange de production, SMTP, `LEGAL_*`, **sans** `HAYAFLASH_ALLOW_DEMO_SEED`), `check_stack_isolation.sh`.
13. **Sauvegarde fraîche du staging**, puis premier déploiement prod (`deploy_vps.sh /srv/hayaflash-prod`), compte administrateur,
    **vérifier les 8 volumes** (arrêt immédiat sans `-v` sinon).
14. Domaine Hestia sans `access_log`, alias `www`, certificat couvrant `www`, relecture du vhost généré ; `sudo nginx -t` avant
    chaque rechargement ; `symain.africa` et `services.symain.africa` inchangés.
15. IP réelle de bout en bout (5b.8) puis resserrer `HF_REAL_IP_FROM` ; paiement réel à 100 FCFA puis tarif spécial fermé ;
    sauvegarde + `restore_test.sh` de la prod ; cron de sauvegarde.
16. Ouvrir aux **vendeuses pilotes**, puis au public, puis au programme partenaires (D15), chaque étape sur décision explicite.
