# SPEC 03 — Module Distrib V1 (grossistes / revendeurs)

Statut : prêt pour Claude Code — **avec l'Avenant A (§15, 23/10/2026), qui prévaut en cas de contradiction**. Priorité 3 (voir `docs/ROADMAP_V2_V3.md`, section 3).
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
- `credit_ceiling` (plafond d'encours, défaut 10 000), `payout_delay_days` (défaut **3**, réglable par grossiste)
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
- `distributor`, `invite`, `amount`, `paid_at`, `reference`, `recorded_by` (grossiste) — **montant calculé par
  le relevé, jamais saisi ; un relevé a au plus deux déclarations (`attempt` 1 et 2)** (voir §15.4, §15.9)

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
  | cancelled | cancelled (voir règles ci-dessous si la ligne est déjà `paid_confirmed`) |
- **[Remplacé par §15.1–15.3]** ~~`paid_confirmed` n'est posé que par le grossiste~~ (bouton « Paiement reçu »), possible dès
  `ordered` (paiement anticipé) mais jamais si `cancelled`. Une fois confirmé, la synchronisation
  ne fait plus redescendre le statut.
- **Règles de synchro (Avenant A, 24/10/2026)** : la synchro ne remplace jamais `not_delivered` ni
  `paid_confirmed` ; elle horodate `confirmed_at` à la première observation d'un statut `confirmed` ou
  au-delà (§15.1) ; sur `Order.status = cancelled`, une ligne `paid_confirmed` de source `auto` sans
  versement est passée en `cancelled` avec recalcul, toute autre ligne `paid_confirmed` reçoit seulement
  `conflict_flag` + signal pilotage (§15.1). Une ligne `not_delivered` n'est pas touchée.
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
- **[Remplacé par §15.4]** ~~Le grossiste enregistre chaque versement (montant libre)~~ : il règle le
  relevé hebdomadaire calculé (« Payé » + référence Orange Money). Le revendeur voit « Mes gains » :
  confirmé, versé, restant dû.

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
11. Encours et marges dues : calculs exacts avec règlements et relevés réglés (`declared`/`accepted` = réglés, `contested` = reste dû).
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

Inscription libre des grossistes, masquage automatique au-delà du plafond (le blocage léger des allocations passe en V1, §15.6), notifications
WhatsApp/SMS/e-mail, sous-domaine distrib.hayaflash.com, stock commun réservé à la commande,
prépaiement de la commission, blocage du prix minimum dans le formulaire produit, taux par catégorie
et dégressifs.

---

## 15. Avenant A — Confiance et contrôle (23/10/2026)

**Prévaut sur §4 à §12 en cas de contradiction.** Objectif : ne plus faire dépendre la marge du
revendeur d'un clic du grossiste, qui est la partie qui doit cette marge. Principe directeur :
**le silence produit toujours le résultat juste** — aucune partie n'a d'action à faire quand tout va
bien ; seule l'exception demande un geste, motivé et tracé. Aucun litige ouvert, aucun arbitrage
au cas par cas : des signaux vers le pilotage HayaFlash.

Rappel métier : la cliente paie toujours à la livraison, contre le produit. **Livré = payé.**

### 15.1 Présomption de livraison (remplace la confirmation exclusive par le grossiste)

- Toute ligne `DistribSettlement` non annulée passe **automatiquement à `paid_confirmed`**
  `auto_confirm_hours` après le **passage de la commande à `confirmed`** (défaut **72 h**, réglable par
  grossiste dans `Distributor`), sauf si le grossiste a déclaré une non-livraison (§15.2) avant ce délai.
  **Décision du 24/10/2026** : le délai ne part pas de la création de la commande (une commande
  `pending` n'est pas encore acceptée par la revendeuse et peut expirer à 48 h : `orders/services/expiration.py`).
- `confirmed_at` est **horodaté par `distrib`** à la première observation d'un statut `confirmed`,
  `out_for_delivery` ou `delivered` (signal ou réconciliation §5.4) ; `auto_confirm_at = confirmed_at +
  auto_confirm_hours`. `distrib` ne lit pas d'horodatage dans `orders/` : la précision est celle de la
  synchro (signal immédiat, réconciliation ≤ 5 min). Une ligne dont la commande reste `pending` n'a ni
  `confirmed_at` ni échéance, et n'est jamais auto-confirmée.
- Le grossiste peut toujours confirmer plus tôt (bouton « Livré et payé », ex-« Paiement reçu »).
- Tâche Celery beat (toutes les 15 min, file `default`) : `distrib.tasks.auto_confirm_settlements`.
  Idempotente, `select_for_update`, erreurs journalisées jamais propagées.
- Nouveau champ `confirmation_source` : `distributor` / `customer` / `auto`.
- Une fois `paid_confirmed`, **plus aucune rétrogradation** (ni par la synchro, ni par le grossiste),
  **sauf l'unique exception « présomption renversée » ci-dessous**. Toute autre correction est **staff**,
  dans le pilotage, journalisée (`DistribCorrection` : ligne, ancien/nouveau statut, motif, auteur, date).
- **Commande annulée après `paid_confirmed`** (annulation par la vendeuse avant la livraison, ou autre
  circuit existant ; `distrib` n'annule jamais), règle fixée le 24/10/2026 :
  1. `confirmation_source = auto` **et** ligne non rattachée à un `ResellerPayout` : la synchro passe la
     ligne en `cancelled` et **recalcule** : marge et commission ramenées à 0, `commission_billable` faux,
     encours et marges dues mis à jour. La présomption est renversée par le fait. Journalisé dans
     `DistribCorrection` (auteur = système, motif « commande annulée après confirmation automatique »).
  2. `confirmation_source = distributor` ou `customer`, **ou** ligne déjà incluse dans un `ResellerPayout`
     (quelle que soit la source) : **aucune rétrogradation**, `conflict_flag` posé + signal au pilotage ;
     correction éventuelle par le staff (`DistribCorrection`).
  Le rattachement à un versement se matérialise par `DistribSettlement.payout` (FK nullable, §15.9),
  posé sur toutes les lignes du relevé quand le grossiste clique « Payé » (§15.4) ; la règle 1 ne
  s'applique que tant que `payout` est nul (y compris pour une ligne d'un relevé clos mais non payé : le
  relevé est alors recalculé).
- Compte à rebours visible par les trois parties : « Confirmée automatiquement dans 41 h », affiché
  seulement à partir de `confirmed_at` (« Démarre à la confirmation » tant que la commande est `pending`).

### 15.2 Déclaration de non-livraison (seule action du grossiste en cas d'échec)

**Décision du 24/10/2026 (constats P0) : R1, sans annulation.** Le circuit d'annulation de la
vendeuse n'est pas utilisable par `distrib` (réservé à la boutique propriétaire, refusé dès la mise en
livraison : `delivery/services/delivery.py:276-301`). `distrib` **ne touche ni `Order` ni le stock**.

- Bouton « Pas livré » sur la ligne, **avant** la confirmation automatique, avec un motif obligatoire
  en un tap : `refused` (cliente a refusé), `absent` (injoignable / absente), `cancelled` (annulée
  par la cliente), `other` (texte court obligatoire).
- Nouveau statut final `not_delivered` (+ `not_delivered_reason`, `not_delivered_note`, `declared_by`,
  `declared_at`). Écrit **uniquement** dans `DistribSettlement`. La synchronisation §5.4 ne l'écrase jamais.
- **Aucune remise en stock automatique** : ni appel à `release_order_stock`, ni à `adjust_stock`, ni à
  un service d'annulation, ni écriture de `Order.status`. Raison : risque de double libération si la
  commande est annulée plus tard par le circuit normal (expiration, vendeuse).
- Le grossiste peut **réaffecter du stock volontairement** via l'allocation (§5.3) ; c'est une action
  distincte, journalisée dans `AllocationMovement`, jamais déclenchée par « Pas livré ».
- Commande à plusieurs articles dont un seul importé : la déclaration porte sur la ligne
  (`OrderItem`) concernée uniquement ; aucune action sur la commande. Cas ambigu = `other` + signal pilotage.
- Interactions avec l'existant (constats P0, voir `distrib/README.md` § « Interactions ») : l'expiration
  (`orders/services/expiration.py`) n'agit que sur les commandes `pending` > 48 h ; `unhonored.py` ne
  réagit qu'aux échecs de livraison posés par la vendeuse. Aucun des deux ne lit `distrib`.
- Contrôle : une fausse déclaration ne se voit plus dans le stock mais dans l'indice §15.5 (taux de
  `not_delivered`, signaux `conflict`) et dans le pilotage ; sanction = échange privé, jamais automatique.
