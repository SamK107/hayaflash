> **OBSOLÈTE (23/10/2026)** — remplacé par `docs/specs/SPEC_03_DISTRIB_V1.md` (avec Avenant A §15). Ne pas utiliser pour l'implémentation.

# SPEC — HayaFlash Distrib V1 : grossistes et revendeurs (Évolution 3)

> Gouvernance : `GOVERNANCE_EVOLUTIONS.md`. Branche : `feature/distrib`. Effort : ~1 semaine calendaire (dev + tests + staging 48 h). Risque : moyen, maîtrisé par le découplage total du circuit de commande.

## 1. Le modèle économique (rappel des décisions)

- Le **grossiste** fournit un catalogue (photos, prix de gros, prix de vente minimum, stock).
- Des **revendeurs** (boutiques HayaFlash sélectionnées) importent ces produits et lancent leurs ventes flash avec leur compte habituel (gratuit puis payant).
- Le **livreur du grossiste** livre et encaisse sur le mobile money du grossiste. **HayaFlash ne touche jamais l'argent des ventes.**
- Le grossiste reverse la marge au revendeur (prix de vente − prix de gros) dans le délai contractuel.
- Commission HayaFlash : `taux × prix de vente`, bornée par un minimum et un maximum par ligne vendue. Pilote : 0 % pendant 2 mois. Ensuite **encours plafonné**, réglé chaque semaine (pas de prépaiement imposé).

## 2. Principes techniques non négociables

1. **Zéro modification** de `create_order.py`, `stock_release.py`, `orders/models.py`, `delivery/models.py`, `payments/`. Aucun signal sur `Order`.
2. Un produit importé est un **`Product` normal** de la boutique du revendeur : vente flash, prix promo, stock, commande fonctionnent sans changement. Le lien avec le grossiste est porté **uniquement** par les tables `distrib` (aucune colonne ajoutée à `Product`).
3. **Stock alloué par revendeur** : allouer 10 unités = `Product.stock_initial = stock_available = 10`. La survente est impossible grâce au verrou existant de `create_order`.
4. **Synchronisation par tâche Celery périodique** (60 s, idempotente) qui lit les nouvelles lignes de commande portant sur des produits alloués. Délai max d'apparition chez le grossiste : ~1 min.
5. Suivi **par ligne de commande** (`OrderItem`) : une commande peut mélanger produits du grossiste et produits propres du revendeur.

## 3. Modèle de données (app `distrib`, migrations additives)

```text
Wholesaler                    (1 par compte grossiste)
  user            OneToOne User
  business_name, city, momo_number
  status          pending | active | suspended
  commission_rate Decimal (ex. 0.06)   commission_min int (ex. 250)   commission_max int (ex. 1500)
  credit_limit    int FCFA (plafond d'encours, ex. 10000)
  payout_delay_days int (délai de reversement aux revendeurs, ex. 7)
  pilot_until     date null (commission 0 % jusqu'à cette date)
  created_at, updated_at

WholesaleProduct
  wholesaler FK, name, description, category (SaleCategory)
  wholesale_price int, min_retail_price int, stock_total int
  is_active bool, created_at, updated_at
WholesaleProductMedia         (wholesale_product FK, image, position)

ResellerLink                  (rattachement grossiste ↔ boutique)
  wholesaler FK, seller FK SellerProfile
  status invited | active | ended     invited_at, accepted_at, ended_at
  unique (wholesaler, seller)

Allocation                    (1 produit grossiste attribué à 1 boutique)
  wholesale_product FK, seller FK, product OneToOne Product (le produit créé dans la boutique)
  quantity_allocated int, quantity_returned int default 0
  created_at, updated_at

Settlement                    (1 par OrderItem portant sur un produit alloué)
  order_item OneToOne OrderItem, allocation FK
  status ordered | out_for_delivery | delivered_by_shop | paid_confirmed | cancelled
  quantity int, sale_amount int, wholesale_amount int, reseller_margin int, commission_amount int
  shop_delivered_at null, paid_confirmed_at null, paid_confirmed_by FK User null
  created_at, updated_at

ResellerPayout                (reversement du grossiste au revendeur)
  wholesaler FK, seller FK, amount int, period_start, period_end
  momo_reference, paid_at, created_by FK User
  settlements M2M Settlement

CommissionPayment             (règlement du grossiste à HayaFlash, saisi par l'admin)
  wholesaler FK, amount int, momo_reference, paid_at, created_by FK User
```

