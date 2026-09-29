# GOVERNANCE_RELEASE.md — HayaFlash

> Cadre de mise en production : ce qui doit être vrai, prouvé et coché avant
> qu'une version quitte `main` pour le VPS partagé avec services.symain.africa.
> Complète `GOVERNANCE_SECURITE.md` (état de la sécurisation) sans le remplacer.
>
> **Règle d'or : ne jamais casser services.symain.africa, ni la prod HayaFlash
> lors des déploiements futurs.**

---

## 1. Conventions

| Élément | Emplacement |
|---|---|
| Ce cadre (règles, phases, commandes) | `GOVERNANCE_RELEASE.md` (racine) |
| Suivi d'une release (une par version) | `docs/releases/<version>.md` — ex. `docs/releases/v1.0.0-rc1.md` |
| Modèle de suivi à copier | `docs/releases/_TEMPLATE.md` |
| Rapports générés (release_check, gitleaks, ZAP, vps_audit…) | `docs/releases/reports/` |
| Script de contrôle automatisé | `scripts/release_check.py` |
| Outils de contrôle (non installés dans l'image) | `requirements-dev.txt` |

**Statuts** (identiques dans tous les suivis) :

| Statut | Sens |
|---|---|
| ⬜ | À faire / non vérifié |
| 🔄 | En cours (PR ouverte, vérification en cours) |
| ✅ | Fait **et prouvé** |
| ❌ | Vérifié et non conforme |

- Un item ne passe en ✅ qu'avec une **preuve** : fichier:ligne, nom de test,
  n° de PR, chemin d'un rapport dans `docs/releases/reports/`, ou sortie de
  commande collée. Sans preuve, il reste ⬜.
- Les items et findings sont **pré-remplis en ⬜** ; **c'est l'audit qui coche**.
- Chaque finding porte un identifiant stable (`F-NN`), une référence
  fichier:ligne et une décision « bloquant : oui / non / à qualifier ».
  « à qualifier » est tranché par l'audit, jamais par défaut.
- Toute correction passe par une **PR dédiée** (une PR par finding ou par
  lot cohérent), jamais par un commit direct sur `main`.

---

## 2. Phases

Les phases s'enchaînent ; une phase n'est close que lorsque tous ses items
bloquants sont ✅.

### Phase 0 — Gel & hygiène du dépôt

- Plus aucune feature ; seuls les correctifs d'audit entrent, via PR.
- Règle bloquante sur les branches (§3).
- **gitleaks sur tout l'historique : bloquant avant le tag rc** (manuel, §3 bis).
- Le tag `v1.0.0-rc1` n'est posé que lorsque tous les findings bloquants sont
  corrigés (✅ avec PR en preuve).

### Phase 1 — Matrice de traçabilité des gouvernances

Pour **chaque** exigence de **chaque** fichier `GOVERNANCE*` :
exigence → implémentation (fichier:ligne) → test couvrant (nom) → statut → preuve.

- **Tout item sans test est un finding.** Pour une exigence d'exploitation
  (VPS, dashboard Sentry…) qu'aucun test pytest ne peut couvrir, la « preuve
  de substitution » est un rapport daté dans `docs/releases/reports/`
  (ex. sortie de `infra/scripts/vps_audit.sh`) ; le finding reste ouvert
  jusqu'à ce rapport.
- Matrice pré-remplie en ⬜ dans le suivi ; l'audit coche.
- Périmètre : tous les fichiers `GOVERNANCE*` et les documents de gouvernance
  référencés par `CLAUDE.md` et `docs/CODEBASE_STATUS.md`. Le suivi commence
  par un inventaire (fichier → nombre d'exigences extraites, ou raison de
  n'en extraire aucune). Les règles métier sont traitées en premier.
- Chaque exigence cite sa source (fichier:ligne). Une règle appliquée par le
  code mais écrite nulle part dans le dépôt (décision du mainteneur) est
  sourcée « décision mainteneur » et fait l'objet d'un finding de documentation.
- Une contradiction entre deux documents, ou entre un document et le code,
  est un finding.
- Les exigences de `GOVERNANCE_RELEASE.md` lui-même sont suivies par les
  phases 0 à 7 du suivi : elles ne sont pas dupliquées dans la matrice.

### Phase 2 — Backend, données & tests (automatisé : `scripts/release_check.py`)

- `pytest --ds=config.settings.test_pg` sur PostgreSQL 16 — **0 skipped exigé**.
- Couverture ≥ 90 % (hors fichiers de tests) sur `subscriptions/`, `orders/`,
  `payments/` dans leur ensemble, **et fichier par fichier** sur le callback
  Orange Money (`subscriptions/billing_views.py`, `subscriptions/views.py`,
  `subscriptions/services/payment.py`, `subscriptions/services/orange_money.py`),
  chaque fichier de `payments/services/` et `orders/services/create_order.py` ;
  seuil global CI ≥ 60 % conservé.
- `makemigrations --check --dry-run`.
- `migrate` depuis une base vide sur PostgreSQL 16.
- `check --deploy` sur les settings prod, **valeurs factices**.
- Celery worker + beat réels (auto-close d'une vente) — manuel, voir le suivi.

### Phase 3 — Sécurité

pip-audit, bandit (gitleaks : Phase 0) ; auth `/login/` `/register/` ;
IDOR vendeur A/B sur chaque endpoint ; callback Orange Money (montant serveur,
idempotence, aucune activation avant confirmation) ; uploads (6 champs) ;
OTP dormant ; config prod (DEBUG, ALLOWED_HOSTS, cookies, HSTS, CSP) ;
OWASP ZAP baseline sur staging. pip-audit et bandit sont lancés par
`release_check.py` : bandit sévérité **haute bloquante**, sévérité **moyenne
affichée dans le rapport, non bloquante, à relire**.

**Périmètre OTP : hors périmètre V1 — non exposé.** La connexion réelle est
téléphone + mot de passe.

### Phase 4 — Staging isolé sur le VPS & cohabitation avec services.symain.africa

**Topologie retenue (29/09)** : le Nginx de l'hôte (HestiaCP, qui sert
services.symain.africa) garde 80/443 et termine TLS. Le conteneur Nginx
HayaFlash ne publie plus 80/443 : il écoute sur `127.0.0.1:<port dédié>`,
derrière un vhost HestiaCP. L'IP réelle du client doit traverser ce double
proxy (`set_real_ip_from` dans le Nginx conteneur, en-têtes de confiance
uniquement depuis le proxy côté Django), sinon toute limitation par IP
s'applique à une seule adresse partagée par tous les visiteurs.

Backup symain + test de restauration **avant toute intervention** ; inventaire
VPS (RAM, disque, `ss -tlnp`) ; `COMPOSE_PROJECT_NAME` dédié ; PostgreSQL et
Redis dédiés ; port dédié lié à `127.0.0.1` (healthcheck ≠ 8000 si occupé) ;
vhost Nginx séparé, `nginx -t` avant reload ; `mem_limit`/`cpus` ; basic auth
staging ; déploiement au SHA exact (`git checkout <SHA>`, pas `git pull`).

### Phase 5 — Tests fonctionnels sur staging

Playwright : inscription → abonnement → vente → publication rapide → commande
→ paiement → auto-close. Passe exploratoire Claude in Chrome page par page,
mobile + 3G simulée. Email SMTP LWS : envoi réel + SPF/DKIM/DMARC.

### Phase 6 — Paiement réel

Orange Money 100 FCFA via le prix spécial vendeur ; cohérence base / plan
activé / webhook.

### Phase 7 — Go / No-Go puis production

Zéro ❌ bloquant, aucune vulnérabilité critique/haute, tests verts, symain
joignable et sauvegardé, backups HayaFlash actifs, rollback testé, **Required
reviewers** sur l'environnement GitHub `production`, réactivation des jobs
deploy (`if: true`), surveillance J+1 (Sentry, logs, healthcheck).

---

## 3. Règle bloquante de Phase 0 — branches (squash merge)

Les PR sont mergées en *squash* et les branches sont **conservées
volontairement** : `git branch --no-merged` les liste donc toutes, même
intégrées. D'où la règle :

> Au tag rc, toute branche listée par `git branch -a --no-merged main` doit
> (a) correspondre à une PR mergée identifiable dans main, ou (b) donner
> DEJA INTEGREE via `git merge-tree --write-tree main <branche>` comparé à
> `main^{tree}`, ou (c) être explicitement déclarée abandonnée dans le suivi.
> Toute autre branche est bloquante.

Commandes (PowerShell, racine du dépôt ; lecture seule, aucune ne modifie
le dépôt hormis `fetch`) :

```powershell
# Prérequis : git >= 2.38 (merge-tree --write-tree)
git --version

# 1. Références à jour ; main local doit être identique à origin/main
git fetch --all --prune
git rev-parse main origin/main          # les deux SHA doivent être identiques

# 2. Liste brute
git branch -a --no-merged main

# 3. Critère (b) pour chaque branche
$mainTree = (git rev-parse 'main^{tree}').Trim()
$branches = git branch -a --no-merged main --format='%(refname)' |
    Where-Object { $_ -and $_ -ne 'refs/remotes/origin/HEAD' }
foreach ($b in $branches) {
    $out  = git merge-tree --write-tree main $b 2>$null
    $code = $LASTEXITCODE
    $tree = ("$($out | Select-Object -First 1)").Trim()
    if ($code -eq 0 -and $tree -eq $mainTree) { $verdict = 'DEJA INTEGREE' }
    elseif ($code -eq 1)                     { $verdict = 'CONFLITS - A EXAMINER' }
    else                                     { $verdict = 'A EXAMINER' }
    '{0,-70} {1}' -f $b, $verdict
}

# 4. Critère (a) pour une branche restée « A EXAMINER » (gh CLI) :
gh pr list --state merged --head <nom-de-branche-sans-origin/> --json number,title,mergedAt
#    ou, sans gh : rechercher le n° de PR dans l'historique de main
git log main --oneline --grep '(#<numero>)'
```

Lecture : `DEJA INTEGREE` = fusionner la branche dans `main` ne changerait
rien (arbre identique) → critère (b) satisfait. Chaque branche restante est
consignée dans le suivi avec son critère (a), (b) ou (c) ; une branche sans
critère bloque le tag.

### 3 bis. gitleaks — bloquant avant le tag rc (manuel)

```powershell
# gitleaks >= 8.19 (sous-commande « git ») ; rapport caviardé (--redact)
gitleaks version
gitleaks git . --log-opts="--all" --redact --verbose `
  --report-format json `
  --report-path docs/releases/reports/v1.0.0-rc1_gitleaks_AAAAMMJJ.json
# gitleaks < 8.19 : gitleaks detect --source . --log-opts="--all" --redact ...
```

Attendu : code retour 0, « no leaks found ». Toute fuite (même dans un
commit ancien, même d'un secret révoqué) est un finding bloquant : rotation
du secret d'abord, décision sur la réécriture d'historique ensuite.

---

## 4. `scripts/release_check.py`

Exécuté **par le mainteneur**, sous PowerShell, dans le `.venv` du projet.

```powershell
# 1. Outils
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

# 2. PostgreSQL 16 avec les paramètres de la CI (ci.yml) : 127.0.0.1:55432
docker run -d --name hayaflash-test-pg `
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=hayaflash_test `
  -p 127.0.0.1:55432:5432 postgres:16-alpine

# 3. Contrôle (rapport écrit dans docs/releases/reports/)
python scripts/release_check.py --release v1.0.0-rc1

# 4. Nettoyage du conteneur de test
docker rm -f hayaflash-test-pg
```

Ce que fait le script (dans l'ordre) : PostgreSQL 16 joignable →
`manage.py check` → `makemigrations --check --dry-run` → `migrate` sur une
base vide créée puis supprimée (`hayaflash_release_check`) → `pytest
--ds=config.settings.test_pg` (0 skipped) → couverture des apps critiques →
`check --deploy` → pip-audit → bandit (haute bloquante, moyenne listée non
bloquante). Code retour 0 seulement si tout est OK.

Garanties :

- `.env` **jamais lu** : `PYTHON_DOTENV_DISABLED=1` et environnement en liste
  blanche dans chaque sous-processus (comme la CI, qui n'a pas de `.env`).
- `check --deploy` : `ENVIRONMENT=prod`, `SECRET_KEY` générée par
  `get_random_secret_key()`, `ALLOWED_HOSTS` et `DATABASE_URL` factices,
  **uniquement dans l'environnement du sous-processus, jamais sur disque** ;
  le rapport l'indique (« valeurs factices »).
- `.coverage`, junit et json de couverture en dossier temporaire ; seul le
  rapport est écrit dans le dépôt.

Hors script (manuels, consignés dans le suivi) : Celery worker + beat réels,
gitleaks (bloquant Phase 0), OWASP ZAP.

---

## 5. Règles des déploiements futurs (inchangées)

1. **Image au SHA exact** : l'image déployée est taguée au SHA du commit ; le
   code sur le VPS est positionné sur ce même SHA (`git checkout <SHA>`),
   jamais `latest`, jamais `git pull`.
2. **Migrations expand/contract** : ajouter d'abord (compatible avec l'ancienne
   version), supprimer seulement dans une release ultérieure. Les migrations
   sont forward-only : un rollback d'image ne défait pas une migration.
3. **Séquence** : backup → migrate → healthcheck → rollback automatique si le
   healthcheck échoue (`infra/scripts/deploy.sh`).
4. **Jamais de déploiement pendant une FlashSale en cours.**
5. **Arrêt Celery gracieux** (worker terminé proprement, pas de tâche coupée).
