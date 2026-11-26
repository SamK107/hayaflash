# Runbook — validation staging de la V2

Statut : **brouillon à valider par le fondateur**. Ce document ne lance rien : aucune commande n'a été exécutée sur un serveur pour l'écrire.
Source de vérité : `docs/EXECUTION_V2.md`. Déploiement manuel : `infra/scripts/deploy_vps.sh` (voir ses options dans son en-tête).

Légende des commandes :
- **LECTURE SEULE** : ne modifie ni la pile, ni la base, ni les fichiers.
- **MODIFIE LE SERVEUR** : écrit des fichiers, une base, un conteneur ou une configuration. Ne jamais lancer sans validation explicite du fondateur pour cette action précise.

Pile visée : staging uniquement, dans `/srv/hayaflash` (port 8020). **Ne touche jamais à `/srv/hayaflash-prod`** ni à `services.symain.africa`, présent sur le même VPS.

Les commandes qui suivent supposent un shell SSH sur le VPS, dans le dossier de la pile concernée.

---

## 0. Décisions à prendre avant de commencer (fondateur)

| # | Décision | Pourquoi | Référence |
|---|---|---|---|
| D1 | Accepter ou non que la recette Orange (étape 4.2) utilise de l'argent réel | Staging et prod partagent les mêmes identifiants Orange Money. Un paiement de test à 100 FCFA est donc un **vrai paiement** sur le compte marchand de production. | Registre rc1, F-165 (risque accepté le 02/11/2026) |
| D2 | Valeur de `PARTNER_REGISTRATIONS_OPEN` en staging | Ouvrir l'inscription partenaire en staging teste le parcours ; en prod elle reste fermée tant que D11 n'est pas tranchée. | Section 3 |
| D3 | Valeur de `MARKET_REQUIRE_VERIFIED` en prod | Vrai = le Marché ne liste que les boutiques vérifiées : change la visibilité des boutiques existantes. Reste faux tant que non décidé. | `flash_sales/services/marche_visibility.py` |
| D4 | Point (b) du finding F-170 (accès du grossiste par URL en dur) | Non précisé : rien à valider tant qu'il n'est pas décrit. | Registre rc1, F-170 |
| D5 | Fenêtre de déploiement staging | Une migration et un redémarrage de `web` ; le staging n'est pas sur un domaine indexé (`SITE_NOINDEX`), mais des utilisateurs de test peuvent être connectés. | — |

---

## 1. Pré-contrôles

### 1.1 Versions déployées — LECTURE SEULE

```bash
git -C /srv/hayaflash rev-parse --short HEAD
git -C /srv/hayaflash-prod rev-parse --short HEAD
git -C /srv/hayaflash status --short
```

Attendu : staging à un commit antérieur à `integration/v2` ; `status` vide (sinon `deploy_vps.sh` refuse, voir section 3).

### 1.2 Valeurs des réglages dans les fichiers `.env` — LECTURE SEULE

N'affiche que les trois lignes utiles, pas le reste du fichier (secrets).

```bash
grep -E '^(DISTRIB_ENABLED|PARTNER_REGISTRATIONS_OPEN|MARKET_REQUIRE_VERIFIED)=' /srv/hayaflash/.env
grep -E '^(DISTRIB_ENABLED|PARTNER_REGISTRATIONS_OPEN|MARKET_REQUIRE_VERIFIED)=' /srv/hayaflash-prod/.env
```

Une variable absente = valeur par défaut du code (`false`). Rappel : **une variable absente ne doit pas être confondue avec une variable fausse** ; les deux donnent le même comportement, mais le fichier doit être explicite (voir section 3.3).

### 1.3 Valeurs réellement chargées par le conteneur web — LECTURE SEULE

Le `.env` ne dit pas tout : c'est la valeur vue par le processus qui compte. Le code `main` (prod) ne connaît peut-être pas les variables V2 : une `AttributeError` est alors un résultat normal et confirme que prod n'est pas en V2.

