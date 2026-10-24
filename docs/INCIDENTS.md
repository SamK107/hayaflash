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

> Défauts latents constatés à la lecture du code, **non corrigés** et sans incident
> réel connu. À évaluer par le mainteneur (voir `GOVERNANCE_RELEASE.md` / registre des
> findings du suivi de release). Constaté le 2026-10-24 pendant la phase P0 de `feature/distrib`.

### `adjust_stock` : mise à jour perdue (lost update) face à une commande simultanée

| Champ | Contenu |
|---|---|
| Fichiers | `products/services/crud.py:114-132` (`adjust_stock`) ; seul appelant : `products/api.py:166` (Publication rapide, mutation avec `stock`) |
| Gravité proposée | **majeure** (stock faux ⇒ survente ou stock fantôme) ; probabilité faible à moyenne (fenêtre de quelques ms, mais Publication rapide est utilisée pendant les lives, au moment où les commandes arrivent) |
| Cause | `adjust_stock` ne verrouille pas la ligne (`select_for_update`) et n'est pas atomique par elle-même. Il lit `product.stock_available` en mémoire, calcule `delta = new - ancien`, puis fait `product.stock_available = new_stock_available` et `save(update_fields=...)` : une valeur **absolue** écrase la valeur en base. En comparaison, `create_order` (`orders/services/create_order.py:123`) et `release_order_stock` (`orders/services/stock_release.py:32`) verrouillent le produit. Le produit passé à `adjust_stock` vient de `Product.objects.get(...)` (`products/api.py:161`), sans verrou. |
| Scénario | Stock affiché 10. La vendeuse saisit 12 dans Publication rapide : la vue lit le produit (stock 10). Pendant ce temps, 3 commandes passent (base : 7). `adjust_stock` écrit 12 : les 3 unités vendues « reviennent » (stock 12 au lieu de 9). Dans l'autre sens (vendeuse qui baisse le stock), des unités commandées peuvent disparaître du décompte. Le mouvement `CORRECTION` enregistre `delta = 2` calculé sur la valeur périmée, donc l'historique des mouvements ne correspond plus au stock. |
| Effets | Survente possible (stock gonflé), écart entre `stock_available` et la somme des `StockMovement`, aucune alerte. |
| Piste de correction (non appliquée) | Dans une `transaction.atomic()` : `Product.objects.select_for_update().get(pk=...)`, calculer `delta` sous verrou, écrire en `F("stock_available") + delta`. Ajouter un test de concurrence (PostgreSQL) sur le modèle de `distrib/tests_concurrency.py`. |
| Contournement dans Distrib | `distrib/services/allocation.py` n'appelle pas `adjust_stock` : verrou + `F()` + `StockMovement(CORRECTION)`. Test : `distrib/tests_concurrency.py` (PostgreSQL) et `distrib/tests_allocation.py::AllocateTests::test_stale_stock_in_memory_is_not_overwritten`. |
| Statut | À évaluer — **non corrigé dans `feature/distrib`** (hors périmètre §8). |
