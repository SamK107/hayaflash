"""Reporting plateforme (staff only) : pilotage commercial et financier HayaFlash.

Chiffre d'affaires (CA) : paiements reussis HORS paiements a tarif special de
motif "test" (tests de paiement reel, pas du revenu). Les tarifs speciaux
hors test (pilote, partenaire, promo) sont du vrai revenu, mais affiches a
part des revenus au prix officiel (get_revenue_breakdown).

Retrocession Orange (get_orange_remittance_summary) : TOUS les paiements
Orange reussis, tests compris -- l'argent a bien ete encaisse par Orange.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from subscriptions.models import (
    OverrideReason,
    PaymentProvider,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionPayment,
)

TEST_PAYMENT_Q = Q(price_override__reason=OverrideReason.TEST)


def revenue_payments():
    """Paiements comptes dans le CA : reussis, hors tests de paiement."""
    return SubscriptionPayment.objects.filter(status=PaymentStatus.SUCCESS).exclude(
        TEST_PAYMENT_Q
    )

# Orange Money retient 1% de commission sur chaque paiement d'abonnement reussi
# et reverse le reste (99%) a HayaFlash.
ORANGE_COMMISSION_RATE = Decimal("0.01")


def get_subscription_revenue_timeline_monthly(months: int = 12) -> list[dict]:
    """CA plateforme (tous providers) issu des abonnements payes, par mois."""
    start_date = timezone.now() - timedelta(days=30 * months)
    rows = (
        revenue_payments()
        .filter(paid_at__gte=start_date)
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(revenue=Sum("amount"))
        .order_by("month")
    )
    return [
        {"month": r["month"].strftime("%Y-%m"), "revenue": float(r["revenue"] or 0)}
        for r in rows
        if r["month"] is not None
    ]


def get_subscription_revenue_ytd() -> Decimal:
    """CA plateforme (tous providers) depuis le 1er janvier de l'annee en cours."""
    year_start = timezone.now().replace(
        month=1, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    total = (
        revenue_payments()
        .filter(paid_at__gte=year_start)
        .aggregate(total=Sum("amount"))["total"]
    )
    return total or Decimal("0")


def get_revenue_breakdown(since=None) -> dict:
    """Revenus separes : prix officiel / tarif special (hors test) / tests.

    Chaque entree : {"total": int, "count": int}. `since` = date de debut
    (paid_at), None = tout l'historique.
    """
    qs = SubscriptionPayment.objects.filter(status=PaymentStatus.SUCCESS)
    if since is not None:
        qs = qs.filter(paid_at__gte=since)

    def _agg(sub_qs) -> dict:
        row = sub_qs.aggregate(total=Sum("amount"), count=Count("id"))
        return {"total": int(row["total"] or 0), "count": row["count"]}

    return {
        "official": _agg(qs.filter(is_special_price=False)),
        "special": _agg(qs.filter(is_special_price=True).exclude(TEST_PAYMENT_Q)),
        "test": _agg(qs.filter(TEST_PAYMENT_Q)),
    }


def get_orange_remittance_summary() -> dict:
    """
    Montant qu'Orange Money doit reverser a HayaFlash.

    Orange retient ORANGE_COMMISSION_RATE (1%) de commission sur chaque paiement
    d'abonnement reussi et doit reverser le solde (99%).
    """

    def _summary(total: Decimal | None) -> dict:
        total = total or Decimal("0")
        commission = (total * ORANGE_COMMISSION_RATE).quantize(Decimal("1"))
        return {
            "total_collected": total,
            "commission": commission,
            "to_remit": total - commission,
        }

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    base_qs = SubscriptionPayment.objects.filter(
        provider=PaymentProvider.ORANGE,
        status=PaymentStatus.SUCCESS,
    )
    month_total = base_qs.filter(paid_at__gte=month_start).aggregate(
        total=Sum("amount")
    )["total"]
    all_time_total = base_qs.aggregate(total=Sum("amount"))["total"]

    return {
        "month": _summary(month_total),
        "all_time": _summary(all_time_total),
    }


def get_subscribed_sellers() -> list[Subscription]:
    """Vendeurs avec un abonnement payant (Medium/Pro), pour supervision plateforme."""
    return list(
        Subscription.objects.filter(plan__in=[Plan.MEDIUM, Plan.PRO])
        .select_related("seller", "seller__user")
        .order_by("-plan", "expires_at")
    )
