# SPEC — Prix barré + « Prix promo » (Évolution 1)

> Gouvernance : `GOVERNANCE_EVOLUTIONS.md`. Branche : `feature/prix-barre`. Effort : ~1 jour. Risque : très faible (affichage uniquement).

## Contexte (état du code au 22/10/2026)

- `Product.price` = prix catalogue. `FlashSaleProduct.promo_price` = prix pour une vente (facultatif).
- `FlashSaleProduct.effective_price` = promo si définie, sinon catalogue.
- `orders/services/create_order.py` facture `link.effective_price` → **le prix facturé est déjà correct, on n'y touche pas.**
- La vitrine Marché (`_calendar_list.html`) affiche déjà prix barré + pastille « −X % ».
- `templates/orders/client_order.html` affiche `{{ product.price }}` (ligne ~50) et l'injecte dans le JS (`price:` ligne ~82).

## Phase 0 — Vérification préalable (obligatoire, 15 min)

Localiser la vue qui rend `client_order.html` et déterminer **quelle valeur contient `product.price`** dans ce contexte :
- si c'est déjà le prix effectif (promo appliquée) → OK, continuer ;
- si c'est le prix catalogue → **incohérence en prod** : la cliente voit un prix et est facturée d'un autre. Le signaler immédiatement à Alex (décision écrite avant toute suite), car le total affiché par le JS serait faux.

## Objectif

Sur la page de commande cliente, pendant une vente avec prix promo, afficher :
- le prix catalogue **grisé et barré** ;
- le prix promo en gros, mention **« Prix promo »** ;
- selon le mode choisi par le vendeur : pastille **« −30 % »** ou ligne **« Tu économises 2 500 FCFA »**.

## Règles métier

| Règle | Détail |
|---|---|
| Mode d'affichage | Champ sur la vente : `net` (défaut, comportement actuel), `urgence` (−X %), `economie` (Tu économises X FCFA) |
| Condition d'affichage barré | mode ≠ `net` ET `promo_price` défini ET `promo_price < product.price` |
| Pourcentage | `floor((catalogue − promo) / catalogue × 100)` ; jamais arrondi vers le haut |
| Garde-fou honnêteté | remise > 70 % → pas de prix barré (affichage `net`) + avertissement dans le formulaire vendeur |
| Prix facturé | inchangé : `effective_price` |

## Phase 1 — Modèle (migration additive)

`flash_sales.FlashSale` : ajouter
```python
class PriceDisplayMode(models.TextChoices):
    NET = "net", "Prix seul"
    URGENCE = "urgence", "Prix barré + % de réduction"
    ECONOMIE = "economie", "Prix barré + économie en FCFA"

price_display_mode = models.CharField(
    max_length=10, choices=PriceDisplayMode.choices, default=PriceDisplayMode.NET,
)
```
Contrôle : `sqlmigrate` = un seul `ADD COLUMN ... DEFAULT 'net' NOT NULL`. Les ventes existantes gardent l'affichage actuel.

## Phase 2 — Service pur (testable sans base)

Nouveau fichier `flash_sales/services/price_display.py` :
```python
from dataclasses import dataclass
from decimal import Decimal

MAX_HONEST_DISCOUNT_PCT = 70

@dataclass(frozen=True)
class PriceDisplay:
    price: int                 # prix facturé (FCFA entiers)
    old_price: int | None      # prix barré, None si pas d'affichage barré
    discount_pct: int | None
    savings: int | None
    mode: str

def build_price_display(catalog: Decimal, promo: Decimal | None, mode: str) -> PriceDisplay:
    catalog_i = int(catalog)
    if promo is None:
        return PriceDisplay(catalog_i, None, None, None, "net")
    promo_i = int(promo)
    if mode == "net" or promo_i >= catalog_i or catalog_i <= 0:
        return PriceDisplay(promo_i, None, None, None, "net")
    pct = (catalog_i - promo_i) * 100 // catalog_i
    if pct > MAX_HONEST_DISCOUNT_PCT or pct < 1:
        return PriceDisplay(promo_i, None, None, None, "net")
    return PriceDisplay(promo_i, catalog_i, pct, catalog_i - promo_i, mode)
```

## Phase 3 — Vue + template

1. Dans la vue de `client_order.html` : pour chaque produit affiché, attacher `product.price_display = build_price_display(...)` à partir du `FlashSaleProduct` de la vente. **Ne pas modifier `product.price`** ni la valeur injectée dans le JS.
2. Nouveau partial `templates/orders/partials/_price_block.html` :
   ```django
   {% with pd=product.price_display %}
   {% if pd and pd.old_price %}
     <div class="flex flex-col">
       <span class="text-sm text-gray-400 line-through" aria-label="Ancien prix">{{ pd.old_price|floatformat:"0g" }} FCFA</span>
       <span class="text-2xl font-bold text-primary">{{ pd.price|floatformat:"0g" }} FCFA</span>
       <span class="text-xs font-semibold uppercase tracking-wide">Prix promo</span>
       {% if pd.mode == "urgence" %}<span class="pill">−{{ pd.discount_pct }} %</span>{% endif %}
       {% if pd.mode == "economie" %}<span class="text-sm">Tu économises {{ pd.savings|floatformat:"0g" }} FCFA</span>{% endif %}
     </div>
   {% else %}
     <span class="text-2xl font-bold text-primary">{{ product.price|floatformat:"0g" }} FCFA</span>
   {% endif %}
   {% endwith %}
   ```
   Réutiliser les classes de la pastille déjà utilisée sur le Marché (`_calendar_list.html`).
3. Remplacer **uniquement** la ligne ~50 de `client_order.html` par `{% include %}` du partial.

## Phase 4 — Formulaire vendeur

Dans le formulaire de création / édition de vente : champ « Affichage des prix promo » (3 choix, aide courte). Avertissement si un produit de la vente dépasse 70 % de remise.

## Tests (à écrire)

- Service : promo absente ; promo ≥ catalogue ; mode net ; 30 % → 30 ; 33,3 % → 33 ; 75 % → net ; économie correcte.
- Vue : mode net → HTML identique à avant (pas de `line-through`) ; mode urgence → ancien prix + « −X % » + « Prix promo ».
- **Non-régression** : le montant total d'une commande créée depuis la page reste `effective_price × quantité` (tests existants orders verts).

## Recette staging (checklist)

- [ ] Vente sans promo : affichage identique à la prod actuelle
- [ ] Vente promo mode `net` : identique à avant
- [ ] Mode `urgence` et `economie` sur téléphone Android d'entrée de gamme
- [ ] Commande passée : total facturé = prix promo
- [ ] Remise > 70 % : pas de prix barré, avertissement vendeur

## Mise en prod

Process `GOVERNANCE_EVOLUTIONS.md` §6. Pas de flag nécessaire : le défaut `net` reproduit le comportement actuel. Observation staging : 24 h.
