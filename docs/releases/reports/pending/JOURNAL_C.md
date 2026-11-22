# Journal — Tâche C : contrôle du stock négatif et migration `products.0011`

Branche : `task/c-stock-0011` (worktree `C:\projets\hf-c`). Base : `0d2b9e1`.

## 2026-11-22 — Décisions

| Décision | Raison | Alternative écartée |
|---|---|---|
| Commande `controle_stock_negatif` **en lecture seule** : liste les produits (`stock_available < 0`) et les variantes (`stock < 0`), code d'erreur si au moins une ligne. | Demande de la tâche. Le code d'erreur permet un contrôle scripté avant déploiement. | Corriger automatiquement les lignes : écarté, une correction de stock est une décision humaine (EXECUTION_V2 § 1, b). |
| Option `--database` (alias Django) en plus de `--settings`. | Permet de cibler une base sans changer de réglage (ex. base de test). | Lire l'URL de base depuis l'environnement : écarté, moins explicite. |
| Aucune donnée personnelle affichée : identifiants, nom du produit, stock. | Journal et sortie peuvent être partagés. | Afficher le téléphone de la vendeuse : écarté. |
| Test de détection sur SQLite avec `PRAGMA ignore_check_constraints` (désactivé aussitôt après). | La contrainte CHECK empêche d'écrire une ligne négative ; sans ce moyen, le chemin « échec » ne serait pas testé. | Mock des requêtes seulement : écarté, ne prouve pas la requête réelle. Le test est marqué `sqlite_only`. |
| Migration `0011` **non modifiée**. | Demande de la tâche (déjà commitée). | — |

## Fichiers

- `products/management/commands/controle_stock_negatif.py` (nouveau) : commande + fonctions `negative_products()` et `negative_variants()`.
- `products/tests_controle_stock_negatif.py` (nouveau) : base saine (succès, rien modifié), produit négatif, variante négative, alias inconnu, zéro non négatif.

## Vérifications (SQLite)

- `pytest --ds=config.settings.test products/tests_controle_stock_negatif.py products/tests_stock_contrainte.py` : 9 passed.
- `ruff check --select E,F,W --ignore E501` sur la commande et son test : OK.
- `makemigrations --check` et suite complète : voir le rapport de fin de tâche.

## Procédure de contrôle puis d'application de la migration 0011

**Principe.** La migration `0011` vérifie elle-même les données dans la même transaction : si une ligne a un stock négatif, elle échoue en `RuntimeError` et rien n'est modifié (transaction annulée). Le contrôle préalable évite donc un échec en production, et permet de corriger les lignes avant.

**Rappel :** cette procédure ne s'exécute **pas** sans validation explicite du fondateur pour chaque cible distante (EXECUTION_V2 § 1, a). Aucune action n'a été faite à distance.

### Étape 0 — Prérequis (toutes cibles)

1. Le commit contenant `0011` et la commande est sur la branche qui sera déployée (`integration/v2` après fusion validée, ou la branche de déploiement désignée par le fondateur). Pas de fusion dans `main` par cette tâche.
2. Suite de tests verte en SQLite (`config.settings.test`) sur ce commit.
3. Aucun `migrate` ni `runserver` sur une base partagée depuis un worktree de tâche.

### Étape 1 — Contrôle en lecture seule, locale (poste de développement)

Sur une base **locale** dédiée (jamais la base PostgreSQL de développement partagée) :

```
cd C:\projets\hf-c
C:\projets\hayaflash\.venv\Scripts\python.exe manage.py controle_stock_negatif --settings=config.settings.dev
```

Code de sortie 0 : la migration peut être appliquée localement. Code 1 : corriger les lignes listées (voir étape 4).

### Étape 2 — Staging (action distante : validation du fondateur requise)

**Stop : demander l'accord avant chaque commande ci-dessous.**