- Hors périmètre V1 : annulation par tiers autorisé (service dédié dans `orders/`/`delivery/`),
  éventuellement V1.1 sur décision du mainteneur.

### 15.3 Confirmation par la cliente (facultative, sans aucune action du revendeur)

**Règle (23/10/2026) : aucune action demandée au revendeur, aucun échange WhatsApp revendeur ↔
cliente.** La confirmation cliente est un bonus ; le verrou reste la présomption de 72 h (§15.1).

Pour chaque ligne, `distrib` génère :
- `receipt_token` : jeton long non devinable (`secrets.token_urlsafe`, 22+ caractères) ;
- `receipt_code` : **code de commande à 4 chiffres**, affiché **uniquement à la cliente**
  (jamais dans l'espace revendeur ni dans l'espace grossiste).

**Accès 1 — automatique, depuis le même téléphone**
- Sur l'écran de confirmation de commande (`templates/orders/client_order.html`), par **un seul
  `{% include %}`** conditionnel (`DISTRIB_ENABLED` + au moins un produit importé) : petit lien
  discret « Confirmer la réception plus tard » et rappel du code à 4 chiffres.
- Le navigateur garde les jetons des commandes Distrib en cours (cookie dédié `hf_receipts`,
  HttpOnly, SameSite=Lax, 30 jours, jetons uniquement, aucune donnée personnelle).
