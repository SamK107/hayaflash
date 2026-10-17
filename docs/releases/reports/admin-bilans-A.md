# Admin — Bilans vendeurs, partie A (liste des boutiques + fiche mensuelle)

Date : 2026-10-17 · Lecture seule : aucun modèle, aucune migration, pipeline de commande intact.

## Fichiers

| Fichier | Rôle |
|---|---|
| `analytics/services/monthly_report.py` (nouveau) | Calculs : `list_shops`, `shop_month_report`, bornes de mois, choix de période. Réutilisable par la future page vendeuse. |
| `core/views.py` | `platform_admin_shops`, `platform_admin_shop_report` (`@staff_member_required`, comme `platform_admin_dashboard`). |
| `core/urls.py` | `platform-admin/boutiques/` (`platform_admin_shops`), `platform-admin/boutiques/<id>/bilan/?mois=AAAA-MM` (`platform_admin_shop_report`). |
| `templates/core/platform_admin_shops.html`, `platform_admin_shop_report.html` (nouveaux) | Pages. Aucun JS inline (CSP). |
| `templates/core/platform_admin.html` | Lien « Boutiques et bilans ». |
| `analytics/tests_monthly_report.py` (nouveau) | 13 tests. |

## Définitions retenues (aussi en tête du service)

- **Commande réalisée** = `collected_q` (`orders/services/dashboard.py:31`) : `Order.status == DELIVERED` **et** `Delivery.cod_collected`. Même définition que `analytics/services/reporting.py` (F-94/F-95) : admin et vendeuse voient les mêmes chiffres. `reporting._collected_items` / `_revenue_expr` sont réutilisés.
- **CA** = Σ `price_snapshot × quantity` des lignes des commandes réalisées.
- **Mois** = `Order.created_at` en heure locale (bornes locales du mois, `TIME_ZONE=Africa/Bamako`).
- **Répartition des commandes** (catégories exclusives, somme = passées) : réalisées · annulées · *livrées non encaissées* · échec de livraison (`Delivery.status=FAILED`, commande ni annulée ni livrée) · en attente de mise à jour (le reste : pending / confirmed / out_for_delivery).
- **Ventes flash réalisées** = non annulées, `start_time` dans le mois et déjà commencé.
- **Clientes** = téléphones distincts des commandes réalisées ; « déjà clientes » = téléphone avec une commande non annulée chez la boutique avant le mois.
- **Activité** : « active » si dernière vente (non annulée, déjà commencée) il y a ≤ 30 jours. Plan = plan effectif (un payant expiré → FREE).
- Mois par défaut = dernier mois complet (janvier → décembre N-1), ramené au mois d'inscription si la boutique est née ce mois-ci. Mois invalide ou hors bornes → même repli, jamais d'erreur.

## Points ouverts (statuts ambigus)

1. **Pas de statut « refusé » sur `Order`.** Seul l'échec existe, côté `Delivery.FAILED`, et la commande **reste** `out_for_delivery` (`delivery/services/delivery.py:311-321`) : j'ai donc classé ces commandes en « échec de livraison » plutôt qu'en « en attente ». Alternative : les laisser en attente.
2. **Livrée mais non encaissée** (`DELIVERED` sans `cod_collected`) : ni réalisée, ni annulée, ni « à mettre à jour » (statut final). Je l'affiche sur une ligne dédiée. Elle n'entre pas dans le calcul de l'alerte des 20 %. À confirmer.
3. **Alerte 20 %** : seuil strictement supérieur, calculé sur *en attente de mise à jour / passées*.
4. **« Ventes réalisées »** : critère = début de la vente dans le mois (une vente à cheval sur deux mois compte dans le mois de début).
5. Téléphones clientes comparés en chaîne brute (pas de normalisation E.164 supplémentaire).
6. Le rang `#` reste celui de l'inscription même avec recherche ou ordre inversé.

## Vérifications

- `pytest --ds=config.settings.test` : 1619 passed, 4 skipped (avant correctifs ruff mineurs) ; les 13 tests du module repassés ensuite.
- `ruff` : propre sur les fichiers ajoutés. `core/views.py` garde 4 avertissements **préexistants** (non touchés).
- `manage.py check` : OK.
- Requêtes de la liste : constantes (test avec 1 puis 9 boutiques).