1. **Sauvegarde datée** de la base staging avant toute opération (procédure `docs/SAUVEGARDES.md`).
2. **Contrôle** (lecture seule) dans le conteneur de staging, dossier `/srv/hayaflash` (projet `hayaflash`) :
   `docker compose -p hayaflash -f docker-compose.production.yml exec web python manage.py controle_stock_negatif --settings=config.settings.staging`
   *(commande à confirmer par le fondateur avant exécution : nom du fichier compose et du service.)*
3. Si code 0 : déployer le commit (procédure staging `infra/scripts/deploy_vps.sh /srv/hayaflash`, validation du fondateur). La migration `0011` s'applique au démarrage ou par `migrate` dans le conteneur.
4. **Vérification** : `python manage.py showmigrations products` doit lister `0011_stock_non_negatif` appliquée ; tests de non-régression stock (`products/tests_stock_contrainte.py`) rejoués sur staging si la procédure le prévoit.
5. Laisser staging tourner **48 h** sans incident (règle commune ROADMAP § 0).

### Étape 3 — Production (action distante : validation du fondateur requise)

**Stop : demander l'accord avant chaque commande ci-dessous.** Procédure de production distincte de celle du staging (ROADMAP § 0) : ne jamais réutiliser les commandes de staging.

1. Staging vert pendant 48 h.
2. **Tag git de retour** posé sur le commit précédant la 0011 ; **sauvegarde datée** de la base prod (`/home/sam/hf-backup-prod.sh` ou procédure validée), copie sur le disque D:.
3. **Contrôle** lecture seule dans le conteneur prod, dossier `/srv/hayaflash-prod` (projet `hayaflash-prod`, port 8021) :
   `docker compose -p hayaflash-prod -f docker-compose.production.yml exec web python manage.py controle_stock_negatif --settings=config.settings.prod`
   *(à confirmer : nom du fichier compose de prod et du service.)*
4. Si code 1 : **ne pas déployer**. Corriger à la main les lignes listées, sur validation écrite du fondateur, avec trace ; relancer le contrôle jusqu'au code 0.
5. Si code 0 : déployer le commit (`infra/scripts/deploy_vps.sh /srv/hayaflash-prod`, validation du fondateur). La migration s'applique dans une transaction.
6. **Vérification** : `showmigrations products` ; lecture de la page produit et d'une commande test (sans montant réel) ; surveiller les logs 30 min.

### Étape 4 — Correction d'un stock négatif (si le contrôle échoue)

- Ne jamais corriger par une requête SQL directe sans validation écrite : une correction de stock est une décision humaine.
- Cause probable : une vente ou une commande a décrémenté au-delà du stock disponible (survente) avant la contrainte. Identifier la cause avant de corriger.
- Correction proposée : `adjust_stock` (services existants, mouvement tracé dans `StockMovement`) ou décision du fondateur sur la valeur cible.
- Relancer le contrôle après chaque correction.

### Retour arrière

- Migration réversible : `migrate products 0010` retire les deux contraintes (`reverse_code` = noop pour la vérification, `AddConstraint` inversé). Données inchangées.
- Retour applicatif : redéployer le tag posé à l'étape 3.2.
- Tout retour en arrière en production demande la validation du fondateur.

## Incertitudes notées

- Les noms exacts du fichier `docker-compose` et du service `web` sont repris de `CLAUDE.md` et du `ROADMAP` ; **non vérifiés sur le VPS**. À confirmer avant toute exécution.
- Le contrôle ne couvre que les stocks **négatifs** : il ne détecte pas une incohérence entre `stock_available` et la somme des `StockMovement` (test `tests_adjust_stock_concurrency.py` couvre ce point côté applicatif).

## Non fait / hors périmètre

- Aucune exécution distante, aucun `migrate`, aucune modification de la migration `0011`.
- Pas de correction automatique des lignes négatives.

## Commandes de validation pour le fondateur

```
cd C:\projets\hf-c
C:\projets\hayaflash\.venv\Scripts\python.exe -m pytest --ds=config.settings.test products -q
C:\projets\hayaflash\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings.test
```