- Quand la cliente revient sur une page publique HayaFlash depuis ce téléphone, un **bandeau
  discret** apparaît : « Tu as reçu ta commande ? Confirmer » (un seul bandeau, fermable, n'apparaît
  plus une fois la ligne confirmée, annulée ou `paid_confirmed`).

**Accès 2 — secours, lien discret « Confirmer un paiement »**
- Lien discret dans le pied des pages publiques, ajouté par **un seul `{% include %}`** dans le
  gabarit commun public, affiché seulement si `DISTRIB_ENABLED`.
- Page `/distrib/confirmer/` : numéro de téléphone (indicatif choisi + numéro, E.164) + code à
  4 chiffres → si une ligne ouverte correspond : bouton « J'ai reçu ma commande ».
- Anti-abus : limite de débit par IP et par numéro (5 essais / heure), réponse identique que le
  couple existe ou non, code invalidé après confirmation.

**Après « J'ai reçu »** : champ facultatif « Référence Orange Money (facultatif) » (chiffres/lettres,
sans date, longueur bornée) puis « Envoyer » — ignorable.

**Effets**
- ligne non encore confirmée → `paid_confirmed` immédiat, `confirmation_source=customer` ;
- ligne déjà `not_delivered` → **aucun changement de statut**, signal `conflict` au pilotage
  uniquement ;
- `customer_confirmed_at` et `customer_om_reference` visibles des trois parties dans la partie
  paiements de la ligne, avec la date de livraison.

**P0 — vérifier** que les deux includes sont possibles proprement (un seul `{% include %}` chacun,
aucune autre modification de template ou de vue existante). Sinon : s'arrêter et consigner ;
l'accès 2 seul (page `/distrib/confirmer/` sans lien en pied de page) reste le repli.

