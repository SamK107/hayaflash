# JOURNAL I — Avis pip-audit restants (certifi, brotli, djangorestframework)

Branche : `task/i-deps-audit`, depuis `integration/v2` (5d518a5, qui contient la tâche H). Worktree `C:\projets\hf-i`. Pas de push, pas de fusion.

## Commits
- `4dd74b3` : certifi 2026.2.25 → 2026.10.18 (PYSEC-2026-4320).
- `1cead3d` : Brotli 1.2.0 → 1.2.1 (PYSEC-2026-4322).
- djangorestframework : **non monté** (voir ci-dessous).

## djangorestframework 3.17.2 → 3.18.2 : point d'arrêt (règle d), DRF laissé de côté
Notes de version lues (site officiel + GitHub, 3.18.0 à 3.18.2). Changements visibles qui touchent l'API :
- 3.18.0 : « Change errors for list serializers (`many=True`) to dict format » (PR #9837) : le format des erreurs de validation des listes change. Le projet expose une API (`/api/v1/`) : format de réponse modifié. Rupture.
- 3.18.0 : retrait du support de Django 4.2, 5.0, 5.1 (le projet est en Django 5.2 : sans effet).
- 3.18.1 : rejet des valeurs non finies (nan, inf) dans `FloatField` : comportement de validation modifié.
- 3.18.1 : « compatibility setting for ListSerializer error formats » (PR #10027) : réglage de compatibilité, nom non confirmé.
- 3.18.2 : « Refuse non-text encoding charsets » (GHSA-3547-9m27-7rxg) : le code de réponse n'est pas précisé.
- 3.18.2 : « Make TokenProxy deletion actually delete the token » (GHSA-xw6w-gcfp-cf8m) : suppression de token modifiée.
- 3.18.3 (6 oct. 2026) : corrige une régression introduite par 3.18.2 (« order_by_precedence » modifié par erreur). La cible de sécurité devrait donc être 3.18.3, à confirmer.

Conclusion : la montée change le format d'erreur des listes et des comportements de validation/authentification. La règle d s'applique. Aucun test n'a été modifié.

## Vérifications
- `pip check` : aucune dépendance cassée.
- `pip-audit -r requirements.txt --desc on` : **3 avis restants**, tous sur djangorestframework 3.17.2 (corrigé en 3.18.2, et 3.18.3 pour la régression).
- Tests lancés (certifi + brotli, DRF inchangé) : subscriptions (Orange Money : env, paiements, statut, webhook, webhookLog, vues billing), analytics/tests_paiement_om, accounts/tests_api_auth_removed, orders (API, seller actions, limite de téléphone, tests.py), core/tests_phone_logs. Résultat : 206 réussis, 2 ignorés, 1 xfail.
- Non lancés : suite complète, tests de seed, core/tests_deploy_nginx_recreate.py.

## Questions ouvertes
1. Faut-il monter DRF à 3.18.3 et adapter le format d'erreur des listes (ou garder le format actuel via le réglage de compatibilité 3.18.1, dont le nom reste à confirmer) ? Décision produit : format d'erreur visible par les clients de l'API.
2. Accepter la cible 3.18.3 plutôt que 3.18.2 ?
3. Le test d'erreur des listes et le test FloatField n'ont pas été analysés : à faire dans la tâche DRF.
