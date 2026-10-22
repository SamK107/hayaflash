# SPEC 03 — Module Distrib V1 (grossistes / revendeurs)

Statut : prêt pour Claude Code. Priorité 3 (voir `docs/ROADMAP_V2_V3.md`, section 3).
Niveau de risque visé : faible — app indépendante, lecture seule du circuit de commande,
aucune modification de `orders/`, `payments/` ni des modèles existants.


> **Avant de commencer** : la liste de lancement et les règles communes de `docs/ROADMAP_V2_V3.md` §0 s'appliquent (prod = `/srv/hayaflash-prod`, port 8021, procédure de déploiement propre à la prod ; jamais de push, merge ni action VPS sans accord ; lettres figées intouchables).

## 1. Objectif

Un grossiste, créé par l'admin HayaFlash, publie un catalogue de gros et enregistre à l'avance ses
revendeurs (nom + numéro). Un revendeur rattaché importe des produits dans sa boutique HayaFlash avec
un stock alloué, et les vend en ventes flash comme d'habitude. Le grossiste suit en temps quasi réel
les commandes, livraisons, paiements, marges dues aux revendeurs et commissions dues à HayaFlash.
**HayaFlash ne touche jamais l'argent des ventes.**

## 2. Principes non négociables

1. **App indépendante `distrib`** : `distrib` lit `accounts`, `products`, `orders`, `delivery` ;
   aucune de ces apps n'importe `distrib`. Aucun champ ajouté aux modèles existants.
2. **Circuit de commande inchangé** : un produit importé est un `Product` normal, créé par les
   services existants (`products/services/crud.py`). Ventes flash, commandes, prix promo et stock
   fonctionnent sans modification.
3. **Lien produit ↔ grossiste dans une table de `distrib`** (`ImportedProduct`), jamais dans `products`.
4. **Le suivi ne peut jamais bloquer une commande** : création des lignes de suivi via signal
   `post_save` sur `Order` **différé par `transaction.on_commit`** et protégé par `try/except` + log,
   plus une tâche de réconciliation périodique qui rattrape tout oubli.
5. **Consentement** : un revendeur n'est rattaché qu'après avoir accepté explicitement le partage des
   ventes des produits du grossiste.
6. **Cloisonnement** : le grossiste ne voit que ses revendeurs acceptés et **uniquement les commandes
   portant sur ses produits importés** ; jamais les autres produits ni les autres clients du revendeur.
7. **HayaFlash reste ouvert à tous** : la liste du grossiste sert à rattacher, jamais à bloquer une inscription.
8. Montants en **FCFA entiers** (`DecimalField(max_digits=12, decimal_places=0)`), jamais de centimes.
9. Numéros : normalisés en E.164 avec l'indicatif choisi à la saisie (`core/countries.py`), jamais de pays déduit.

## 3. Rappels sur l'existant (constatés le 22/10/2026)

- `accounts.User` : authentification par `phone` (E.164) ; `SellerProfile` = boutique (`seller_code`).
- `orders.Order` : `status` ∈ pending / confirmed / out_for_delivery / delivered (« Livré et payé ») /
  cancelled ; `OrderItem` porte `product`, `price_snapshot`, `product_name_snapshot`.
  **Claude Code doit vérifier** si une commande peut contenir plusieurs articles et baser le suivi
  sur `OrderItem` (une ligne de suivi par article importé) si c'est le cas.
- `delivery.Delivery` : adresse texte, GPS, statut, `cod_amount` / `cod_collected`.
- Tableau de bord admin : `core/urls.py` → `platform-admin/`.

## 4. Modèles (`distrib`, migrations additives)

**`Distributor`** — le grossiste
- `user` (OneToOne `accounts.User`), `business_name`, `contact_phone`, `orange_money_number`
- `is_active`, `is_suspended`, `suspended_reason`
- Commission : `commission_rate` (%, défaut 6), `commission_min` (défaut 250), `commission_max`
  (défaut 1500), `pilot_until` (date ; avant cette date, commission = 0)
