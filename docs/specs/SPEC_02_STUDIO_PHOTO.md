# SPEC 02 — Studio HayaFlash : détourage des photos produits

Statut : prêt pour Claude Code. Priorité 2 (voir `docs/ROADMAP_V2_V3.md`).
Niveau de risque visé : faible — app séparée, worker isolé, aucune modification du circuit de commande.


> **Avant de commencer** : la liste de lancement et les règles communes de `docs/ROADMAP_V2_V3.md` §0 s'appliquent (prod = `/srv/hayaflash-prod`, port 8021, procédure de déploiement propre à la prod ; jamais de push, merge ni action VPS sans accord ; lettres figées intouchables).

## 1. Objectif

Sur une photo produit déjà téléversée, le vendeur appuie sur « ✨ Nettoyer le fond ». Le fond est
supprimé, le produit est centré sur un fond uni (blanc, gris clair ou autre couleur proposée),
recadré en carré. Le vendeur voit l'avant/après, choisit la couleur, valide — ou revient à l'original
à tout moment.

## 2. Mesures VPS (22/10/2026) et budget mémoire

- VPS : 8 Go RAM (≈ 6,5 Go disponibles), 4 vCPU Xeon E5-2650 v3 avec AVX2, 106 Go disque libre.
- Swap : 2,5 Go utilisés au moment de la mesure → surveiller (`vmstat 1 5`, colonnes si/so)
  avant et après la mise en service.
- Conteneurs existants limités à 512 Mo : conserver ce principe.
- **Budget Studio** : prod `mem_limit: 1536m`, `cpus: 1.5` ; staging `mem_limit: 1g`, et
  conteneur **arrêté hors des périodes de test**.

## 3. Architecture

- **Nouvelle app Django `studio`** (modèles, vues, URLs, tâches, templates propres).
- **Nouveau service Docker `worker-studio`** : `celery -A config worker -Q studio -c 1 --max-tasks-per-child=50`.
  Le worker existant (`-Q default,flash_sales,notifications`) ne consomme **pas** la file `studio`.
- **Image dédiée** : nouvelle étape `studio` dans le Dockerfile, qui installe `requirements-studio.txt`
  (`rembg` + `onnxruntime` CPU) et **télécharge le modèle au build** (`U2NET_HOME=/models`).
  L'image `web` n'installe pas ces paquets ; `rembg` n'est importé **que dans la tâche**.
- **Modèle de détourage** : `isnet-general-use` (bon compromis qualité/mémoire pour des produits).
- **Recoloration sans IA** : la tâche produit une fois la découpe transparente (PNG) ; changer de
  couleur de fond est un simple collage Pillow fait dans la requête web (rapide, sans worker).

## 4. Modèles (app `studio`, migrations additives uniquement)

`StudioAccess` — accès pilote : `seller` (FK unique), `created_at`, `notes`.

`StudioJob` :
- `seller` (FK), `media` (FK `products.ProductMedia`, on_delete CASCADE)
- `status` : pending / processing / done / failed / applied / reverted
- `original_file` (copie de l'image d'origine, `upload_to="studio/originals"`)
- `cutout_file` (PNG transparent, `upload_to="studio/cutouts"`)
- `result_file` (WebP final, `upload_to="studio/results"`)
- `background_color` (hex, défaut `#FFFFFF`)
- `error_message`, `duration_ms`, `created_at`, `finished_at`

Aucune modification de `products/models.py`.

## 5. Traitement (tâche `studio.tasks.cleanup_photo`, file `studio`)

1. Lire l'image de `media.file`, `exif_transpose`, réduire à 1024 px max (côté long) avant l'IA.
2. `rembg.remove()` → découpe RGBA ; recadrer sur la zone utile (`getbbox`).
3. Sauver la découpe en PNG (`cutout_file`).
4. Composer : carré 1080×1080, couleur choisie, produit centré occupant ~85 % du cadre ;
   WebP qualité ~82 → `result_file`.
5. Limites : `soft_time_limit=90`, `time_limit=120`. En cas d'échec : `status=failed`,
   message vendeur « Photo difficile à détourer. Réessaie avec le produit posé sur une surface unie, en lumière du jour. »
6. Mesurer et enregistrer `duration_ms`.

## 6. Application et retour à l'original

- **Appliquer** : copier l'original dans `original_file` (si pas déjà fait), puis remplacer le fichier
  du média par `result_file` via `ProductMedia.objects.filter(pk=…).update(file=…)` — **sans appeler
  `ProductMedia.save()`**, pour ne pas déclencher `resize_uploaded_image`. Vérifier ce point par un test.
- **Revenir à l'original** : même mécanisme en sens inverse, disponible tant que le job existe.
- Ainsi les pages clientes et le Marché affichent l'image nettoyée **sans aucune modification de leur code**.
- Action admin « Restaurer les originaux » (sélection de jobs) pour un retour arrière en masse.

## 7. Interface vendeur

- Bouton « ✨ Nettoyer le fond » sous chaque image, dans le formulaire produit et la Publication
  rapide, ajouté par **un seul `{% include "studio/_button.html" %}`** par template, affiché seulement
  si Studio actif et vendeur autorisé.
