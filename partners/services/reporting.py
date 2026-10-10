"""Chiffres des pages admin du programme partenaires (requêtes agrégées, pas de N+1)."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import Count, Exists, Max, OuterRef, Q, Sum
from django.utils import timezone

from flash_sales.models import FlashSaleStatus
from orders.models import Order, OrderStatus
from partners.models import (
    SLOT_HOLDING_STATUSES,
    CommissionEntry,
    CommissionStatus,
    Partner,
    PartnerClick,
    PartnerStatus,
    Payout,
    PayoutStatus,
    Referral,
)
from partners.services.contract import quarterly_statuses
from partners.services.payouts import period_bounds


def current_period() -> str:
    return timezone.localtime(timezone.now()).strftime("%Y-%m")


def _active_referrals():
    """Parrainages dont le vendeur est actif (commande non annulée, vente non annulée)."""
    has_order = Order.service_objects.filter(flash_sale__owner_id=OuterRef("seller_id")).exclude(
        status=OrderStatus.CANCELLED
    ).exclude(flash_sale__status=FlashSaleStatus.CANCELLED)
    return Referral.objects.filter(flagged=False).filter(Exists(has_order))


def _live_entries():
    return CommissionEntry.objects.exclude(status=CommissionStatus.CANCELLED)


def _rate(part: int, whole: int) -> int:
    return int(part * 100 // whole) if whole else 0


def dashboard_stats() -> dict:
    start, end = period_bounds(current_period())
    money = CommissionEntry.objects.aggregate(
        to_validate=Sum("commission_fcfa", filter=Q(status=CommissionStatus.PENDING)),
        to_pay=Sum("commission_fcfa", filter=Q(status=CommissionStatus.VALIDATED)),
        attributed=Sum(
            "net_fcfa",
            filter=~Q(status=CommissionStatus.CANCELLED)
            & Q(payment__paid_at__gte=start, payment__paid_at__lt=end),
        ),
    )
    return {
        "clicks": PartnerClick.objects.count(),
        "referrals": Referral.objects.count(),
        "active": _active_referrals().count(),
        "payers": _live_entries().values("referral_id").distinct().count(),
        "attributed_net_fcfa": money["attributed"] or 0,
        "to_validate_fcfa": money["to_validate"] or 0,
        "to_pay_fcfa": money["to_pay"] or 0,
        "slots_used": Partner.objects.filter(
            is_founder=True, status__in=SLOT_HOLDING_STATUSES, phase="contract"
        ).count(),
        "slots_total": settings.PARTNER_FOUNDER_SLOTS,
    }


def _active_by_partner() -> dict[int, int]:
    rows = _active_referrals().values("partner_id").annotate(n=Count("id"))
    return {r["partner_id"]: r["n"] for r in rows}


def funnel() -> list[dict]:
    """Clics -> inscrits -> actifs -> payants, par partenaire, avec les taux."""
    partners = Partner.objects.annotate(
        clicks_n=Count("clicks", distinct=True),
        signups_n=Count("referrals", distinct=True),
        payers_n=Count(
            "referrals",
            filter=Q(referrals__commissions__isnull=False)
            & ~Q(referrals__commissions__status=CommissionStatus.CANCELLED),
            distinct=True,
        ),
    ).order_by("name")
    active = _active_by_partner()
    rows = []
    for p in partners:
        n_active = active.get(p.pk, 0)
        rows.append(
            {
                "partner": p,
                "clicks": p.clicks_n,
                "signups": p.signups_n,
                "active": n_active,
                "payers": p.payers_n,
                "signup_rate": _rate(p.signups_n, p.clicks_n),
                "active_rate": _rate(n_active, p.signups_n),
                "payer_rate": _rate(p.payers_n, p.signups_n),
            }
        )
    return rows


def alerts() -> dict:
    now = timezone.now()
    limit = now - timedelta(days=settings.PARTNER_INACTIVE_ALERT_DAYS)
    inactive = []
    for p in (
        Partner.objects.filter(status=PartnerStatus.ACTIVE)
        .annotate(
            last_click=Max("clicks__created_at"),
            last_referral=Max("referrals__attributed_at"),
            last_commission=Max("referrals__commissions__created_at"),
        )
        .order_by("name")
    ):
        seen = [d for d in (p.last_click, p.last_referral, p.last_commission) if d]
        # Sans aucune activité : on compte depuis le début du contrat.
        last = max(seen) if seen else timezone.make_aware(
            datetime.combine(p.contract_start, time.min)
        )
        if last < limit:
            p.last_activity = last
            inactive.append(p)

    holders = list(
        Partner.objects.filter(status__in=SLOT_HOLDING_STATUSES, phase="contract").order_by("name")
    )
    statuses = quarterly_statuses(holders)
    releasable = [p for p in holders if statuses[p.pk]["releasable"]]

    today = timezone.localdate()
    overdue = [
        po
        for po in Payout.objects.filter(status=PayoutStatus.DUE).select_related("partner")
        if po.due_date < today
    ]
    flagged = list(
        Referral.objects.filter(flagged=True)
        .select_related("partner", "seller__user")
        .order_by("-attributed_at")[:50]
    )
    return {
        "inactive": inactive,
        "flagged": flagged,
        "releasable": releasable,
        "overdue": overdue,
        "total": len(inactive) + len(flagged) + len(releasable) + len(overdue),
    }


def partner_rows() -> list[dict]:
    partners = list(Partner.objects.order_by("name"))
    money = {
        r["referral__partner_id"]: r
        for r in CommissionEntry.objects.values("referral__partner_id").annotate(
            due=Sum("commission_fcfa", filter=Q(status=CommissionStatus.VALIDATED)),
            paid=Sum("commission_fcfa", filter=Q(status=CommissionStatus.PAID)),
            pending=Sum("commission_fcfa", filter=Q(status=CommissionStatus.PENDING)),
        )
    }
    active = _active_by_partner()
    quarterly = quarterly_statuses(partners)
    return [
        {
            "partner": p,
            "active_sellers": active.get(p.pk, 0),
            "due_fcfa": (money.get(p.pk) or {}).get("due") or 0,
            "paid_fcfa": (money.get(p.pk) or {}).get("paid") or 0,
            "pending_fcfa": (money.get(p.pk) or {}).get("pending") or 0,
            "quarterly": quarterly[p.pk],
        }
        for p in partners
    ]
