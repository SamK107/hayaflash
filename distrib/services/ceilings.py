"""Plafonds et coupure progressive (spec §15.6).

Deux plafonds distincts :
- marges dues PAR REVENDEUR (`reseller_credit_ceiling`) : bloque ce revendeur ;
- encours de commission du grossiste (`credit_ceiling`) : bloque tout le grossiste.

Seuls les NOUVELLES allocations et importations sont bloquees (> 100 %). Jamais les
commandes en cours, les ventes deja ouvertes, la livraison ni les reprises de stock.
Deblocage automatique : tout est recalcule a chaque appel, rien n'est memorise.

P5 : calculs de base sur les lignes de suivi existantes. Le calcul complet (releves,
versements declares/acceptes) est complete en P7.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from distrib.models import (
    Distributor,
    DistribPayment,
    DistribSettlement,
    ResellerInvite,
    ResellerPayout,
)

ALERT_RATIO = Decimal("0.8")  # >= 80 % : alerte orange

LEVEL_OK = "ok"
LEVEL_WARNING = "warning"
LEVEL_BLOCKED = "blocked"

RESELLER_BLOCK_MESSAGE = "Règle les marges dues pour débloquer les nouvelles allocations."
COMMISSION_BLOCK_MESSAGE = (
    "Les nouvelles allocations sont bloquées : règle la commission due à HayaFlash pour débloquer."
)


def reseller_due(invite: ResellerInvite) -> Decimal:
    """Marges confirmees non encore versees (les versements contestes restent dus)."""
    total = (
        DistribSettlement.objects.filter(
            invite=invite, status=DistribSettlement.Status.PAID_CONFIRMED
        )
        .filter(Q(payout__isnull=True) | Q(payout__status=ResellerPayout.Status.CONTESTED))
        .aggregate(t=Sum("reseller_margin"))["t"]
    )
    return total or Decimal("0")


def commission_outstanding(distributor: Distributor) -> Decimal:
    """Commissions facturables confirmees − reglements enregistres par l'equipe."""
    billed = (
        DistribSettlement.objects.filter(
            distributor=distributor,
            status=DistribSettlement.Status.PAID_CONFIRMED,
            commission_billable=True,
        ).aggregate(t=Sum("commission_amount"))["t"]
        or Decimal("0")
    )
    paid = DistribPayment.objects.filter(distributor=distributor).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    return billed - paid


def level(amount: Decimal, ceiling: Decimal) -> str:
    """`blocked` strictement au-dessus du plafond, `warning` des 80 %."""
    if ceiling <= 0:
        return LEVEL_BLOCKED if amount > 0 else LEVEL_OK
    if amount > ceiling:
        return LEVEL_BLOCKED
    if amount >= ceiling * ALERT_RATIO:
        return LEVEL_WARNING
    return LEVEL_OK


def reseller_level(invite: ResellerInvite) -> str:
    return level(reseller_due(invite), invite.distributor.reseller_credit_ceiling)


def commission_level(distributor: Distributor) -> str:
    return level(commission_outstanding(distributor), distributor.credit_ceiling)


def allocation_block_reason(distributor: Distributor, invite: ResellerInvite) -> str | None:
    """Message a afficher si une NOUVELLE allocation / importation est bloquee, sinon None."""
    if reseller_level(invite) == LEVEL_BLOCKED:
        return RESELLER_BLOCK_MESSAGE
    if commission_level(distributor) == LEVEL_BLOCKED:
        return COMMISSION_BLOCK_MESSAGE
    return None