### 15.4 Relevé hebdomadaire et versement des marges (silence = accord)

**Décision du 24/10/2026 (P7) : plus aucun montant libre.** Le grossiste ne saisit jamais un montant :
il règle un **relevé** calculé par le système, en une fois.

**Relevé (`DistribStatement`)**
- Un relevé par revendeur (`invite`) et par semaine : du lundi 00:00 au **dimanche 23:59:59**
  (fuseau `Africa/Bamako`, `TIME_ZONE` du projet).
- Tâche Celery beat hebdomadaire (lundi 00:05, file `default`) `distrib.tasks.close_weekly_statements` :
  idempotente (unicité `invite` + `period_start`), `select_for_update`, erreurs journalisées jamais
  propagées. Elle rattache au relevé **toutes les lignes `paid_confirmed` à la clôture, non encore
  couvertes par un relevé** (`statement` nul), dont `paid_confirmed_at` ≤ dimanche 23:59:59.
  `amount` = somme des `reseller_margin` de ces lignes, **calculée**, jamais saisie.
- Les lignes confirmées **après la clôture** (ou rattrapées en retard) vont au relevé **suivant**.
  Un relevé à 0 FCFA n'est pas créé.
- Statuts : `to_pay` (clos, à régler) → `paid` (versement déclaré, ci-dessous) → `accepted`, ou
  `contested` (1re contestation : une redéclaration est permise) → `paid` (redéclaré) → `accepted` ou
  `escalated` (2e contestation : staff seul). Tant qu'un relevé est `to_pay`, il est **recalculé** si une
  ligne est retirée par le renversement automatique (§15.1, règle 1) ; dès `paid`, il est figé.
  `contest_count` (0, 1 ou 2) compte les contestations du cycle en cours.
- **Pas de paiement partiel en V1** : le seul geste possible est de régler le relevé entier.

**Versement (`ResellerPayout`)**
- Le grossiste ouvre le relevé et clique **« Payé »** en saisissant la **référence Orange Money**
  (obligatoire, nettoyée, bornée). Cela crée un `ResellerPayout` (une ligne par déclaration, `attempt` = 1 ou 2, unicité `statement` + `attempt`) avec
  `amount` = montant du relevé (recopié, non modifiable) et renseigne `payout` sur **chacune des lignes du
  relevé** ; le rattachement couvre donc exactement les lignes du relevé.
- Champs : `status` (`declared` / `accepted` / `contested`), `attempt`, `om_reference`, `contest_deadline`
  (= déclaration + 72 h), `contest_reason`, `accepted_source` (`reseller` / `auto` / `staff`).
- Le revendeur voit le relevé (ses lignes, ses marges) puis, après « Payé », « Versement reçu ? » avec
  deux boutons : « Oui » (facultatif) et **« Pas reçu »** (motif court).
- Sans réponse avant `contest_deadline` → `accepted` automatiquement (tâche beat).
- **Contestation portée sur le relevé** : « Pas reçu » → le versement passe `contested`, le relevé
  `contested` (`contest_count` = 1), le montant **reste dû** dans tous les calculs (marges dues, plafond
  §15.6, retards) et un signal part au pilotage. Pas de procédure de litige dans l'outil.
- **Une seule redéclaration par le grossiste** (décision du 24/10/2026) : sur un relevé `contested`
  (`contest_count` = 1), il clique de nouveau « Payé » avec une **nouvelle** référence OM (différente de la
  précédente, obligatoire) ; cela crée le versement `attempt` 2 (même montant, non modifiable), repointe
  `payout` sur les lignes, repart pour un **nouveau délai de 72 h** (`contest_deadline`), relevé `paid`.
  Le versement `attempt` 1 est conservé en historique (`contested`).
