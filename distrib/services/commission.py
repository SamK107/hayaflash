"""Commission HayaFlash (spec §5.5, §15.7).

Calculee au passage a `paid_confirmed` (toute source), des le premier mois :
`clamp(vente × taux, minimum, maximum)` arrondi au FCFA. Elle n'est FACTURABLE
qu'apres `pilot_until` (periode d'essai) : l'encours ne compte que les lignes facturables.

Le plafond `commission_max` (1 500 FCFA par defaut) s'applique par ligne de suivi, c'est-a-dire
par article importe : l'interface cliente ne commande qu'un produit a la fois, une commande
porte donc une seule ligne. Une commande API multi-produits aurait un plafond par article.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from distrib.models import Distributor

ZERO = Decimal("0")


def commission_for(distributor: Distributor, sale_amount, on_date: date) -> tuple[Decimal, bool]:
    """`(montant en FCFA entiers, facturable ?)` pour une vente confirmee a `on_date`."""
    sale = Decimal(sale_amount)
    if sale <= 0:
        return ZERO, False
    raw = (sale * distributor.commission_rate / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    amount = min(max(raw, distributor.commission_min), distributor.commission_max)
    billable = distributor.pilot_until is None or on_date > distributor.pilot_until
    return amount, billable
