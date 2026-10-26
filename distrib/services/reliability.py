"""Indice de fiabilite d'un grossiste (spec §15.5) : pilotage HayaFlash uniquement en V1.

Calcule sur 30 jours glissants. Aucune sanction automatique : l'indice ne sert qu'a alerter
l'equipe, qui echange en prive avec le grossiste. Jamais montre aux revendeurs (V2).

Definitions (testees, `distrib/tests_reliability.py`) :
- taux « Pas livre » = lignes `not_delivered` / lignes creees sur la periode hors `cancelled` ;
- conflits = lignes `conflict_flag` mises a jour sur la periode (le drapeau n'a pas d'horodatage propre) ;
- versements contestes = versements au statut `contested` declares sur la periode ;
- retards = releves `to_pay` clos depuis plus de `payout_delay_days` (etat courant) ;
- repartition des confirmations = lignes `paid_confirmed` confirmees sur la periode, par source.
Un seuil a 0 desactive l'alerte correspondante.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from distrib.models import DistribSettlement, Distributor, ResellerPayout

from . import statements

WINDOW_DAYS = 30

S = DistribSettlement.Status

ALERT_NOT_DELIVERED = "not_delivered"
ALERT_CONFLICTS = "conflicts"
ALERT_CONTESTED = "contested"
ALERT_OVERDUE = "overdue"

ALERT_LABELS = {
    ALERT_NOT_DELIVERED: "Trop de « Pas livré »",
    ALERT_CONFLICTS: "Conflit : la cliente a confirmé une livraison déclarée non faite",
    ALERT_CONTESTED: "Versement contesté par un revendeur",
    ALERT_OVERDUE: "Relevé en retard de règlement",
}


def _percent(part: int, total: int) -> Decimal:
    if not total:
        return Decimal("0.0")
    return (Decimal(part) * 100 / Decimal(total)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def reliability(distributor: Distributor, now=None) -> dict:
    now = now or timezone.now()
    since = now - timedelta(days=WINDOW_DAYS)
    base = DistribSettlement.objects.filter(distributor=distributor)

    considered = base.filter(created_at__gte=since).exclude(status=S.CANCELLED)
    total = considered.count()
    declined = considered.filter(status=S.NOT_DELIVERED)
    not_delivered = declined.count()
    reasons = {value: 0 for value, _ in DistribSettlement.NotDeliveredReason.choices}
    for reason in declined.values_list("not_delivered_reason", flat=True):
        if reason in reasons:
            reasons[reason] += 1

    conflicts = base.filter(conflict_flag=True, updated_at__gte=since).count()
    contested = ResellerPayout.objects.filter(
        distributor=distributor, status=ResellerPayout.Status.CONTESTED, paid_at__gte=since
    ).count()
    overdue = statements.overdue_statements(distributor, now).count()

    confirmed = base.filter(status=S.PAID_CONFIRMED, paid_confirmed_at__gte=since)
    confirmed_total = confirmed.count()
    sources = {}
    for value, label in DistribSettlement.ConfirmationSource.choices:
        count = confirmed.filter(confirmation_source=value).count()
        sources[value] = {"label": label, "count": count, "percent": _percent(count, confirmed_total)}

    alerts = []
    threshold = distributor.alert_not_delivered_percent
    if threshold and not_delivered * 100 > threshold * total:
        alerts.append(ALERT_NOT_DELIVERED)
    if distributor.alert_conflicts and conflicts >= distributor.alert_conflicts:
        alerts.append(ALERT_CONFLICTS)
    if distributor.alert_contested and contested >= distributor.alert_contested:
        alerts.append(ALERT_CONTESTED)
    if overdue:
        alerts.append(ALERT_OVERDUE)

    return {
        "window_days": WINDOW_DAYS,
        "total": total,
        "not_delivered": not_delivered,
        "not_delivered_percent": _percent(not_delivered, total),
        "reasons": reasons,
        "reason_list": [
            {"label": label, "count": reasons[value]}
            for value, label in DistribSettlement.NotDeliveredReason.choices
            if reasons[value]
        ],
        "conflicts": conflicts,
        "contested": contested,
        "overdue": overdue,
        "confirmed_total": confirmed_total,
        "sources": sources,
        "alerts": alerts,
        "alert_labels": [ALERT_LABELS[a] for a in alerts],
    }