- HTMX : POST crée le job → interrogation toutes les 2 s → avant/après côte à côte.
- Pastilles de couleur : Blanc `#FFFFFF`, Gris clair `#F2F2F2`, Crème `#FAF6EF`, Noir `#111111`.
- Boutons « Utiliser cette photo » / « Garder l'originale » ; plus tard « Revenir à l'original ».
- Conseil affiché : « Pose le produit sur une surface unie, en lumière du jour. »
- Mobile d'abord (360 px), textes en français, tutoiement.

## 8. Garde-fous

- `STUDIO_ENABLED` (environnement, **False par défaut**) + accès limité aux vendeurs présents dans `StudioAccess`.
- `STUDIO_OPEN_TO_ALL` (False par défaut) pour ouvrir plus tard à tous sans migration.
- Quota : `STUDIO_DAILY_QUOTA` par vendeur (défaut 20), compté sur les jobs créés du jour.
- Un seul job en cours par média (refuser un double clic).
- Nettoyage (Celery beat) : supprimer découpes et résultats **jamais appliqués** de plus de 7 jours.
  Ne jamais supprimer un `original_file` dont le job est `applied`.

## 9. Périmètre des fichiers

**Autorisés :** nouvelle app `studio/` et `templates/studio/` ; une ligne d'include dans
`templates/products/product_form.html` et `templates/products/quick_publish.html` ;
`Dockerfile` (nouvelle étape) ; `docker-compose.yml` et `docker-compose.production.yml`
(**nouveau service uniquement**) ; `requirements-studio.txt` ; settings (`INSTALLED_APPS`, réglages,
route de tâche `studio.tasks.* → studio`) ; `config/urls.py` (un include) ; `.env.example`.

**Interdits :** `orders/`, `payments/`, `products/models.py`, `products/services/`, la commande et la
configuration du worker existant, toute migration hors app `studio`.

## 10. Phases

- **P0** — Branche `feature/studio`. Suite de tests verte avant de commencer.
- **P1** — App `studio`, modèles, migrations, admin (dont action « Restaurer les originaux »).
- **P2** — Service de traitement (fonctions pures Pillow + appel `rembg`) et tâche Celery.
- **P3** — Dockerfile étape `studio`, `requirements-studio.txt`, service `worker-studio` (dev + prod).
- **P4** — Vues HTMX, templates, include dans les deux pages produit.
- **P5** — Quotas, interrupteurs, nettoyage planifié.
- **P6** — Tests (ci-dessous), lint, documentation (`CLAUDE.md` : section Studio).

## 11. Tests

En CI, `rembg.remove` est **simulé** (renvoie une image RGBA) : aucun téléchargement de modèle.
1. Studio coupé → aucun bouton, URLs studio en 404 ; pages produit identiques à l'actuel.
2. Vendeur non autorisé → pas de bouton, POST refusé.
3. Tâche : produit un PNG transparent et un WebP 1080×1080 à la bonne couleur.
4. Appliquer → le média pointe vers le résultat, `ProductMedia.save()` non appelé, original conservé.
5. Revenir à l'original → fichier d'origine restauré.
6. Quota atteint → refus avec message clair.
7. Échec de la tâche → `failed`, message vendeur, aucun changement du média.
8. Nettoyage → supprime les jobs non appliqués > 7 jours, jamais les originaux appliqués.
9. Toute la suite existante passe, lint vert.

## 12. Validation sur le staging (48 h)

- Démarrer `worker-studio` (staging, 1 Go). Tester ≥ 20 vraies photos de téléphone : tissus,
  chaussures, cosmétiques, bijoux, sacs, produits sombres et clairs.
- Relever pendant les tests : `docker stats` (pic mémoire du worker), `free -h`, `vmstat 1 5`.
- **Critères d'acceptation** : pic mémoire < 1,2 Go ; 95 % des images traitées en < 10 s ;
  aucun ralentissement visible de hayaflash.com ni de symain ; pas de swap actif pendant les tests.
- Arrêter `worker-studio` staging après les tests.

## 13. Mise en production

1. Moment sans vente flash en cours. Sauvegarde base + médias, tag git `v-avant-studio`.
2. Construire les images (dont `studio`) **avant** de toucher aux conteneurs.
3. Déployer avec `STUDIO_ENABLED=False` ; tests rapides habituels.
4. Démarrer `worker-studio`, passer `STUDIO_ENABLED=True`, ajouter 2 à 3 vendeuses pilotes dans `StudioAccess`.
5. Surveiller mémoire et swap pendant les premiers jours.

## 14. Retour arrière

- Couper `STUDIO_ENABLED` → boutons masqués. Les photos déjà nettoyées restent affichées.
- Si besoin : action admin « Restaurer les originaux », puis arrêter `worker-studio`.
- Aucune autre donnée touchée.

## 15. Hors périmètre (V2)

Ombre portée sous le produit, couleur de fond aux couleurs de la boutique, nettoyage automatique
dès le téléversement, ouverture à tous les vendeurs, quotas différents selon l'abonnement.
