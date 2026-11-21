# Gouvernance des évolutions post-production — HayaFlash

> Statut : en vigueur à partir du 22 oct. 2026. hayaflash.com est en production avec de vrais clients.
> Ce document s'applique à TOUTE évolution : prix barré, Studio photo, module Distrib, et les suivantes.
> Specs détaillées : `SPEC_PRIX_BARRE.md`, `SPEC_STUDIO.md`, `SPEC_DISTRIB.md` (même dossier).

## 1. Ordre de livraison

| Ordre | Évolution | Branche | Mise en prod |
|---|---|---|---|
| 1 | Prix barré + « Prix promo » | `feature/prix-barre` | dès staging vert 24 h |
| 2 | Studio photo | `feature/studio` | après go/no-go RAM + staging vert 48 h |
| 3 | Module Distrib V1 | `feature/distrib` | dernier ; staging vert 48 h + pilote 1 grossiste |

Les trois branches peuvent avancer en parallèle en local. Elles sont **fusionnées et déployées une par une**, jamais ensemble : si un problème survient en prod, on sait laquelle l'a causé.

## 2. Règles intangibles (« ce qu'on ne touche pas »)

**Fichiers et zones protégés** — aucune modification sans décision écrite dans `docs/decisions/` :
- `orders/services/create_order.py`, `orders/services/stock_release.py`
- `orders/models.py` (dont `OrderStatus`), `delivery/models.py`, tout `payments/`
- les migrations déjà appliquées en prod (aucune édition, aucune suppression)
- `subscriptions/` (quotas, plans)

**Migrations autorisées** : `CREATE TABLE`, `ADD COLUMN` nullable ou avec `default`, `CREATE INDEX`, nouvelles valeurs de `choices`.
**Migrations interdites** : renommer / supprimer une colonne ou une table, changer un type, `RunPython` qui modifie des données existantes.

**Commande interdite sur le VPS** : `docker compose down -v` (supprime la base et les médias).

## 3. Principes de conception

1. **Nouvelle app Django par module** (`studio`, `distrib`). Le code existant n'est touché que par des ajouts minimes (un bouton, un bloc de template conditionnel).
2. **Interrupteurs (feature flags)** : modèle unique `core.FeatureFlag` créé dans la 1re évolution qui en a besoin :
   - `key` (slug unique), `enabled` (bool, défaut `False`), `all_sellers` (bool, défaut `False`), `sellers` (M2M vers `SellerProfile`, vide), `updated_at`.
   - Helper : `core.flags.is_enabled(key, seller=None) -> bool` (cache 60 s).
   - Gérable depuis l'admin Django : activer pour 1 pilote, puis pour tous, ou tout couper en 1 clic.
3. **Découplage** : un module ne s'insère jamais dans la transaction d'une commande (pas de signal `post_save` sur `Order`). Il lit les données existantes et réagit après coup (tâche Celery périodique idempotente).
4. **Lecture plutôt qu'écriture** sur les modèles existants. Toute écriture sur un modèle existant passe par un service dédié, transactionnel, avec `select_for_update` si elle touche le stock, et journalise un `StockMovement`.
5. **Montants en FCFA entiers** partout (jamais de centimes).
6. **Textes en français en dur**, tutoiement pour les vendeurs et clientes.

## 4. Garde-fous automatiques (CI)

Ajouter à la CI GitHub Actions, dès la 1re évolution :

1. `python manage.py makemigrations --check --dry-run` (aucune migration oubliée).
2. **Contrôle des zones protégées** — script `scripts/check_protected_paths.sh` :
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   PROTECTED='^(orders/services/create_order\.py|orders/services/stock_release\.py|orders/models\.py|delivery/models\.py|payments/|subscriptions/)'
   CHANGED=$(git diff --name-only origin/main...HEAD | grep -E "$PROTECTED" || true)
   if [ -n "$CHANGED" ] && [ "${ALLOW_PROTECTED:-0}" != "1" ]; then
     echo "Zones protégées modifiées :"; echo "$CHANGED"; exit 1
   fi
   ```
   Exception : seulement les nouvelles migrations des apps protégées, si une spec le prévoit explicitement.
3. **Contrôle des migrations** — script `scripts/check_migrations_additive.py` : pour chaque nouvelle migration, lire `sqlmigrate` et échouer si le SQL contient `DROP`, `RENAME`, `ALTER COLUMN ... TYPE`.
4. Suite de tests complète verte ; couverture ≥ niveau actuel (67 %) ; lint vert.

## 5. Définition de « terminé » pour chaque phase

- Code + tests de la phase verts en local (`pytest`).
- Garde-fous CI verts.
- `PROGRESS.md` mis à jour (1 ligne par phase).
- Flag désactivé par défaut vérifié : **avec le flag éteint, l'application se comporte exactement comme avant** (test dédié).

## 6. Process de mise en ligne (identique pour chaque évolution)

### 6.1 Staging
1. Fusion de la branche dans `main` (PR, CI verte).
2. Déploiement sur staging.hayaflash.com.
3. Recette avec la checklist de la spec (vrais téléphones, données réalistes).
4. Flag ON pour un vendeur de test, puis OFF : vérifier les deux états.
5. Observation : 24 h (prix barré) ou 48 h (Studio, Distrib) sans erreur Sentry nouvelle.

### 6.2 Production
1. **Moment** : aucune vente flash en cours (vérifier dans l'admin), de préférence tôt le matin.
2. **Sauvegarde** : `pg_dump` + volume `media`, copie chiffrée (age) sur D: (voir `SAUVEGARDES.md`).
3. **Repères de retour arrière** : tag git `vX.Y-avant-<module>` + noter le tag de l'image Docker en cours.
4. `docker compose -f docker-compose.production.yml build` **avant** tout arrêt.
5. `docker compose -f docker-compose.production.yml up -d` puis `python manage.py migrate`.
6. Tests rapides : connexion vendeur, page Marché, création d'une vente test, page de commande cliente, symain.africa et services.symain.africa répondent.
7. Flag ON pour **un seul** vendeur pilote. Observer 48 h. Puis élargir.

### 6.3 Retour arrière (dans cet ordre)
1. Couper le flag dans l'admin → comportement d'origine immédiat.
2. Si insuffisant : redéployer l'image du tag précédent (`IMAGE_TAG=<ancien> docker compose ... up -d`). Les tables ajoutées restent, l'ancien code les ignore.
3. Dernier recours seulement : restauration de la sauvegarde.

## 7. Charte graphique

- Prix barré, Studio : charte HayaFlash existante, composants existants.
- Module Distrib : **même système de design** (Tailwind, typographie, composants, icônes) avec une **identité de sous-marque « HayaFlash Distrib »** : couleur d'accent distincte, badge « DISTRIB » à côté du logo, mise en page plus dense orientée tableaux. Détails dans `SPEC_DISTRIB.md`.

## 8. Journal des décisions

| Date | Décision |
|---|---|
| 22/10/2026 | Adoption de cette gouvernance ; ordre prix barré → Studio → Distrib |
| 22/10/2026 | `core.FeatureFlag` comme mécanisme unique d'activation progressive |
| 22/10/2026 | Distrib : aucun signal sur `Order`, synchronisation par tâche Celery périodique |
