# Journal — Tâche D : contrôle central des droits de plan (`plan_has_feature`)

Branche : `task/d-plan-has-feature` (worktree `C:\projets\hf-d`). Base : `0d2b9e1`.

## 2026-11-22 — Décisions

| Décision | Raison | Alternative écartée |
|---|---|---|
| Matrice en code dans `subscriptions/services/plans.py` : `PLAN_FEATURES` (`stats`, `advanced_stats`, `paid_subscription`) et `plan_has_feature(plan, feature)`. | Demande de la tâche ; EXECUTION_V2 § 3 (contrôle central, jamais de `if plan == …` dispersé). | Matrice en base (`PlanConfig`) : écartée, les droits ne doivent pas être éditables sans revue de code. |
| `paid_subscription` = `PAID_PLANS` (MEDIUM, PRO) : `PLAN_FEATURES` réutilise la constante existante. | Évite une deuxième liste de plans à maintenir. | Dupliquer la liste : écarté. |
| Plan inconnu → `False` ; fonctionnalité inconnue → `ValueError`. | Fail-closed (EXECUTION_V2 § 3 ; BUSINESS non ouvert doit être refusé partout). | Lever une erreur pour un plan inconnu : écarté, casserait les pages sur un plan non prévu. |
| `Subscription.current_plan` = FREE si expiré, sinon `plan` ; `has_stats`, `has_advanced_stats`, `is_paid` passent par `plan_has_feature(current_plan, …)`. | Reproduit exactement l'ancienne règle `(plan) and not is_expired` (vérifié cas par cas dans les tests). | Changer la sémantique d'expiration : écarté (interdit : comportement de FREE/MEDIUM/PRO). |
| `is_medium` et `is_pro` **conservés** (identités de palier). | Utilisés par les gabarits pour l'affichage (libellés, couleurs, icônes) : la consigne exclut les libellés. | Les supprimer ou les réécrire via la matrice : écarté, aucun gain de droit et risque sur l'affichage. |
| `flash_sales/views.py` (analytics) : le contrôle `sub.is_pro` devient `sub.has_advanced_stats`. Clé de contexte renommée `has_advanced_stats` ; gabarit `flash_sales/analytics_dashboard.html` mis à jour (2 lignes). | C'est un droit (graphique annuel réservé à PRO). Le renommage évite un nom `is_pro` trompeur pour un droit. | Garder `is_pro` comme clé : écarté, nom trompeur. |
| `subscriptions/views.py` `checkout_view` et `subscriptions/services/payment.py` `create_orange_payment` : `plan in (MEDIUM, PRO)` → `plan_has_feature(plan, "paid_subscription")`. Imports `Plan` devenus inutiles retirés. | Droit d'achat. Même résultat pour FREE, MEDIUM, PRO, et pour tout plan inconnu. | — |

## 2026-11-22 — Ce qui n'a PAS été changé (volontairement)

Ces endroits testent encore un plan, mais ce ne sont **pas** des contrôles de droit :

- **Affichage** (gabarits, libellés, couleurs) : `templates/accounts/settings.html`, `templates/subscriptions/subscription.html`, `templates/flash_sales/list.html` (`quota.is_pro`), `templates/flash_sales/analytics_dashboard.html` ligne 17 (`sub.is_pro`, classe CSS), `subscriptions/admin.py` (libellés et couleurs), `accounts/admin.py:132`.
- **Clé de contexte `is_pro` du quota** : `subscriptions/services/limits.py` (`"is_pro": sub.is_pro`) — consommée par `flash_sales/list.html` pour afficher l'incitation à la mise à niveau. Affichage, non modifiée.
- **Texte d'incitation** : `subscriptions/services/limits.py:72` (`if effective_plan == Plan.PRO:`) choisit un message de support ; aucun droit n'en dépend.
- **Validations de configuration** : `subscriptions/models.py` (`PlanConfig.clean` : règle FREE à 0 FCFA, limite MEDIUM ≤ PRO ; `SellerPriceOverride.plan` choices et `clean`) — règles de saisie de l'admin, pas des droits de vendeuse.
- **Rapport plateforme** : `subscriptions/services/platform_reporting.py:134` (`plan__in=[MEDIUM, PRO]`) — requête de reporting admin. Pourrait utiliser `PAID_PLANS`, non fait (hors droits).
- **Partenaires** : `partners/services/trial.py` (`sub.is_paid`) — déjà via la propriété, donc via le contrôle central.
- **Tarif spécial** : `subscriptions/services/plans.py` (`plan_offers`, `get_active_override`) et `subscriptions/services/payment.py` (`sub.is_paid`) — déjà via la propriété.
- **Assistance `analytics/services/monthly_report.py:effective_plan`** : calcule le libellé « plan effectif » pour l'admin ; non modifiée.

## 2026-11-22 — Fichiers

- `subscriptions/services/plans.py` : `PLAN_FEATURES`, `plan_has_feature`.
- `subscriptions/models.py` : `current_plan`, `is_paid`, `has_stats`, `has_advanced_stats` (via le contrôle).
- `subscriptions/services/payment.py` : garde d'achat ; import `Plan` retiré.
- `subscriptions/views.py` : garde de la page de paiement ; import `Plan` retiré.
- `flash_sales/views.py` : analytics (clé `has_advanced_stats`).
- `templates/flash_sales/analytics_dashboard.html` : 2 conditions renommées.
- `subscriptions/tests_plan_features.py` (nouveau) : 10 tests, 17 sous-tests.

## Vérifications

- `pytest --ds=config.settings.test subscriptions/tests_plan_features.py` : 10 passed.
- Lint (sélection CI `--select E,F,W --ignore E501`) : OK sur les fichiers modifiés et le nouveau test.
- `makemigrations --check` : voir résultat ci-dessous.
- Suite complète SQLite : voir résultat ci-dessous.
- **Vérification navigateur non faite** : la règle `when_to_verify` demandait une prévisualisation ; le worktree n'a pas de serveur de développement configuré, et le changement est couvert par les tests unitaires de droits et de comportement (les valeurs de droits de chaque plan sont identiques). Le rendu de la page d'analytique n'a pas été vu à l'écran.

## Incertitudes notées

- Le renommage de la clé de contexte `is_pro` → `has_advanced_stats` ne touche que `flash_sales/views.py` et `analytics_dashboard.html` ; si un autre gabarit lit `is_pro` depuis ce contexte, il ne recevra plus la valeur. Recherche faite : aucun autre usage.
- `Subscription.is_pro` teste toujours `plan == Plan.PRO` (identité d'affichage). C'est le point de vigilance SPEC_05 § 4 : tant que BUSINESS n'est pas ouvert, rien ne le signale ; à reprendre avec l'ouverture.

## Non fait / hors périmètre

- Pas de BUSINESS ajouté (demandé).
- Pas de changement des libellés d'affichage ni des gabarits d'affichage.

## Commandes de validation pour le fondateur

```
cd C:\projets\hf-d
C:\projets\hayaflash\.venv\Scripts\python.exe -m pytest --ds=config.settings.test subscriptions -q
C:\projets\hayaflash\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings.test
```