```bash
cd /srv/hayaflash && docker compose -f docker-compose.production.yml exec -T web python manage.py shell -c "from django.conf import settings as s; print('DISTRIB', s.DISTRIB_ENABLED); print('PARTNER_OPEN', getattr(s,'PARTNER_REGISTRATIONS_OPEN','absent')); print('MARKET_VERIFIED', getattr(s,'MARKET_REQUIRE_VERIFIED','absent'))"
cd /srv/hayaflash-prod && docker compose -f docker-compose.production.yml exec -T web python manage.py shell -c "from django.conf import settings as s; print('DISTRIB', s.DISTRIB_ENABLED); print('PARTNER_OPEN', getattr(s,'PARTNER_REGISTRATIONS_OPEN','absent')); print('MARKET_VERIFIED', getattr(s,'MARKET_REQUIRE_VERIFIED','absent'))"
```

Commande de prod : **LECTURE SEULE** (aucune écriture). À valider par le fondateur avant exécution sur prod, car elle touche la pile de production (même si elle ne modifie rien).

### 1.4 Stock négatif avant migration `products.0011` — LECTURE SEULE

La migration `products/0011_stock_non_negatif` **échoue** si une ligne a un stock négatif. Les tables sont `products_product` (`stock_available`) et `products_productvariant` (`stock`).