**Calculs** (service pur `distrib/services/money.py`, testé sans base) :
- `wholesale_amount = wholesale_price × quantity` ; `reseller_margin = sale_amount − wholesale_amount`
- `commission = 0` si `pilot_until ≥ date`, sinon `clamp(round(rate × sale_amount), commission_min, commission_max)`
- `encours = Σ commission (paid_confirmed) − Σ CommissionPayment`
- `reste en stock grossiste = stock_total − Σ (alloué − repris)`

## 4. Cycle de vie d'une ligne (statuts visibles par tous)

| Statut Settlement | Déclencheur | Qui |
|---|---|---|
| `ordered` — Commandée | la tâche de synchro détecte l'OrderItem | automatique |
| `out_for_delivery` — En livraison | Order passe à « En livraison » | automatique (lecture) |
| `delivered_by_shop` — Livrée (boutique) | le revendeur marque la commande livrée dans son flux habituel | automatique (lecture) |
| `paid_confirmed` — **Livrée et payée** | bouton du grossiste « Paiement reçu » (possible dès `ordered` si la cliente a payé d'avance) | **grossiste uniquement** |
| `cancelled` — Annulée | Order annulée | automatique (lecture) |

Seul `paid_confirmed` compte dans la marge due au revendeur et dans la commission HayaFlash. Toute action de confirmation est journalisée (`core` audit log existant).

## 5. Écritures autorisées sur des modèles existants (liste fermée)

1. **Import / allocation** : création d'un `Product` (+ `ProductMedia` copiés) dans la boutique, `stock_initial = stock_available = quantité`, prix ≥ `min_retail_price`, `StockMovement` type `initial`.
2. **Ajout d'unités** à une allocation : `select_for_update` sur le `Product`, incrément du stock, `StockMovement` `correction`.
3. **Reprise d'allocation** (« Reprendre les invendus ») : `select_for_update`, décrément limité au stock disponible, `quantity_returned += n`, `StockMovement` `correction`.
4. **Suspension** d'un grossiste : `Product.is_active = False` pour ses produits alloués (réversible).

Ces 4 services vivent dans `distrib/services/stock.py`, sont transactionnels et couverts par des tests de concurrence (2 opérations simultanées).

## 6. Rôles, accès, URLs

| Espace | URL | Accès |
|---|---|---|
| Tableau de bord grossiste | `/distrib/` | décorateur `wholesaler_required` (Wholesaler actif) |
| Espace revendeur | `/seller/distrib/` | vendeur avec flag `distrib` actif |
| Pilotage HayaFlash | `/platform-admin/distrib/` | staff uniquement |

- **Compte grossiste V1** : créé par Alex depuis l'admin (sélection sur le volet) + lien d'activation pour définir son mot de passe. Connexion téléphone + mot de passe, comme les vendeurs. Pas d'inscription libre en V1.
- Un grossiste ne voit **que** ses produits, ses revendeurs et leurs lignes. Il voit nom, téléphone et adresse de livraison de la cliente **uniquement** pour les lignes qui le concernent (prérequis : CGU mises à jour).
- Tous les écrans respectent l'isolation : tests de permissions obligatoires (grossiste A ne voit rien de B).

## 7. Écrans

**Grossiste — `/distrib/`** (rafraîchissement HTMX toutes les 30 s) :
- Bandeau KPI : commandes du jour · en livraison · **à confirmer (paiement)** · CA livré-payé du mois · marges dues aux revendeurs · encours HayaFlash / plafond (jauge).
- Onglet **Commandes** : tableau filtrable (statut, revendeur, date) ; bouton « Paiement reçu » par ligne ou en lot.
- Onglet **Catalogue** : produits, photos, prix de gros, prix minimum, stock total / alloué / vendu / reste.
- Onglet **Revendeurs** : liste, invitations, allocations par produit, boutons Allouer / Reprendre, marge due, dernier reversement.
- Onglet **Reversements** : relevé par revendeur et par période (généré automatiquement), saisie « Payé le … référence Orange Money » → visible du revendeur.

**Revendeur — `/seller/distrib/`** : invitations à accepter, catalogue du grossiste, bouton « Importer dans ma boutique » (choix du prix ≥ minimum), mes allocations, mes marges (dues / reçues).

**Admin — `/platform-admin/distrib/`** : grossistes, statut, commissions du mois, encours vs plafond (alerte rouge si dépassé), saisie des `CommissionPayment`, bouton Suspendre / Réactiver.

## 8. Charte graphique « HayaFlash Distrib »

**Pratique retenue** : même système de design, identité de sous-marque. C'est ce que font les espaces professionnels des grandes plateformes (espaces vendeurs ou partenaires distincts de l'appli client) : l'utilisateur sait immédiatement dans quel espace il est, sans réapprendre l'interface. Une charte totalement différente coûterait du temps de dev et casserait la cohérence.

