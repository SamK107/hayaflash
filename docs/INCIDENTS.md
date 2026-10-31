# Registre des incidents & correctifs de sécurité — HayaFlash

> Référencé par `GOVERNANCE_SECURITE.md` (catégorie 10). Une ligne par
> incident de production, alerte de sécurité ou CVE corrigée — même mineure.
> Objectif : qu'un repreneur du projet sache ce qui s'est déjà produit et
> pourquoi certains garde-fous existent.
>
> Les bugs trouvés en audit **avant** la mise en production restent dans
> `docs/CODEBASE_STATUS.md` (ex. Phase 10.0) ; ici, uniquement ce qui a touché
> (ou aurait pu toucher) un environnement réel ou une donnée réelle.

## Comment remplir

| Champ | Contenu |
|---|---|
| Date | Date de détection (AAAA-MM-JJ) |
| Env | prod / staging |
| Type | panne · sécurité · données · paiement · CVE |
| Gravité | critique · majeure · mineure |
| Résumé | Ce qui s'est passé, en une phrase |
| Impact | Qui/quoi a été touché, combien de temps |
| Cause | Cause racine, pas le symptôme |
| Correctif | Commit/PR + action préventive ajoutée (test, alerte, doc) |

Sources de détection à surveiller : alertes Sentry (`environment=prod`/`staging`),
échec du workflow « Audit dépendances (CVE) » (email GitHub du lundi),
heartbeat des sauvegardes manquant, monitoring externe `/health/`.

## Journal

| Date | Env | Type | Gravité | Résumé | Impact | Cause | Correctif |
|---|---|---|---|---|---|---|---|
| — | — | — | — | Aucun incident enregistré (projet pas encore en production au 2026-09-24) | — | — | — |

## À évaluer — hors Distrib

> Défauts latents constatés à la lecture du code, sans incident réel connu.
> Constaté le 2026-10-24 pendant la phase P0 de `feature/distrib` ; corrigé sur
> `fix/adjust-stock-lock`, fusionné dans `main` et déployé en staging puis en
> production le 2026-10-25.

### `adjust_stock` : mise à jour perdue (lost update) face à une commande simultanée