Requête de contrôle (identique à celle de l'en-tête de la migration) :

```sql
SELECT 'product', id, stock_available FROM products_product WHERE stock_available < 0
UNION ALL
SELECT 'variant', id, stock FROM products_productvariant WHERE stock < 0;
```

Exécution sur la base de la pile (LECTURE SEULE, pas de `UPDATE`) :

```bash
cd /srv/hayaflash && docker compose -f docker-compose.production.yml exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT '"'"'product'"'"', id, stock_available FROM products_product WHERE stock_available < 0 UNION ALL SELECT '"'"'variant'"'"', id, stock FROM products_productvariant WHERE stock < 0;"'
```

Sur le code V2 uniquement (la commande n'existe pas dans `main`), équivalent lisible :

```bash
cd /srv/hayaflash && docker compose -f docker-compose.production.yml exec -T web python manage.py controle_stock_negatif --settings=config.settings.prod
```

Résultat attendu : **aucune ligne**.

**Si des lignes sont renvoyées : STOP.**
1. Ne pas lancer la migration ni `deploy_vps.sh`.
2. Noter les identifiants (`product` ou `variant`, id, stock).
3. Corriger le stock **par l'interface** (admin ou écran vendeur), qui écrit un `StockMovement`. Ne jamais exécuter d'`UPDATE` SQL direct, qui ne laisse aucune trace.
4. Relancer la requête jusqu'à obtenir zéro ligne.
5. Si la correction demande une décision commerciale (commande déjà prise, sur-vente), la remonter au fondateur avant tout changement.

---

## 2. Sauvegarde et point de retour

### 2.1 Sauvegarde manuelle avant migration — MODIFIE LE SERVEUR (écrit une sauvegarde dans `/srv/backups/`)

Le script `deploy_vps.sh` fait déjà une sauvegarde (étape 2) si la pile a une base. Cette sauvegarde manuelle sert de point de contrôle indépendant.

Simulation d'abord — LECTURE SEULE :

```bash
bash /srv/hayaflash/infra/scripts/backup.sh /srv/hayaflash --dry-run
```

Puis la vraie sauvegarde — MODIFIE LE SERVEUR :

```bash
bash /srv/hayaflash/infra/scripts/backup.sh /srv/hayaflash
```

Produit `/srv/backups/hayaflash/AAAA-MM-JJ_HHMM/` avec `db.dump`, `media.tar.gz`, `backup.info`, `SHA256SUMS`.

Vérifier la sauvegarde sans rien écraser (restauration dans une base jetable) : `restore_test.sh` (voir `docs/SAUVEGARDES.md`). **À faire avant le déploiement** ; ne pas se contenter du `SHA256SUMS`.

### 2.2 Point de retour

- **Tag de code** : `avant-v2-20261121` (commit `2112544`).
- **Image Docker** : `deploy_vps.sh` pose le tag `<image>:previous` sur l'image en place avant de construire la nouvelle. Le script affiche à la fin la **commande exacte de retour arrière** ; la relever et la noter avant de continuer.

### 2.3 Réversibilité des migrations V2

Les quatre migrations V2 (par rapport à `main`) ont un `reverse` défini, mais **le retour arrière de schéma n'est pas un retour arrière de données**.

| Migration | Effet | Retour arrière (`migrate <app> <cible>`) | Limite |
|---|---|---|---|
| `accounts.0008_shopreport` | crée `accounts_shopreport` | supprime la table | perd tous les signalements saisis |
| `accounts.0009_sellerprofile_trust_level` | ajoute `trust_level` (défaut 1 existant, 0 ensuite) | supprime la colonne | perd les niveaux saisis |
| `partners.0004_referral_grossiste` | FK `distributor`, contraintes, `seller` devient nullable | rétablit `seller` NOT NULL | **échoue** si un parrainage lié à un grossiste existe (`seller` NULL) |
| `products.0011_stock_non_negatif` | contraintes CHECK `stock >= 0` | supprime les contraintes | aucune perte |

**Point critique (à vérifier sur staging avant la prod)** : après `accounts.0009`, la colonne `trust_level` n'a **pas de défaut en base**. Un ancien code (`avant-v2`) qui crée une boutique sans ce champ échouerait sur une contrainte NOT NULL. Donc **revenir au code `avant-v2` sans restaurer la base ne suffit pas**.

Retour arrière complet = (a) restaurer la sauvegarde de 2.1 ; (b) redéployer `avant-v2-20261121` (`deploy_vps.sh --ref avant-v2-20261121`). Ne jamais lancer `migrate ... zero`.

---

## 3. Déploiement de staging avec `deploy_vps.sh`

Options exactes (lues dans l'en-tête de `infra/scripts/deploy_vps.sh`) :

```
bash infra/scripts/deploy_vps.sh <dossier_pile> [--yes] [--dry-run] [--ref <ref>]
  --yes        pas de confirmation (NE PAS utiliser pour cette première mise en V2)
  --dry-run    affiche sans rien modifier
  --ref <ref>  défaut origin/main ; ici : integration/v2
```

Le script fait : contrôle d'isolation des piles, sauvegarde (si base présente), `git fetch origin`, liste des commits et des fichiers sensibles (migrations, `.env.example`, compose, Dockerfile, requirements, nginx) puis demande `oui`, tag `:previous`, `git checkout --detach`, `docker build`, `collectstatic`, `up -d web worker beat`, **`migrate --noinput`**, nginx, `/health/`.

### 3.1 Isolation des piles — LECTURE SEULE

```bash
bash /srv/hayaflash/infra/scripts/check_stack_isolation.sh /srv/hayaflash
```

Attendu : aucune erreur. Le script refuse un compose qui contient un chemin `/srv/hayaflash` en dur.

### 3.2 Simulation — LECTURE SEULE

```bash
bash /srv/hayaflash/infra/scripts/deploy_vps.sh /srv/hayaflash --dry-run --ref integration/v2
```

Relire la liste des commits et les fichiers sensibles affichés. Attendu : migrations `accounts/0008`, `accounts/0009`, `partners/0004`, `products/0011` (et rien d'inattendu).

### 3.3 Réglages à poser dans `/srv/hayaflash/.env` — MODIFIE LE SERVEUR (fichier `.env` de staging)

Ajouter (ou vérifier) les trois lignes. Ne pas les mettre dans `.env.example`, qui ne contient que des valeurs par défaut documentées.

```
DISTRIB_ENABLED=true
PARTNER_REGISTRATIONS_OPEN=<selon D2>
MARKET_REQUIRE_VERIFIED=false
```

Les variables sont lues au démarrage du conteneur : un changement de `.env` n'est pris en compte qu'après recréation de `web` (le script le fait, `up -d --no-deps web worker beat`). Ne pas modifier le `.env` de prod dans ce runbook.

### 3.4 Déploiement — MODIFIE LE SERVEUR (migration sur la base de staging)

Pas de `--yes`. La question de confirmation exige la réponse exacte `oui`.

```bash
bash /srv/hayaflash/infra/scripts/deploy_vps.sh /srv/hayaflash --ref integration/v2
```

Vérifications immédiates — LECTURE SEULE :

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://staging.hayaflash.com/health/
cd /srv/hayaflash && docker compose -f docker-compose.production.yml logs --tail=100 web | grep -i -E "error|traceback" || echo "aucune erreur"
cd /srv/hayaflash && docker compose -f docker-compose.production.yml exec -T web python manage.py showmigrations accounts partners products | grep -E "0008|0009|0004|0011"
```

Attendu : `/health/` = 200 ; migrations marquées `[X]`.

**Ne pas toucher à prod pendant tout ce runbook.** Le script `deploy_vps.sh` pointe par défaut sur `origin/main` : toujours passer `--ref integration/v2` pour staging.

---

## 4. Recette de bout en bout sur staging

Pour chaque point : le résultat attendu, et la preuve à noter (capture ou sortie de commande) dans le registre rc1 ou le journal de la recette.

### 4.1 Inscription d'une vendeuse — Navigateur

- Créer un compte vendeur de test par le parcours d'inscription public (pas d'identifiant réel). **URL à relever avant la recette** : l'ancienne API d'authentification `/api/v1/accounts/auth/*` est retirée du routage (F-19, `accounts/tests_api_auth_removed.py`) et ne doit pas être utilisée.
- Attendu : compte créé, boutique (`SellerProfile`) créée, `trust_level` = 0 (non vérifiée).
- Preuve : identifiant de la boutique dans `/admin/accounts/sellerprofile/`.

### 4.2 Test Orange Money à 100 FCFA via `SellerPriceOverride` — Navigateur + admin

**Bloqué tant que D1 n'est pas tranchée.** Si accepté :
- Suivre `docs/RUNBOOK_TEST_PAIEMENT.md` section 1 (tarif spécial : 100 FCFA, 1 jour, 1 utilisation, fenêtre de 2 h).
- Attendu : `price_override.created` dans l'audit ; paiement `SubscriptionPayment` en succès après webhook ; plan Medium actif ; la transaction est exclue du CA (`is_special_price`, motif `test`).
- Ne jamais saisir de montant dans le formulaire de paiement : le prix est calculé côté serveur.

### 4.3 Lien traçable par partenaire — Navigateur

- Depuis `/platform-admin/partenaires/`, récupérer le lien personnel du partenaire de test (`/r/<code>/`).
- Ouvrir ce lien dans une fenêtre privée, puis créer une boutique.
- Attendu : le cookie `hf_ref` est posé ; `partners.Referral.seller` = la nouvelle boutique (premier lien gagnant : un second lien ne change rien).
- Preuve : ligne `Referral` et `CommissionEntry` dans l'admin.

### 4.4 Inscription partenaire avec `PARTNER_REGISTRATIONS_OPEN` — Navigateur

- Avec `PARTNER_REGISTRATIONS_OPEN=true` (D2 = vrai) : le parcours `/partenaires/d/<token>/` permet d'accepter la lettre d'essai en ligne.
- Avec `false` : l'acceptation en ligne est refusée ; l'équipe peut toujours enregistrer l'acceptation à la main depuis l'admin.
- Changer la valeur = modifier `.env` puis recréer `web` (3.3). Ne pas le faire sans noter la valeur précédente.

### 4.5 Suspension et réactivation d'une boutique — Admin + Navigateur

- `/admin/accounts/sellerprofile/` : sélectionner la boutique de test, action **Suspendre**, motif obligatoire.
- Attendu : `/f/<slug>/` et `/s/<slug>/` affichent la page neutre **« Boutique indisponible »** (`analytics/shop_unavailable.html`), sans vente ni bouton de commande. Aucune commande ne doit passer (`assert_flash_sale_accepts_orders`).
- Action **Réactiver** : la boutique et ses ventes reviennent.
- Preuve : entrées `shop.suspended` puis réactivation dans le journal d'audit.

### 4.6 Signalement `ShopReport` — Navigateur (sans compte)

- Ouvrir `/signaler/<slug>/` (sans être connecté), envoyer un signalement.
- Attendu : enregistrement dans `/admin/accounts/shopreport/` (statut `new`).
- Limite : 5 soumissions par heure et par IP. La 6e doit être refusée.
- Vérifier que le signalement n'apparaît dans aucune page publique.

### 4.7 Niveau de confiance avec `MARKET_REQUIRE_VERIFIED` — Admin + Navigateur

- Avec `MARKET_REQUIRE_VERIFIED=false` (défaut) : le Marché liste la boutique de test, quel que soit son niveau.
- Passer `MARKET_REQUIRE_VERIFIED=true` en staging uniquement (3.3, recréation de `web`) :
  - une boutique au niveau 0 n'apparaît **pas** sur le Marché ;
  - la même boutique passée au niveau 1 (`trust_level`, admin) y apparaît.
- Rétablir `false` à la fin, sauf décision contraire (D3).
- Route exacte de la page Marché : à relever dans `flash_sales/public_views.py` (non trouvée par le simple `grep` des `urls.py`).

### 4.8 Lien « Grossistes » de `/platform-admin/` et accès grossiste — Navigateur

- Avec `DISTRIB_ENABLED=true` : `/platform-admin/` affiche « Grossistes » à côté de « Programme partenaires » et « Boutiques et bilans » (`templates/core/platform_admin.html:21`).
- Avec `false` : le lien disparaît, `/distrib/*` renvoie 404.
- Accès grossiste : se connecter avec un compte grossiste de test. Attendu : redirection vers `/distrib/` après `/login/` sans `next`. Le lien « Espace grossiste » est visible sur `/login/` (`{% url %}`, pas en dur).
- Point (b) de F-170 (accès par URL en dur) : **non précisé** ; décision D4 avant de le tester.

---

## 5. Critères de passage

Ce qui doit être vrai pour autoriser **(a)** la fusion de la PR #111 (`integration/v2` vers `main`, ouverte) puis **(b)** le déploiement de prod. Ce runbook ne fusionne ni ne déploie rien.

### 5.1 Avant la fusion de #111 dans `main`
- [ ] Section 1 terminée : versions notées, réglages relevés, stock négatif à zéro ligne sur staging **et** prod (sur prod, à valider par le fondateur).
- [ ] Sauvegarde de section 2.1 réalisée, vérifiée par `restore_test.sh`.
- [ ] Déploiement staging (section 3) : `/health/` = 200, migrations `[X]`, aucune erreur de traceback dans les logs de `web`.
- [ ] Recette 4.1, 4.3, 4.4, 4.5, 4.6 : résultat attendu, preuves notées.
- [ ] Recette 4.2 : faite **ou** non réalisée avec décision explicite du fondateur sur D1.
- [ ] Recette 4.7 : faite avec `MARKET_REQUIRE_VERIFIED=true` puis remise à `false`, ou décision D3 prise.
- [ ] Recette 4.8 : lien Grossistes et accès grossiste vérifiés ; F-170 mis à jour (ou accepté tel quel par le fondateur).
- [ ] Toutes les CI de #111 vertes (`ci.yml`, `deps-audit.yml`), y compris le seuil de couverture 88 et le check --deploy (voir `docs/releases/reports/pending/JOURNAL_K.md`).
- [ ] Aucune erreur 500 nouvelle dans les logs de staging pendant la recette.

### 5.2 Avant le déploiement de prod
- [ ] Tout ce qui précède, plus les mêmes migrations vérifiées sur prod (stock négatif = 0, sauvegarde de prod faite avec `backup.sh`).
- [ ] `PARTNER_REGISTRATIONS_OPEN=false` et `MARKET_REQUIRE_VERIFIED` (D3) fixés explicitement dans `/srv/hayaflash-prod/.env`.
- [ ] `DISTRIB_ENABLED` de prod **relevé** (section 1.2/1.3) : la valeur attendue dépend de F-170, et `CLAUDE.md` affirme `true` alors que le fondateur ne voit pas le lien sur prod.
- [ ] Commande de retour arrière relevée (section 2.2) et testée sur staging.
- [ ] Autorisation explicite du fondateur pour la commande `deploy_vps.sh` sur **prod**, sans `--yes`, avec `--ref` exact.

---

## 6. Décisions attendues du fondateur (résumé)

1. **D1** : recette Orange à 100 FCFA avec argent réel sur le compte marchand partagé (F-165) — oui / non.
2. **D2** : `PARTNER_REGISTRATIONS_OPEN` en staging (et valeur de prod, fermée jusqu'à D11).
3. **D3** : `MARKET_REQUIRE_VERIFIED` en prod (défaut faux recommandé).
4. **D4** : description du point (b) de F-170 (accès grossiste par URL en dur).
5. **D5** : fenêtre de déploiement staging.
6. Validation explicite de chaque commande marquée **MODIFIE LE SERVEUR** et de toute lecture sur **prod** (1.2 et 1.3).