- `credit_ceiling` (plafond d'encours, défaut 10 000), `payout_delay_days` (défaut 7)
- `created_at`, `created_by` (admin)

**`ResellerInvite`** — liste préalable
- `distributor`, `display_name`, `phone` (E.164), `status` : invited / accepted / declined / revoked
- `seller` (FK `SellerProfile`, nul tant que non accepté), `invited_at`, `answered_at`
- Unicité : (`distributor`, `phone`)

**`WholesaleProduct`** — catalogue de gros
- `distributor`, `name`, `description`, `category` (`core.choices.SaleCategory`)
- `wholesale_price`, `min_retail_price` (prix de vente minimum), `stock_total`
- `is_active`, `created_at`, `updated_at`

**`WholesaleProductImage`** — `wholesale_product`, `image`, `order`

**`ImportedProduct`** — lien produit boutique ↔ catalogue
- `wholesale_product`, `invite` (revendeur accepté), `product` (OneToOne `products.Product`)
- `allocated_qty` (quantité actuellement allouée), `created_at`

**`AllocationMovement`** — journal des allocations
- `imported_product`, `quantity_change` (+ allocation, − reprise), `reason`, `created_by`, `created_at`

**`DistribSettlement`** — suivi par article vendu
- `distributor`, `invite`, `order` (FK), `order_item` (FK, nullable selon §3), `imported_product`
- `quantity`, `sale_amount`, `wholesale_amount`, `reseller_margin`, `commission_amount`
- `status` : ordered / in_delivery / delivered_by_shop / paid_confirmed / cancelled
- `paid_confirmed_at`, `paid_confirmed_by`, `created_at`, `updated_at`
- Unicité sur l'article de commande (pas de doublon)

**`DistribPayment`** — règlements des commissions à HayaFlash
- `distributor`, `amount`, `paid_at`, `reference` (Orange Money), `recorded_by` (admin)

**`ResellerPayout`** — versements de marge aux revendeurs
- `distributor`, `invite`, `amount`, `paid_at`, `reference`, `recorded_by` (grossiste)

## 5. Règles de gestion

### 5.1 Comptes grossistes
- Créés **uniquement par l'admin HayaFlash** (pas d'inscription libre en V1).
- Entrée dédiée `/distrib/connexion/` qui réutilise la connexion existante avec `next=/distrib/`.
  **Vérifier** que la redirection d'après connexion ne casse pas pour un utilisateur sans `SellerProfile`.

### 5.2 Rattachement des revendeurs
- Le grossiste saisit nom + indicatif + numéro → `ResellerInvite(invited)`.
- Détection **à la création de boutique et à chaque visite du tableau de bord vendeur** : un bandeau
  ajouté par **un seul `{% include %}`** (balise d'inclusion de `distrib`) dans le template du tableau
  de bord vendeur, affiché si une invitation `invited` correspond au numéro du vendeur connecté.
- Page d'acceptation dans `distrib` : texte de consentement clair (« Le grossiste X verra les
  commandes des produits que tu importes depuis son catalogue, avec l'adresse de livraison des
  clientes, pour pouvoir livrer. ») → Accepter / Refuser.
- Un revendeur peut être rattaché à plusieurs grossistes. Le grossiste peut révoquer (`revoked`) :
  plus de nouvelles importations ; les commandes en cours restent suivies.

### 5.3 Import et stock (allocation)
- Le revendeur choisit un produit du catalogue, fixe son prix de vente (**≥ `min_retail_price`**),
  et le grossiste (ou le revendeur, selon réglage V1 : **le grossiste**) fixe la quantité allouée.
- Création via `products/services/crud.py` : `Product` avec stock = quantité allouée (mouvement
  `INITIAL` existant) ; **copie** des images du catalogue en `ProductMedia` (fichiers copiés, pas partagés).
- **Disponible grossiste** = `stock_total` − somme des `allocated_qty`. Refuser toute allocation au-delà.
- **Reprise** : retire les unités non vendues (au plus `product.stock_available`) via le service
  d'ajustement de stock existant (verrouillage de ligne, mouvement `CORRECTION`), et journalise
  un `AllocationMovement` négatif. **Vérifier** que ce service verrouille la ligne (`select_for_update`).
- Prix sous le minimum (si le revendeur le modifie ensuite dans le formulaire produit) : alerte sur
  les tableaux de bord grossiste et admin ; pas de blocage en V1.