| Champ | Contenu |
|---|---|
| Fichiers | `products/services/crud.py` (`adjust_stock`) ; seul appelant : `products/api.py:166` (Publication rapide, mutation avec `stock`) |
| Gravité proposée | **majeure** (stock faux ⇒ historique de mouvements faux, survente ou stock fantôme) ; probabilité faible à moyenne (fenêtre de quelques ms, mais Publication rapide est utilisée pendant les lives, quand les commandes arrivent) |
| Cause | `adjust_stock` ne verrouillait pas la ligne : il calculait `delta = new - product.stock_available` sur l'instance reçue (lue sans verrou par `products/api.py:161`), puis écrivait une valeur absolue. `create_order` (`orders/services/create_order.py:123`) et `release_order_stock` (`orders/services/stock_release.py:32`) verrouillent, pas lui. |
| Scénario | Stock 20 lu par la vue ; 3 commandes passent (base : 17) ; la vendeuse enregistre 25. Ancien code : mouvement `CORRECTION` de +5 (25 − 20) au lieu de +8 (25 − 17) ; somme des mouvements 22 ≠ stock 25. Deux ajustements simultanés, ou un ajustement et une commande, produisent le même écart. |
| Effets | Écart entre `stock_available` et la somme des `StockMovement`, sans alerte. Le stock final affiché égale la valeur saisie ; c'est l'historique qui est faux (et, selon l'ordre des écritures, des unités commandées peuvent « revenir » ou disparaître). |
| Correctif | `adjust_stock` s'exécute dans `transaction.atomic()`, verrouille le `Product` (`select_for_update`), calcule le delta sur la valeur relue sous verrou et met à jour en `F("stock_available") + delta`. Signature, validation (stock négatif refusé), contenu du `StockMovement` (`CORRECTION`, mêmes notes) et retour (même instance, rafraîchie) inchangés. Aucune migration. |
| Preuves | Avant : `products/tests_adjust_stock_concurrency.py` marqué xfail strict (commit `b4e3d94`) ; sur PostgreSQL (`--ds=config.settings.test_pg`) 3 tests échouent (ex. « 22 != 25 », « 4 != 9 »). Après : 5 tests verts sur PostgreSQL, 4 exécutions consécutives ; tests de concurrence existants (`orders/tests.py`, `orders/tests_expiration.py`, `payments/tests.py`, `core/tests_celery_beat.py`) verts sur PostgreSQL ; suite SQLite 1935 passés, 6 ignorés ; test de concurrence 10/10 sur PostgreSQL. |
| Interblocage (traité) | Le verrou est tenu jusqu'à la fin de la transaction de `bulk_update`. Pour éviter un interblocage avec une commande multi-produits (`create_order` verrouille les produits par id croissant), `bulk_update` verrouille d'abord les produits existants du lot par id croissant (`_lock_existing_products_ascending`, `products/api.py`) ; le traitement et la réponse restent dans l'ordre d'envoi. Preuve : `BulkUpdateDeadlockTests` (25 tours, PostgreSQL) échoue sans ce verrouillage préalable et passe avec ; `BulkUpdateLockOrderTests` vérifie l'ordre des verrous (SQL) et l'ordre inchangé de la réponse. |
| Ordre de fusion | 1) fusionner `fix/adjust-stock-lock` dans `main` ; 2) fusionner `main` dans `feature/distrib` en **gardant la version « corrigé »** de cette section (la section existe aussi, au statut « à évaluer », sur `feature/distrib`). |
| À prévoir : CI PostgreSQL | Les tests de concurrence sont ignorés en SQLite ; ils n'ont tourné qu'en local (conteneur `hf-pg-test`, `--ds=config.settings.test_pg`). Ajouter un job CI PostgreSQL (service `postgres`, mêmes variables `TEST_PG_*`) pour `products/tests_adjust_stock_concurrency.py`, `orders/tests.py`, `orders/tests_expiration.py`, `payments/tests.py`, `core/tests_celery_beat.py`. |
| Statut | **Corrigé.** Fusionné dans `main` (25/10/2026), déployé en staging puis en production le 25/10/2026. Verifie en production par un test de concurrence manuel (shell Django, compte de test cree puis supprime) : stock coherent, aucune erreur. |

### `staff_correct` : `FOR UPDATE` refusé par PostgreSQL (jointure externe)

| Champ | Contenu |
|---|---|
| Fichiers | `distrib/services/settlement.py` (`staff_correct`, ~ligne 355) ; appelé par `distrib/views_pilotage.py:pilotage_correct` |
| Gravité proposée | **majeure** : la correction staff d'une ligne de règlement (Distrib) était **impossible en PostgreSQL** (erreur 500), alors qu'elle fonctionne en SQLite ; aucune donnée faussée |
| Cause | `DistribSettlement.objects.select_for_update().select_related("distributor", "statement")` : `statement` est une clé étrangère nullable, donc Django la joint en `LEFT OUTER JOIN`, et PostgreSQL refuse `FOR UPDATE` sur le côté nullable d'une jointure externe (`NotSupportedError`). SQLite ne verrouille pas les lignes : le défaut ne se voyait pas en local. |
| Scénario | Une équipe corrige le statut d'une ligne depuis `/distrib/pilotage/` ; en prod (PostgreSQL) la requête échoue. |
| Effets | Erreur 500 à chaque correction staff. Détecté par la CI (job « Tests Django », PostgreSQL) : 3 tests de `distrib/tests_settlement.py::CancelAfterConfirmationTests` en échec sur `main` (`07c4207`) puis sur la PR du stock plafonné, sans lien avec elle. |
| Correctif | `select_for_update(of=("self",))` : seule la ligne `DistribSettlement` est verrouillée ; `select_related` conservé, donc mêmes objets chargés, même verrou utile (la ligne corrigée). Aucune migration, aucun changement de comportement métier. `auto_confirm_due` (même motif, mais `distributor` et `order` non nullables) n'est pas concerné et n'est pas modifié. |
| Preuves | Avant : sur PostgreSQL 16 (`--ds=config.settings.test_pg`) `distrib/tests_settlement.py` : 3 échoués, 48 passés. Après : `distrib` complet sur PostgreSQL 16 : 321 passés. Aucun test ajouté : les 3 tests existants couvrent le chemin et échouent sans le correctif. |
| Statut | **Corrigé sur la branche `fix/distrib-settlement-lock`**, en attente de revue et de fusion. Jamais atteint la production (Distrib non fusionné en prod à cette date). |

