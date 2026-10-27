"""Chiffres des tableaux de bord (spec §6) : grossiste, revendeur, pilotage.

Lecture seule : aucune ecriture, aucun effet de bord. Les montants sont des FCFA entiers.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from distrib.models import (
    DistribSettlement,
    DistribStatement,
    Distributor,
    ImportedProduct,
    ResellerInvite,
    ResellerPayout,
)

from . import ceilings, statements
from . import settlement as settlement_service

S = DistribSettlement.Status
ZERO = Decimal("0")


def _sum(qs, field: str) -> Decimal:
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def month_start(now):
    local = timezone.localtime(now)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def day_start(now):
    return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)


def format_remaining(seconds: float) -> str:
    """« 2 j 3 h », « 5 h 20 min », « 12 min » : lisible d'un coup d'oeil sur un telephone."""
    minutes = max(0, int(seconds // 60))
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} j {hours} h" if hours else f"{days} j"
    if hours:
        return f"{hours} h {mins:02d} min" if mins else f"{hours} h"
    return f"{max(mins, 1)} min"


def distributor_summary(distributor: Distributor, now=None) -> dict:
    """Accueil grossiste : commandes du jour, en livraison, a confirmer, CA du mois, marges dues, encours."""
    now = now or timezone.now()
    lines = DistribSettlement.objects.filter(distributor=distributor)
    outstanding = ceilings.commission_outstanding(distributor)
    margins_due = ZERO
    reseller_alerts = 0
    for invite in distributor.invites.filter(status__in=("accepted", "revoked")):
        due = ceilings.reseller_due(invite)
        margins_due += due
        if ceilings.level(due, distributor.reseller_credit_ceiling) != ceilings.LEVEL_OK:
            reseller_alerts += 1
    to_pay = distributor.statements.filter(status=DistribStatement.Status.TO_PAY)
    return {
        "orders_today": lines.filter(created_at__gte=day_start(now))
        .exclude(status=S.CANCELLED)
        .values("order_id")
        .distinct()
        .count(),
        "in_delivery": lines.filter(status=S.IN_DELIVERY).count(),
        "to_confirm": lines.filter(status__in=settlement_service.OPEN_STATUSES).count(),
        "revenue_month": _sum(
            lines.filter(status=S.PAID_CONFIRMED, paid_confirmed_at__gte=month_start(now)), "sale_amount"
        ),
        "margins_due": margins_due,
        "outstanding": outstanding,
        "commission_level": ceilings.level(outstanding, distributor.credit_ceiling),
        "statements_to_pay": to_pay.count(),
        "statements_to_pay_amount": _sum(to_pay, "amount"),
        "statements_contested": statements.unsettled_statements(distributor).count(),
        "overdue": list(statements.overdue_statements(distributor, now).select_related("invite")),
        "reseller_alerts": reseller_alerts,
    }


def reseller_overview(distributor: Distributor) -> list[dict]:
    """Une ligne par revendeur : ventes, stock alloue, marges dues, dernier versement (spec §6 « Revendeurs »)."""
    rows = []
    for invite in distributor.invites.select_related("seller"):
        lines = DistribSettlement.objects.filter(invite=invite)
        stock = ImportedProduct.objects.filter(invite=invite).aggregate(t=Sum("allocated_qty"))["t"] or 0
        due = ceilings.reseller_due(invite)
        rows.append(
            {
                "invite": invite,
                "sales": lines.filter(status=S.PAID_CONFIRMED).count(),
                "in_progress": lines.filter(status__in=settlement_service.OPEN_STATUSES).count(),
                "stock": stock,
                "due": due,
                "level": ceilings.level(due, distributor.reseller_credit_ceiling),
                "last_payout": ResellerPayout.objects.filter(invite=invite).order_by("-paid_at").first(),
            }
        )
    return rows


def reseller_summary(seller, now=None) -> dict:
    """« Mes grossistes » / « Mes gains » : totaux de la boutique, tous grossistes confondus."""
    now = now or timezone.now()
    invites = ResellerInvite.objects.filter(seller=seller, status__in=("accepted", "revoked"))
    lines = DistribSettlement.objects.filter(invite__in=invites)
    return {
        "due": sum((ceilings.reseller_due(i) for i in invites), ZERO),
        "in_progress": lines.filter(status__in=settlement_service.OPEN_STATUSES).count(),
        "waiting_statement": lines.filter(status=S.PAID_CONFIRMED, statement__isnull=True).count(),
        "to_answer": ResellerPayout.objects.filter(invite__in=invites, status=ResellerPayout.Status.DECLARED).count(),
        "received_month": _sum(
            ResellerPayout.objects.filter(
                invite__in=invites, status=ResellerPayout.Status.ACCEPTED, paid_at__gte=month_start(now)
            ),
            "amount",
        ),
    }


def pilotage_totals(now=None) -> dict:
    """Bandeau du pilotage : ce qui demande l'attention de l'equipe."""
    now = now or timezone.now()
    since = now - timedelta(days=30)
    return {
        "conflicts": DistribSettlement.objects.filter(conflict_flag=True).count(),
        "statements_open": DistribStatement.objects.filter(
            status__in=(DistribStatement.Status.CONTESTED, DistribStatement.Status.ESCALATED)
        ).count(),
        "outstanding": sum((ceilings.commission_outstanding(d) for d in Distributor.objects.all()), ZERO),
        "orders_30d": DistribSettlement.objects.filter(created_at__gte=since)
        .aggregate(n=Count("order_id", distinct=True, filter=~Q(status=S.CANCELLED)))["n"],
    }