### 5.4 Suivi des commandes
- Signal `post_save` sur `Order` (enregistré dans `distrib/apps.py`) → `transaction.on_commit` →
  pour chaque article dont le produit est un `ImportedProduct` : créer/mettre à jour le `DistribSettlement`.
  Toute erreur est journalisée, **jamais propagée**.
- Tâche Celery beat toutes les 5 minutes (file `default`) : réconciliation (crée les lignes manquantes,
  synchronise les statuts).
- Correspondance des statuts :
  | `Order.status` | `DistribSettlement.status` |
  |---|---|
  | pending, confirmed | ordered |
  | out_for_delivery | in_delivery |
  | delivered | delivered_by_shop |
  | cancelled | cancelled |
- **`paid_confirmed` n'est posé que par le grossiste** (bouton « Paiement reçu »), possible dès
  `ordered` (paiement anticipé) mais jamais si `cancelled`. Une fois confirmé, la synchronisation
  ne fait plus redescendre le statut.
- Montants calculés à la création : `sale_amount` = prix × quantité (snapshot de commande),
  `wholesale_amount` = prix de gros × quantité, `reseller_margin` = différence.

### 5.5 Commission HayaFlash et encours
- Calculée **au passage à `paid_confirmed`** : 0 si `pilot_until` non dépassé ; sinon
  `clamp(sale_amount × rate, commission_min, commission_max)`, arrondi au FCFA.