### Stock d'un produit importé (Distrib) supérieur à la quantité allouée (F-158)

| Champ | Contenu |
|---|---|
| Fichiers | `products/api.py` (`bulk_update` → `adjust_stock`), `distrib/services/allocation.py` ; correctif `fix(distrib): le stock d'un produit importe ne vient que de l'allocation` (#88) |
| Gravité proposée | **moyenne** : la revendeuse peut afficher et vendre plus que ce que le grossiste lui a alloué (survente possible) ; aucune commande concernée à ce jour |
| Cause | La grille « Publication rapide » acceptait un stock sans rapport avec `allocated_qty` pour un produit importé. |
| Constat (staging, 30/10/2026, requête lecture seule après déploiement de `2354200`) | **1 écart sur 3 produits importés** : `ImportedProduct #3`, revendeuse Bassitan SOUCKO, produit #283, `stock_available` 35 pour `allocated_qty` 5. |
| Datation | `StockMovement` #92 `correction +30` (« Ajustement stock (Publication rapide) ») le 2026-10-28 07:43 UTC, puis `AllocationMovement` #2 `+5` / `StockMovement` #93 `+5` à 07:47 UTC. Écart **antérieur de ~2 jours** au correctif, déployé le 30/10 vers 18:57 UTC (19:57 heure du VPS, UTC+1) ; il n'a pas été créé par le code corrigé. Somme des `StockMovement` = 35 = stock : le journal est cohérent, c'est la valeur qui est trop haute. Aucune ligne de commande sur le produit. |
| Correction appliquée | Staging, 2026-10-30 19:18 UTC, accord du mainteneur : `adjust_stock` du produit #283 à 5 → `StockMovement` #95 `CORRECTION −30`. Vérifié : `stock_available` = 5, somme des mouvements = 5, requête `stock_available > allocated_qty` = 0 résultat. Dry-run : `scripts/dryrun_distrib_stock_cap.py`. |
| Prod (31/10/2026, accord du mainteneur) | Déploiement de `/srv/hayaflash-prod` de `5fddc85` à `11ec93b` ; `DISTRIB_ENABLED=False` confirmé ; `distrib.0001_initial` appliquée ; `/health/` 200 ; `/distrib/` en 404 depuis l'extérieur. `scripts/dryrun_distrib_stock_cap.py` sur la prod : **0 écart**. Aucune correction nécessaire. |
| Statut | **Clos.** Staging corrigé (1 donnée) ; prod vérifiée, 0 écart. |

### Suivi : `deploy_vps.sh` affiche un mauvais commit de retour arrière après un `git pull` manuel (F-160)

| Champ | Contenu |
|---|---|
| Fichiers | `infra/scripts/deploy_vps.sh` (`PREV_SHA`, ligne 94 ; commande de retour arrière, ligne 205) |
| Gravité proposée | **mineure, non bloquante** : aucun dégât constaté ; risque seulement si la commande affichée est copiée telle quelle en cas de retour arrière |
| Cause | `PREV_SHA="$(git rev-parse HEAD)"` est lu quand le script démarre. Si un `git pull` a déjà été fait, `HEAD` est déjà la cible : `PREV_SHA = NEW_SHA`. |
| Constat | Staging le 30/10 (retour arrière affiché `2354200`, cible du déploiement) ; prod le 31/10 (affiché `11ec93b`, service réellement sur `5fddc85`). Même cause : l'étape 3 affiche « Deja a jour » sans liste de commits ni changements sensibles (migrations, compose, nginx). |
| Contournement | Relever `git rev-parse HEAD` avant le `pull` (fait pour les deux piles) et utiliser ce commit, pas celui affiché, pour un retour arrière. L'image `<image>:previous` est, elle, correcte. |
| Piste (à traiter plus tard) | Que `deploy_vps.sh` ne dépende pas de l'état du clone : soit capturer `HEAD` avant tout `pull`, soit déduire le commit en service de l'image (tag `<image>:<sha court>` déjà posé par le script, ou label `org.opencontainers.image.revision` au `docker build`). |
| Statut | **Ouvert, hors urgence** (F-160). |
