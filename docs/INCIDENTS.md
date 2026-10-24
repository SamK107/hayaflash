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
> Constaté le 2026-10-24 pendant la phase P0 de `feature/distrib` ; corrigé sur `fix/adjust-stock-lock`.

### `adjust_stock` : mise à jour perdue (lost update) face à une commande simultanée

| Champ | Contenu |
|---|---|
| Fichiers | `products/services/crud.py` (`adjust_stock`) ; seul appelant : `products/api.py:166` (Publication rapide, mutation avec `stock`) |
| Gravité proposée | **majeure** (stock faux ⇒ historique de mouvements faux, survente ou stock fantôme) ; probabilité faible à moyenne (fenêtre de quelques ms, mais Publication rapide est utilisée pendant les lives, quand les commandes arrivent) |
| Cause | `adjust_stock` ne verrouillait pas la ligne : il calculait `delta = new - product.stock_available` sur l'instance reçue (lue sans verrou par `products/api.py:161`), puis écrivait une valeur absolue. `create_order` (`orders/services/create_order.py:123`) et `release_order_stock` (`orders/services/stock_release.py:32`) verrouillent, pas lui. |
| Scénario | Stock 20 lu par la vue ; 3 commandes passent (base : 17) ; la vendeuse enregistre 25. Ancien code : mouvement `CORRECTION` de +5 (25 − 20) au lieu de +8 (25 − 17) ; somme des mouvements 22 ≠ stock 25. Deux ajustements simultanés, ou un ajustement et une commande, produisent le même écart. |
| Effets | Écart entre `stock_available` et la somme des `StockMovement`, sans alerte. Le stock final affiché égale la valeur saisie ; c'est l'historique qui est faux (et, selon l'ordre des écritures, des unités commandées peuvent « revenir » ou disparaître). |
| Correctif | `adjust_stock` s'exécute dans `transaction.atomic()`, verrouille le `Product` (`select_for_update`), calcule le delta sur la valeur relue sous verrou et met à jour en `F("stock_available") + delta`. Signature, validation (stock négatif refusé), contenu du `StockMovement` (`CORRECTION`, mêmes notes) et retour (même instance, rafraîchie) inchangés. Aucune migration. |
| Preuves | Avant : `products/tests_adjust_stock_concurrency.py` marqué xfail strict (commit `b4e3d94`) ; sur PostgreSQL (`--ds=config.settings.test_pg`) 3 tests échouent (ex. « 22 != 25 », « 4 != 9 »). Après : 5 tests verts sur PostgreSQL, 4 exécutions consécutives ; tests de concurrence existants (`orders/tests.py`, `orders/tests_expiration.py`, `payments/tests.py`, `core/tests_celery_beat.py`) verts sur PostgreSQL ; suite SQLite 1932 passés, 5 ignorés. |
| Risque résiduel | Le verrou est tenu jusqu'à la fin de la transaction de `bulk_update` (`products/api.py`, `transaction.atomic()`). Si un lot modifie plusieurs produits dans un ordre décroissant pendant qu'une commande multi-produits verrouille les mêmes produits par id croissant, PostgreSQL peut détecter un interblocage et annuler l'une des deux transactions. Rare ; non corrigé ici (changerait `products/api.py`). |
| Statut | Corrigé sur `fix/adjust-stock-lock` (non fusionné, non déployé). |