- **Seconde contestation sur le même relevé** → relevé `escalated` (`contest_count` = 2), signal pilotage
  prioritaire, montant toujours dû. Le grossiste ne peut plus rien faire ; **seul le staff**, dans le
  pilotage, peut clore (relevé et versement `accepted`, `accepted_source` = `staff`) ou rouvrir le relevé
  (`to_pay`, lignes détachées du versement, `contest_count` remis à 0 : le grossiste peut alors régler à
  nouveau). Chaque action staff est journalisée (auteur, date, motif).
- **Dû au revendeur** = marges des lignes `paid_confirmed` dont `payout` est nul ou dont le versement est
  `contested` (les versements `declared` et `accepted` sont comptés comme réglés).
- Rythme : relevé chaque semaine ; alerte de retard si un relevé reste `to_pay` plus de
  `payout_delay_days` (défaut **3**, réglable par grossiste ; décision du 24/10/2026) après sa clôture
  (grossiste, revendeur concerné, pilotage). Les relevés `contested` et `escalated` restent dus et signalés.

### 15.5 Indice de fiabilité (pilotage HayaFlash uniquement en V1)

Calculé sur 30 jours glissants, par grossiste :
- taux de `not_delivered` (et répartition par motif) ;
- nombre de signaux `conflict` (cliente a confirmé une ligne déclarée non livrée) ;
- nombre de versements `contested` et retards de versement ;
- part des confirmations `customer` / `distributor` / `auto`.
Seuils d'alerte réglables (défauts : `not_delivered` > 20 %, ≥ 1 `conflict`, ≥ 1 `contested`).
Aucune sanction automatique : l'admin échange en privé avec le grossiste. Affichage aux revendeurs = V2.

### 15.6 Plafonds et coupure progressive (remplace la suspension uniquement manuelle)

Deux plafonds distincts, réglables par grossiste :
- `reseller_credit_ceiling` (défaut **10 000 FCFA**) : marges dues **par revendeur** (confirmées −
  versements `accepted`/`declared`, les `contested` restant dus) ;
- `credit_ceiling` existant (défaut 10 000 FCFA) : encours de commission dû à HayaFlash.

Pour chacun :
- **≥ 80 %** : alerte orange chez le grossiste (et le revendeur concerné) et au pilotage ;
- **> 100 %** : **blocage automatique des nouvelles allocations et importations** (le revendeur
  concerné pour le plafond marge, tout le grossiste pour le plafond commission). Message clair :
  « Règle les marges dues pour débloquer ».