- **Conservé** : configuration Tailwind, typographies, icônes, composants (boutons, cartes, formulaires, toasts), logo HayaFlash.
- **Distinct** :
  - couleur d'accent propre à Distrib, à fort contraste avec la couleur primaire HayaFlash (lire `tailwind.config` et choisir une teinte « professionnelle » complémentaire, ex. bleu nuit `#1E3A8A` si la primaire est chaude) ; définie comme token `distrib` dans la config, pas en dur ;
  - badge **« DISTRIB »** à côté du logo dans l'en-tête ;
  - fond légèrement teinté de l'en-tête et de la barre latérale ;
  - mise en page **orientée tableaux**, plus dense (desktop d'abord, mais responsive : tableaux → cartes sous 640 px).
- **Couleurs de statut universelles** (identiques partout) : gris Commandée · bleu En livraison · ambre Livrée (boutique) · vert Livrée et payée · rouge Annulée. Toujours accompagnées d'un libellé (jamais la couleur seule).

## 9. Phases de développement (une PR par phase)

| Phase | Contenu | Critère de fin |
|---|---|---|
| D0 | `core.FeatureFlag` (si absent), app `distrib`, modèles, admin Django | migrations additives validées par la CI |
| D1 | Service `money.py` + tests unitaires | 100 % des cas de calcul couverts |
| D2 | Comptes grossistes (création admin, activation, décorateur) + catalogue grossiste | tests de permissions |
| D3 | Rattachement revendeurs + import / allocation / ajout / reprise (`stock.py`) | tests de concurrence verts |
| D4 | Tâche de synchro `sync_settlements` (beat 60 s, idempotente) + statuts | rejouer 2 fois = aucun doublon |
| D5 | Tableau de bord grossiste + bouton « Paiement reçu » | recette sur téléphone et PC |
| D6 | Espace revendeur + relevés + `ResellerPayout` | relevé = somme des lignes confirmées |
| D7 | Pilotage admin + encours + suspension | alerte encours > plafond |
| D8 | E2E Playwright (parcours complet), recette staging, pilote 1 grossiste | checklist §10 |

## 10. Recette staging (checklist)

- [ ] Grossiste test créé, catalogue de 5 produits avec photos
- [ ] 2 revendeurs test rattachés, import avec prix < minimum refusé
- [ ] Vente flash d'un revendeur, 3 commandes clientes dont une mixte (produit propre + produit grossiste)
- [ ] Lignes visibles chez le grossiste en ≤ 1 min, seulement les siennes
- [ ] Livraison marquée par la boutique → « Livrée (boutique) » ; « Paiement reçu » par le grossiste → « Livrée et payée » partout
- [ ] Commande annulée → stock rendu par le flux existant, ligne « Annulée »
- [ ] Reprise des invendus : stock boutique et reste grossiste corrects
- [ ] Commission : 0 pendant le pilote ; après, min / max respectés
- [ ] Flag `distrib` éteint : aucune différence visible pour les vendeurs non concernés
- [ ] Suite de tests complète verte, zones protégées intactes (CI)

## 11. Prérequis hors code (avant activation en prod)

- [ ] CGU : transmission de l'adresse de livraison au grossiste qui livre
- [ ] Contrat grossiste : commission, min / max, plafond d'encours, délai de reversement, prix minimum, refus de livraison, authenticité des produits
- [ ] Lettre revendeur : marge, délai de reversement, rôle de HayaFlash (aucune détention de fonds)

## 12. Reporté en V2

Inscription libre des grossistes · suspension automatique au-delà du plafond · notifications WhatsApp / SMS · sous-domaine `distrib.hayaflash.com` · prépaiement facultatif · stock commun entre revendeurs · blocage du prix minimum dans le formulaire produit existant.
