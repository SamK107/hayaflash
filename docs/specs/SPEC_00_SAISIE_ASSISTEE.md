# SPEC 00 — Saisie assistée (l'équipe crée la vente flash POUR un vendeur)

Statut : **implémenté le 22/10/2026** (non commité, à valider sur le staging) — app `assist`, 26 tests, suite complète 1916 verts, lint vert, aucune migration. **Priorité 1, avant toute autre fonctionnalité.**
Source : passation du 22/10/2026. Règles communes : `docs/ROADMAP_V2_V3.md` §0.
Branche : `feat/saisie-assistee`. L'essai de bout en bout de la production est validé (pilotes lancés) :
fusion possible après validation de cette fonctionnalité sur le staging.

## 1. Besoin

Cohorte 1 : 8 vendeuses pilotes, majoritairement peu à l'aise avec l'informatique, sur smartphone.
Toutes auront besoin d'aide pour la première vente, beaucoup ensuite. L'équipe doit pouvoir créer
une vente flash et ses produits **pour** un vendeur, **sans se connecter à son compte**.

**Interdits :** demander le mot de passe du vendeur ; se connecter « en tant que » ; session
d'assistance (écartée : 4 à 5 jours, risque élevé sur toutes les vues et sur l'auteur des audits) ;
modifier mot de passe, téléphone, paiements ; envoyer un message au nom du vendeur.

**Écarté :** OCR (photos sans étiquette lisible, moteur lourd sur VPS partagé), Excel (inadapté au public).

## 2. Processus métier

1. Le vendeur envoie par WhatsApp photos, noms, prix, prix promo éventuels et stocks (vocal possible).
   **Ce message est conservé comme preuve** : les CGU rendent le vendeur responsable de ses prix et stocks.
2. L'équipe prévient le vendeur qu'elle crée la vente pour lui, puis saisit.
3. L'équipe envoie au vendeur le lien de sa vente (`/f/<slug>/`) ; le vendeur garde la main sur
   l'ouverture, les commandes et les livraisons depuis son compte.

## 3. Faits du code (rapport de lecture du 22/10)

- `enforce_creation_rules` (appelée par l'admin, `admin.py:56`, et par l'interface vendeur) applique
  les règles de création ; le slug est généré par `FlashSale.save()`.
- **Écarts de l'admin Django actuel** : date de début passée acceptée ; statut librement modifiable ;
  durée saisie à la main ; catégorie, teasers et description vocale absents.
- **Trous côté produit en admin** : prix 0 et stock négatif acceptés (`create_product` les refuse,
  `crud.py:25-28`) ; aucun `StockMovement` initial (`crud.py:48` en crée un) ; propriétaire nullable
  (`models.py:19`) ; `FlashSaleProductAdmin` ne vérifie pas que le produit appartient au vendeur de la vente.
  → **L'admin Django brut ne doit pas servir à saisir des produits pour les vendeurs.**
- Outil existant : `/admin/sellers/<seller_id>/<sale_pk>/quick-publish/` (`urls.py:15`, `views.py:144`),
  `?seller_id=` (`mixins.py:24`), audit `is_admin_action`. Aucun lien n'y mène ; il ne crée pas la vente.
- QR : calculé à la volée, réservé au vendeur propriétaire (staff sans boutique = 403).
- Le prix promo existe déjà (`FlashSaleProduct.promo_price`) : **aucune migration**.

## 4. Solution

- **Point d'entrée** : action « Saisie assistée » sur la fiche vendeur de l'admin (et lien depuis
  `platform-admin/boutiques/`), réservée au staff.
- **Bandeau permanent** sur toutes les pages du parcours : « Saisie assistée pour [nom de la boutique] ».
- **Étape 1 — la vente** : formulaire passant par le service `create_flash_sale` avec le vendeur comme
  propriétaire : **mêmes règles que l'interface vendeur** (2 h max, 3 ventes par jour, quota du plan,
  créneau, date de début non passée). Mêmes champs que le vendeur (titre, début, durée 1 h / 2 h /
  personnalisée 15-120 min, zone, type, couverture).
- **Étape 2 — les produits** : sélection de **plusieurs photos en une fois**, puis **un bloc par photo**
  aux champs **empilés** (responsive) : nom, prix, prix promo (facultatif), stock, unité (« pièce » par
  défaut). Création via `create_product` (refus prix ≤ 0 et stock < 0, `StockMovement` initial) et
  rattachement à la vente avec le prix promo.
  En P0, évaluer la réutilisation de l'outil `quick-publish` admin existant pour l'étape 2 ; le
  réutiliser s'il permet la saisie en blocs empilés, sinon page dédiée appelant les mêmes services.