- **Encours** = somme des commissions confirmées − somme des `DistribPayment`.
- Encours > `credit_ceiling` : alerte rouge sur les tableaux de bord grossiste et admin.
  Bouton admin « Suspendre » : bloque nouvelles importations et allocations ; action admin
  « Masquer les produits du grossiste » (met `is_active=False` sur les produits importés en
  mémorisant l'état précédent, réversible). Suspension automatique = V2.

### 5.6 Marges des revendeurs
- **Dû au revendeur** = marges confirmées − `ResellerPayout`.
- Indicateur de retard : marge confirmée depuis plus de `payout_delay_days` sans versement → alerte
  chez le grossiste et l'admin.
- Le grossiste enregistre chaque versement (montant, référence Orange Money). Le revendeur voit
  « Mes gains » : confirmé, versé, restant dû.

## 6. Écrans

**Grossiste (`/distrib/`)** — mobile d'abord, design soigné, rafraîchissement HTMX toutes les 30 s
- Accueil : commandes du jour, en livraison, à confirmer, CA du mois, marges dues, encours HayaFlash.
- Commandes : filtres par statut / revendeur / période ; détail avec adresse de livraison ;
  bouton « Paiement reçu ».
- Revendeurs : invitations, statuts, ventes, stock alloué, marges dues, versements.
- Catalogue : création / modification, images, prix de gros, prix minimum, stock total.
- Stock : par produit, total / alloué / vendu / disponible ; allouer, reprendre.
- Relevés : par revendeur et par période ; règlements à HayaFlash.

**Revendeur** — bandeau d'invitation ; page « Mes grossistes » : catalogue, importation,
allocations, « Mes gains ».

**Admin HayaFlash (`/distrib/pilotage/`, réservé au staff)** — grossistes, encours, commissions,
retards de versement, alertes de prix minimum ; création de grossiste, enregistrement des règlements,
suspension, masquage. (Le filtre « Distrib » dans `platform-admin/boutiques/` est une phase
facultative P9, car elle touche `core`/`analytics`.)

## 7. Interrupteur et accès

- `DISTRIB_ENABLED` (environnement, **False par défaut**) : coupé → URLs `distrib` en 404, bandeau
  absent, signal et réconciliation inactifs.
- Accès grossiste : utilisateur avec `Distributor` actif. Accès pilotage : `is_staff`.
- Chaque vue vérifie le cloisonnement (tests dédiés).

## 8. Périmètre des fichiers

**Autorisés :** nouvelle app `distrib/` et `templates/distrib/` ; `INSTALLED_APPS`, réglages,
planification beat ; `config/urls.py` (un include) ; **une ligne d'include** dans le template du
tableau de bord vendeur ; `.env.example` ; `CLAUDE.md` (section Distrib).

**Interdits :** `orders/` (y compris `create_order.py`, `stock_release.py`), `payments/`,
tous les `models.py` hors `distrib`, toute migration hors `distrib`, les services de `products`
(**appel autorisé, modification interdite**), `core/` et `analytics/` (sauf phase P9 facultative).

## 9. Phases

- **P0** — Branche `feature/distrib`. Suite de tests verte. Lire les services de `products` et le
  modèle `Order`/`OrderItem` ; consigner les constats (§3) dans le README de l'app.
- **P1** — App, modèles, migrations, admin Django, interrupteur.
- **P2** — Création de grossiste (pilotage), connexion `/distrib/connexion/`.
- **P3** — Invitations, bandeau, page de consentement.
- **P4** — Catalogue de gros + images.
- **P5** — Import, allocation, reprise (services `distrib.services.allocation`).
- **P6** — Signal + réconciliation + `DistribSettlement` + bouton « Paiement reçu ».
- **P7** — Commission, encours, règlements, marges, versements, relevés.
- **P8** — Tableaux de bord grossiste, revendeur, pilotage (HTMX 30 s).
- **P9 (facultative)** — Filtre « Distrib » dans `platform-admin/boutiques/`.
- **P10** — Tests complets, lint, documentation.

## 10. Tests

1. Interrupteur coupé : URLs 404, pas de bandeau, signal inactif, suite existante inchangée.
2. Création d'une commande sur un produit importé **et** sur un produit normal : la commande
   aboutit dans les deux cas ; un suivi n'est créé que pour le produit importé.
3. Exception forcée dans le signal → la commande est créée quand même ; la réconciliation rattrape.
4. Synchronisation de chaque statut ; `paid_confirmed` jamais rétrogradé ; refus si `cancelled`.
5. Seul le grossiste propriétaire peut confirmer un paiement.
6. Cloisonnement : un grossiste ne voit ni les revendeurs, ni les commandes, ni les produits d'un autre ;
   il ne voit pas les produits non importés d'un revendeur.
7. Invitation : bandeau seulement pour le bon numéro (E.164) ; aucun rattachement sans acceptation ;
   révocation bloque les nouvelles importations.
8. Allocation au-delà du disponible refusée ; reprise limitée au stock non vendu ; journal correct.
9. Prix de vente sous le minimum refusé à l'import.
10. Commission : 0 pendant le pilote ; taux, minimum et maximum appliqués ; arrondi FCFA.
11. Encours et marges dues : calculs exacts avec règlements et versements.
12. Toute la suite existante passe (dont commandes, paiements, Publication rapide), lint vert.

## 11. Validation sur le staging (48 h)

Scénario complet avec 1 grossiste de test et 2 revendeurs de test, sur vrais téléphones :
invitation → acceptation → import (1 produit, 5 unités) → vente flash → 3 commandes :
une livrée puis paiement confirmé, une annulée, une payée d'avance (confirmée avant livraison).
Vérifier : statuts identiques chez le grossiste, le revendeur et en pilotage ; stock correct ;
marge, commission et encours exacts ; reprise de stock ; cloisonnement avec un 2e grossiste.

## 12. Mise en production

**Conditions préalables (bloquantes) :** CGU mises à jour (transmission de l'adresse de livraison au
grossiste qui livre) ; contrat grossiste signé (commission, plafond d'encours, délai de versement,
prix minimum, refus de livraison).

1. Moment sans vente flash en cours. Sauvegarde base + médias, tag git `v-avant-distrib`.
2. Déployer avec `DISTRIB_ENABLED=False` ; tests rapides habituels.
3. Activer ; créer le premier grossiste (pilote 2 mois, commission 0).

## 13. Retour arrière

- Couper `DISTRIB_ENABLED` : tout le module disparaît ; les produits importés restent des produits
  normaux des boutiques et continuent de se vendre normalement.
- Au besoin : redéployer l'image du tag précédent. Les tables `distrib` restent en base sans effet.

## 14. Hors périmètre (V2)

Inscription libre des grossistes, suspension et masquage automatiques au-delà du plafond, notifications
WhatsApp/SMS/e-mail, sous-domaine distrib.hayaflash.com, stock commun réservé à la commande,
prépaiement de la commission, blocage du prix minimum dans le formulaire produit, taux par catégorie
et dégressifs.
