# SPEC 01 — Prix barré + « Prix promo » sur la page de commande cliente

Statut : prêt pour Claude Code. Priorité 1 (voir `docs/ROADMAP_V2_V3.md`).
Niveau de risque visé : quasi nul — affichage uniquement, aucune migration.


> **Avant de commencer** : la liste de lancement et les règles communes de `docs/ROADMAP_V2_V3.md` §0 s'appliquent (prod = `/srv/hayaflash-prod`, port 8021, procédure de déploiement propre à la prod ; jamais de push, merge ni action VPS sans accord ; lettres figées intouchables).

## 1. Objectif

Pendant une vente flash, sur la page où la cliente commande (`templates/orders/client_order.html`),
quand un produit a un prix promo inférieur à son prix catalogue, afficher :

```
7 500 FCFA                ← prix promo, gros, couleur principale
10 000 FCFA   −25 %       ← prix catalogue gris et barré + pastille
Prix promo · Tu économises 2 500 FCFA
```

La page Marché (`flash_sales/partials/_calendar_list.html`) affiche déjà prix barré et
pastille : on aligne la page de commande sur ce comportement.

## 2. Ce qui existe (à ne pas modifier)

- `Product.price` = prix catalogue ; `FlashSaleProduct.promo_price` = prix de la vente
  (facultatif) ; `FlashSaleProduct.effective_price` = prix appliqué.
- `products/services/crud.py::products_for_sale()` remplace en mémoire `product.price`
  par `link.effective_price` (jamais persisté).
- Le prix facturé est déjà le prix promo (test `test_order_snapshot_price_is_promo_price`).
- Le JavaScript de `client_order.html` lit `product.price` (ligne `price: {{ product.price|floatformat:0 }}`) :
  **il doit rester strictement inchangé**.

## 3. Périmètre des fichiers

**Autorisés :**
- `products/services/crud.py` — une seule ligne ajoutée dans `products_for_sale()`.
- `orders/views.py` — ajout d'une clé au contexte de la vue qui rend `client_order.html`, rien d'autre.
- `templates/orders/client_order.html` — bloc d'affichage du prix uniquement.
- Le fichier de settings + `.env.example` — un réglage.
- Nouveau fichier de tests `orders/tests_prix_barre.py`.
- CSS : réutiliser les classes existantes du Marché (`hfc-off`…) ; si une classe manque,
  l'ajouter sans modifier les existantes.

**Interdits :** `orders/services/create_order.py`, `orders/services/stock_release.py`,
tout le dossier `payments/`, tous les `models.py`, toute migration, le JavaScript de commande.

## 4. Phases

### P0 — Préparation
- Branche `feature/prix-barre`. Vérifier que la suite de tests passe avant tout changement.

### P1 — Exposer le prix catalogue (1 ligne)
Dans `products_for_sale()`, juste **avant** `product.price = link.effective_price` :
```python
product.catalog_price = product.price  # prix catalogue, pour affichage (prix barré)
```
Attribut en mémoire uniquement, jamais sauvegardé.

### P2 — Interrupteur global
- Réglage `HAYAFLASH_PROMO_DISPLAY` lu depuis l'environnement, **False par défaut**.
- Ajouté dans `.env.example` avec un commentaire.
- La vue de `client_order.html` passe `promo_display_enabled` au contexte.

### P3 — Affichage
Afficher le bloc promo seulement si les trois conditions sont vraies :
`promo_display_enabled` ET `product.catalog_price` défini ET `product.catalog_price > product.price`.
Sinon, affichage actuel **identique au caractère près**.

Règles d'affichage :
- Prix promo en premier, gros, couleur principale (comme aujourd'hui).
- Prix catalogue plus petit, gris, barré (`<s>`), précédé d'un texte lisible par les lecteurs
  d'écran : `<span class="sr-only">au lieu de</span>`.
- Pastille `−X %` : **réutiliser exactement le calcul de remise du Marché** (le localiser dans
  le code du Marché/vitrine et l'appeler ou le reproduire à l'identique, mêmes arrondis), pour
  que la cliente voie le même pourcentage sur le Marché et à la commande.
- Ligne « Prix promo · Tu économises N FCFA », N = catalogue − promo, format milliers sans décimales.
- Tout en FCFA entiers, jamais de centimes.
- Mobile d'abord : lisible à 360 px de large, sans débordement.

### P4 — Tests (`orders/tests_prix_barre.py`)
1. Interrupteur coupé + produit en promo → aucune mention « Prix promo », pas de `<s>` : rendu identique à l'actuel.
2. Interrupteur actif + promo 7 500 / catalogue 10 000 → contient « 10 000 », « −25 % », « Tu économises 2 500 », « Prix promo ».
3. Interrupteur actif + promo égale au catalogue → pas de bloc promo.
4. Interrupteur actif + produit sans promo → pas de bloc promo.
5. Le JavaScript de la page contient toujours le prix promo (7500), pas le prix catalogue.
6. `products_for_sale()` : `catalog_price` = prix catalogue, `price` = prix promo.
7. Toute la suite existante passe (dont `test_order_snapshot_price_is_promo_price`), lint vert.

### P5 — Staging (48 h)
- Déployer avec l'interrupteur **coupé** : vérifier que rien n'a changé.
- Activer l'interrupteur (variable d'environnement + redémarrage du conteneur `web`).
- Tester sur 2 vrais téléphones (petit écran Android compris) : une vente avec promo, une sans,
  une commande complète jusqu'au bout. Vérifier que le montant commandé = prix promo.

### P6 — Production
1. Moment sans vente flash en cours.
2. Sauvegarde base + médias, tag git `v-avant-prix-barre`, noter l'image en service.
3. Déployer avec l'interrupteur **coupé**, tests rapides (connexion vendeur, page vente, commande test).
4. Activer l'interrupteur, revérifier la page de commande d'une vente en promo.

## 5. Retour arrière
- Premier réflexe : couper `HAYAFLASH_PROMO_DISPLAY` et redémarrer `web` → affichage d'avant.
- Sinon : redéployer l'image du tag précédent. Aucune donnée à restaurer (pas de migration).

## 6. Hors périmètre (V2 éventuelle)
- Choix du mode d'affichage par vente (Urgence / Économie / Prix net).
- Garde-fou contre les remises suspectes (ex. > 70 %), à appliquer alors aussi au Marché.
- Prix de référence « plus bas des 30 derniers jours » (règle européenne anti-fausses promos).