- **Jamais bloqués** : les commandes en cours, les ventes flash déjà ouvertes, la livraison.
- Déblocage automatique dès que l'encours repasse sous le plafond.
- Masquage des produits : reste une action admin manuelle (V2 pour l'automatique).

### 15.7 Commission HayaFlash (précise §5.5)

- Taux **5 à 6 %** négocié par grossiste (`commission_rate`, défaut 6), **plafond 1 500 FCFA par
  commande** (`commission_max`), minimum `commission_min` conservé (défaut 250, peut être mis à 0).
- **Calculée et affichée dès le 1er mois**, mais **facturable seulement après `pilot_until`**
  (≈ fin du mois 1) : nouveau champ `commission_billable` (bool) sur la ligne ; l'encours ne compte
  que les lignes facturables. Libellé côté grossiste : « Commission offerte (période d'essai) ».
- Calculée au passage à `paid_confirmed`, quelle que soit la source (§15.1).

### 15.8 Ce que chaque partie doit faire (contrôle d'ergonomie)

| Partie | Obligatoire | Facultatif |
|---|---|---|
| Grossiste | affecter le stock ; livrer ; « Pas livré » en cas d'échec ; déclarer le versement hebdo avec réf. OM | « Livré et payé » plus tôt |
| Revendeur | faire ses lives | « Pas reçu » (versements) |
| Cliente | rien | « J'ai reçu » ; réf. OM |

Tout écran ajouté doit tenir sur un téléphone, en gros boutons, sans saisie libre sauf motif `other`.

### 15.9 Modèles — ajouts (migrations additives, app `distrib` uniquement)

- `Distributor` : `auto_confirm_hours` (72), `reseller_credit_ceiling` (10 000), seuils d'alerte §15.5.
- `DistribSettlement` : statut `not_delivered`, `not_delivered_reason`, `not_delivered_note`,
  `declared_by`, `declared_at`, `confirmation_source`, `confirmed_at`, `auto_confirm_at`, `statement` (FK nullable `DistribStatement`), `payout` (FK nullable `ResellerPayout`), `receipt_token` (unique), `receipt_code` (4 chiffres),
  `customer_confirmed_at`, `customer_om_reference`, `commission_billable`, `conflict_flag`.
- `ResellerPayout` : champs §15.4 + `statement` (FK `DistribStatement`) et `attempt` (1 ou 2 ; unicité
  `statement` + `attempt`) ; `amount` recopié du relevé.
- Nouveau `DistribStatement` : `distributor`, `invite`, `period_start`, `period_end`, `amount`, `line_count`,
  `status` (`to_pay` / `paid` / `accepted` / `contested` / `escalated`), `contest_count`, `closed_at` ;
  unicité (`invite`, `period_start`).
- `Distributor.payout_delay_days` : défaut 3 (réglable).
- Nouveau `DistribCorrection` (§15.1) ; `author` nullable (null = système, renversement automatique).

### 15.10 Phases — ajustements

- **P0** (fait le 24/10 : constats dans `distrib/README.md`, §15.2 = R1) : + vérifier le circuit d'annulation appelable (§15.2) et la possibilité d'include dans
  `client_order.html` (§15.3) ; consigner les constats avant tout code.
- **P6** : + présomption 72 h, « Pas livré », appel d'annulation, `DistribCorrection`.
- **P6b (nouvelle)** : confirmation cliente — code 4 chiffres, cookie et bandeau discret, page `/distrib/confirmer/`, deux includes.
- **P7** : + relevé hebdomadaire par revendeur (`DistribStatement`, tâche de clôture du lundi), « Payé » + référence OM, versements `declared/accepted/contested`, plafonds et coupure progressive,
  commission facturable.
- **P8** : + compte à rebours, boutons §15.8, indice de fiabilité au pilotage.

### 15.11 Tests — ajouts

13. Sans action, une ligne passe `paid_confirmed` (`auto`) `auto_confirm_hours` après `confirmed_at`
    (horodaté par `distrib` à la synchro), jamais avant ; le délai ne part pas de la création : commande
    restée `pending` = jamais auto-confirmée ; `confirmed_at` posé une seule fois (pas de remise à zéro
    aux synchros suivantes) ; compte à rebours absent tant que `pending`.
14. « Pas livré » avant le délai → `not_delivered` dans `distrib` seulement ; `Order`, `OrderItem`, stock et
    mouvements de stock strictement inchangés ; refusé après `paid_confirmed`.
15. Une ligne `paid_confirmed` n'est jamais rétrogradée (synchro, grossiste) ; correction staff journalisée.
    Commande annulée après confirmation : (a) source `auto`, sans versement : ligne `cancelled`, marge et
    commission à 0, encours et marges dues recalculés, `DistribCorrection` système ; (b) source
    `distributor` ou `customer` : statut inchangé, `conflict_flag` + signal pilotage ; (c) source `auto`
    mais ligne rattachée à un `ResellerPayout` : inchangée, `conflict_flag` + signal ; (d) ligne
    `not_delivered` jamais touchée ; rejouer la synchro n'a aucun effet supplémentaire.
16. Confirmation cliente : bandeau présent seulement avec le cookie et une ligne ouverte ; page
    `/distrib/confirmer/` avec numéro + code correct confirme ; mauvais code → réponse neutre ;
    limite de débit ; code jamais visible côté revendeur/grossiste ; sur ligne `not_delivered` →
    `conflict_flag` sans changement de statut ; double confirmation sans effet ; `DISTRIB_ENABLED`
    coupé → ni lien, ni bandeau, ni page.
17. Référence OM facultative, nettoyée, bornée ; visible des trois parties.
18. Versement non contesté → `accepted` après 72 h ; « Pas reçu » → versement et relevé `contested`
    (`contest_count` = 1), montant reste dû. Redéclaration : une seule, avec une référence OM différente
    et obligatoire, même montant, nouveau délai de 72 h, `attempt` 2, lignes repointées, ancien versement
    conservé ; une 2e redéclaration par le grossiste est refusée. Seconde contestation → relevé `escalated`,
    montant toujours dû, grossiste sans action possible ; seul le staff clôt (`accepted_source` = `staff`)
    ou rouvre (`to_pay`, lignes détachées, `contest_count` = 0), action journalisée.
19. Plafonds : alerte à 80 % ; blocage allocations/importations au-delà ; commandes en cours et
    ventes ouvertes jamais bloquées ; déblocage automatique.
20. Commission calculée pendant l'essai mais non facturable ; facturable après `pilot_until` ;
    plafond 1 500 FCFA par commande.
21. Indice de fiabilité : calculs exacts sur jeux de données de test.
22. Relevés : clôture du lundi inclut exactement les lignes `paid_confirmed` jusqu'au dimanche 23:59:59
    non couvertes ; une ligne confirmée à 00:00:01 le lundi va au relevé suivant ; montant = somme des
    marges (jamais saisi, aucun champ montant dans le formulaire « Payé ») ; relevé à 0 non créé ;
    clôture rejouée = aucun doublon (unicité `invite`+`période`).
23. « Payé » : référence OM obligatoire ; le `ResellerPayout` (`attempt` 1) couvre exactement les lignes du relevé
    (`payout` renseigné sur chacune, aucune autre) ; paiement partiel impossible ; double clic sans
    effet ; seul le grossiste propriétaire peut régler ; relevé figé après `paid`.
24. Renversement automatique (§15.1) sur une ligne d'un relevé `to_pay` : ligne retirée, relevé recalculé ;
    sur une ligne d'un relevé `paid` : aucun changement, `conflict_flag` + signal.
25. Plafond marge par revendeur et retards : un relevé `contested` ou `escalated` reste dû ; un relevé
    `to_pay` au-delà de `payout_delay_days` (défaut 3, réglable par grossiste, compté depuis la clôture)
    déclenche l'alerte, pas avant.

### 15.12 Staging — scénario complété (§11)

Ajouter : une commande laissée sans action (vérifier la confirmation auto en réglant
`auto_confirm_hours` à 1 h pour le test) ; un « Pas livré » (commande et stock inchangés ; réaffectation volontaire via l'allocation) ;
une confirmation cliente par le bandeau (même téléphone) et une par la page de secours (autre téléphone, numéro + code) avec référence OM ; une confirmation cliente sur une ligne déclarée non
livrée (signal `conflict` au pilotage seulement) ; un versement contesté ; dépassement du plafond
marge (blocage puis déblocage).

### 15.13 Contrat grossiste et CGU — clauses à prévoir (conditions bloquantes §12)

- **Présomption de livraison** : sans déclaration « Pas livré » sous 72 h, la commande est réputée
  livrée et payée ; la marge et la commission sont dues.
- Obligation de motif et d'exactitude des déclarations de non-livraison ; HayaFlash peut suspendre
  en cas d'écarts répétés (indice de fiabilité).
- Versement hebdomadaire des marges avec référence Orange Money ; silence du revendeur sous 72 h
  = acceptation ; plafond de marges dues par revendeur et blocage des nouvelles allocations au-delà.
- Commission 5–6 % plafonnée à 1 500 FCFA par commande, offerte pendant la période d'essai.
- CGU clientes : collecte facultative de la référence Orange Money à des fins de preuve de paiement,
  visible par la boutique, le grossiste livreur et HayaFlash.
