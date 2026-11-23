# JOURNAL H — Pillow 12.3.0 → 13.0.0 (correctifs de sécurité)

Branche : `task/h-pillow-13`, depuis `integration/v2` (worktree `C:\projets\hf-h`). Pas de push, pas de fusion.

## Décisions
- Montée de `pillow==12.3.0` à `pillow==13.0.0` dans `requirements.txt` (ligne 26). Aucun autre fichier de dépendances ne fige Pillow (`requirements-dev.txt` n'en parle pas, pas de lock file).
- `python-pptx` : absent de `requirements*.txt` et du code ; rien à vérifier côté pptx. À signaler si une dépendance pptx est ajoutée plus tard.

## Vérifications
- `pip check` : aucune dépendance cassée.
- Usage Pillow dans le code : `core/services/image_optimize.py`, `core/services/thumbnails.py`, `core/validators.py`, `scripts/*`, commandes de seed. Aucune API listée comme retirée dans les notes de version 13.0.0 (ImageCms product_name/product_info, `fromarray` mode, `Image._show`, `get_child_images`) n'est utilisée. `Image.LANCZOS` / `Image.BICUBIC` utilisés tels quels : aucun changement de code nécessaire.
  - Note : les notes 13.0.0 consultées étaient un brouillon « unreleased » ; à relire à la publication.
- Tests ciblés images (247 réussis, 106 sous-tests) : accounts/tests_avatar_optimize, assist/tests, core/tests_uploads, core/tests_links, core/tests_og_meta, distrib/tests_catalog, distrib/tests_allocation, flash_sales/tests_marche_vitrine, partners/tests_referral_qr, products/tests_quick_publish, orders/tests_seller_actions, partners/tests_documents_admin.
- `pip-audit -r requirements.txt` (local) : Pillow n'apparaît plus. Restent 7 avis hors périmètre de cette tâche : djangorestframework 3.17.2 (CVE-2026-114136/114137/114138, corrigé en 3.18.2), brotli 1.2.0 (PYSEC-2026-4322, corrigé en 1.2.1), certifi 2026.2.25 (PYSEC-2026-4320, corrigé en 2026.10.18).

## Hors périmètre (signalé, non traité)
- Mettre à jour djangorestframework, brotli, certifi : dépendances différentes, à traiter dans une tâche séparée (DRF 3.18 peut changer le comportement de l'API).
- Tests non lancés : suite complète, tests de seed, `core/tests_deploy_nginx_recreate.py`.