- **Fin** : récapitulatif + lien `/f/<slug>/` à copier pour l'envoyer au vendeur par WhatsApp.
- **Audit** : chaque création journalisée avec **l'auteur réel** (membre de l'équipe) et
  `is_admin_action=True`, plus un champ libre « Référence de la demande WhatsApp » (date/heure du message).

## 5. Périmètre des fichiers

**Autorisés :** nouvelles vues/URLs/templates de saisie assistée (dans l'app la plus proche des
services, ou une nouvelle app `assist`) ; action et lien dans l'admin vendeur ; lien dans
`platform-admin/boutiques/` ; tests.
**Interdits :** `orders/`, `payments/`, `partners/legal_docs.py` et `templates/partners/legal/`
(lettres figées, SHA-256 verrouillés), les services `create_flash_sale` / `create_product`
(**appel autorisé, modification interdite**), toute migration (aucune n'est nécessaire).

## 6. Phases

- **P0** — Branche, suite de tests verte (PostgreSQL `hf-pg-test` port 55432 + sqlite), lecture des
  services et de l'outil `quick-publish` ; décision réutiliser / page dédiée consignée.
- **P1** — Tests rouges d'abord (§7).
- **P2** — Étape 1 (vente) + bandeau + contrôle d'accès staff.
- **P3** — Étape 2 (multi-photos, blocs empilés) + rattachement à la vente.
- **P4** — Récapitulatif, lien à copier, audit, liens d'entrée (admin + platform-admin).
- **P5 (recommandée)** — Durcissement de l'admin Django brut : refus prix ≤ 0 et stock < 0,
  vérification propriétaire produit = vendeur de la vente, date de début non passée à la création,
  propriétaire obligatoire. Modifications **limitées aux formulaires admin**, testées.
- **P6** — Lint (`ruff check . --select E,F,W --ignore E501` → « All checks passed! »),
  `makemigrations --check` (aucune migration), documentation `CLAUDE.md`.

## 7. Tests

1. Non-staff → 403 sur toutes les pages de saisie assistée.
2. Vente créée par l'équipe : propriétaire = vendeur choisi ; règles appliquées (2 h, 3/jour, quota,
   créneau, début non passé) **identiques** à l'interface vendeur (mêmes messages d'erreur).
3. Produits : prix ≤ 0 et stock < 0 refusés ; `StockMovement` initial créé ; propriétaire = vendeur ;
   prix promo enregistré sur la vente et facturé (non-régression `test_order_snapshot_price_is_promo_price`).
4. Audit : auteur réel = membre de l'équipe, `is_admin_action=True`, référence WhatsApp conservée.
5. Aucune page du parcours n'expose ni ne modifie mot de passe, téléphone, paiement ; aucun envoi de message.
6. Le vendeur voit ensuite la vente et ses produits dans son propre compte, peut l'ouvrir et gérer ses commandes.
7. Toute la suite existante passe ; lint vert ; aucune migration.

## 8. Validation et mise en production

- L'essai de bout en bout de la production est validé (ROADMAP §0).
- Staging : saisie complète pour un vendeur de test depuis un PC **et** un téléphone ; vérification
  côté vendeur (vente visible, ouverture, commande test).
- Production : suivre la procédure **de production** (jamais les commandes de staging) ; sauvegarde
  préalable ; déploiement ; une saisie réelle accompagnée pour la première vendeuse pilote.

## 9. Plus tard (selon l'usage)

Mode simplifié dans le compte du vendeur : plusieurs photos d'un coup, un produit par écran.
Courtes vidéos de tutoriel par étape (données de démonstration, datées), à partir de `core/guide.py`
(24 diapositives ; écarts à intégrer : case CGU, durée personnalisée, ouverture manuelle).

## 10. Implémentation (22/10/2026)

- App `assist` : `forms.py` (formulaire vendeur + référence WhatsApp), `services.py` (lecture/validation
  des blocs, création tout-ou-rien), `views.py`, `urls.py`, `tests.py` (26 tests).
- URLs : `/platform-admin/saisie/<seller_id>/` → `.../vente/<id>/produits/` → `.../vente/<id>/fin/`.
- Templates `templates/assist/` (bandeau, étape 1, étape 2, fin) ; JS `static/js/hf-assist.js`
  (blocs empilés, réduction des photos à 1600 px JPEG avant envoi, 20 produits max par envoi).
- Entrées : lien « Saisie » dans `/platform-admin/boutiques/`, colonne « Saisie assistée » dans l'admin Vendeurs.
- Décision P0 : page dédiée plutôt que l'outil `quick-publish` (il ne crée pas la vente et ne gère pas
  la sélection multiple en blocs empilés).
- P5 (durcissement de l'admin Django brut) : **non fait**, reste recommandé.
- Non vérifié ici : série PostgreSQL (`hf-pg-test`) et rendu réel sur téléphone → à faire sur le staging.
