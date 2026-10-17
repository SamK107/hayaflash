# Admin — Bilans vendeurs, partie B (comparaison, évolution, signaux, résumé)

Date : 2026-10-17 · Lecture seule, aucune migration. Prérequis : [admin-bilans-A.md](admin-bilans-A.md).

## Changement de la partie A (décision du 17/10)

Les commandes « livrées non encaissées » comptent désormais dans l'alerte « Statuts de livraison non mis à jour » (elles gardent leur ligne dédiée). Nouveau champ `orders_stale` = en attente de mise à jour + livrées non encaissées ; `pending_alert` = `orders_stale / passées > 20 %`. Test : `SignalTests.test_stale_includes_delivered_unpaid`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `analytics/services/monthly_report.py` | + `shop_bilan`, `build_comparison`, `build_trend`, `sleeping_products`, `best_slot`, `build_signals`, `build_text_summary`. |
| `core/views.py` | La fiche appelle `shop_bilan` (contexte `bilan`). |
| `templates/core/platform_admin_shop_report.html`, `partials/_bilan_value.html` | « À regarder », comparaison, évolution (tableau + barres SVG serveur, sans Chart.js), résumé + bouton `data-hf-copy-from` (déjà géré par `hf-base.js`, confirmation « ✓ Copié », CSP respectée). |
| `analytics/tests_monthly_report_b.py` | 20 tests. |

## Constantes (en tête du service)

| Constante | Valeur |
|---|---|
| `COMPARE_MIN_REALIZED` / `COMPARE_MIN_REVENUE` | 3 commandes réalisées / 10 000 FCFA (mois précédent) |
| `TREND_MONTHS`, `MOVERS_LIMIT` | 3 mois, 3 produits |
| `SIGNAL_DEPENDENCE_SHARE` | > 40 % des recettes |
| `SIGNAL_SLEEPING_MIN_SALES` | ≥ 2 ventes du mois |
| `SIGNAL_DELIVERY_RATE` / `SIGNAL_DELIVERY_MIN_ORDERS` | < 60 % avec ≥ 5 commandes |
| `PENDING_ALERT_RATIO` | > 20 % |
| `SIGNAL_SLOT_MIN_SALES` | ≥ 2 ventes par créneau, ≥ 2 créneaux |
| `SIGNAL_LOYAL_MIN_CUSTOMERS` | ≥ 5 clientes |
| `SLOT_MORNING_END` / `SLOT_AFTERNOON_END` | 12 h / 18 h (heure locale ; « soir » = dès 18 h, nuit incluse) |

## Règles appliquées

- **Seuil** : si le mois précédent a < 3 réalisées ou < 10 000 FCFA, aucune flèche ni pourcentage ; « base trop faible pour comparer » + valeurs brutes (page et résumé). Taux de réalisation : variation en **points**, jamais en %. Pas de mois précédent (inscription ce mois) → « — ».
- **Produits en hausse/baisse** : recette du mois sélectionné − recette du premier mois de la fenêtre, en FCFA absolus, 3 plus fortes hausses et baisses.
- **Stock qui dort** : liaison réelle `FlashSaleProduct` (actif) ; produit actif, `stock_available > 0`, dans ≥ 2 ventes non annulées démarrées dans le mois, 0 vente réalisée.
- **Signaux** : faits chiffrés uniquement, aucun conseil. Le résumé (`build_text_summary`, testé) ne contient ni nom/téléphone d'acheteur ni téléphone de la vendeuse.

## Limites connues

- Stock qui dort : la variante « ou les 2 dernières ventes » n'est **pas** implémentée (seulement ≥ 2 ventes du mois) ; `Product.stock_available` est le stock **actuel**, pas celui du mois consulté.
- Meilleur créneau : CA = commandes réalisées créées dans le mois rattachées aux ventes démarrées dans le mois (une commande passée le mois suivant sur une vente de fin de mois n'est pas comptée).
- « Clientes fidèles » est affiché dès 5 clientes (fait neutre, pas un seuil d'alerte) ; téléphones comparés en chaîne brute.
- Dépendance : une boutique à produit unique affiche 100 % (fait exact).
- « Inscrite depuis n mois » = écart de mois civils entre l'inscription et le mois consulté.
- La fenêtre de 3 mois repose sur 3 appels de `shop_month_report` (≈ 20 requêtes au total, constant : testé avec 6 puis 36 commandes, plafond 40).
- Captures de la fiche : **non réalisées** (pas de Playwright utilisé) ; rendu vérifié par tests de contenu uniquement, pas visuellement.

## Vérifications

- Suite complète : 1638 passed, 4 skipped, + 1 échec corrigé ensuite (garde-fou `subscriptions/tests_plans.py` : « 10 000 FCFA » en dur dans le template → passé par le contexte) ; re-lancés ensuite : `subscriptions/tests_plans.py`, `core`, `analytics` OK (407 passed).
- ruff propre sur les fichiers ajoutés / modifiés du service et des tests.
