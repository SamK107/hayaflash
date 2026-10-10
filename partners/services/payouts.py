"""Validation mensuelle, versements, relevé à copier dans WhatsApp, exports CSV.

Règles :
- les commissions ne sont JAMAIS validées automatiquement ;
- un versement n'existe qu'à partir de PARTNER_MIN_PAYOUT_FCFA (le cumul est
  reporté d'un mois à l'autre), échéance le 10 du mois suivant ;
- « Marquer comme payé » exige une référence Orange et ne se fait qu'une fois ;
- le relevé destiné au partenaire n'indique JAMAIS de nom, téléphone ni boutique :
  uniquement des identifiants anonymes (« Vendeur 1 »).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import audit
from partners.models import (
    CommissionEntry,
    CommissionStatus,
    Partner,
    Payout,
    PayoutStatus,
    Referral,
)
from partners.services.activity import activation_dates

MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
PLAN_LABELS = {"medium": "Medium", "pro": "Pro", "free": "Gratuit"}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_period(period: str) -> tuple[int, int]:
    match = PERIOD_RE.match(period or "")
    if not match:
        raise ValidationError("Période invalide : utilisez le format AAAA-MM.")
    return int(match.group(1)), int(match.group(2))


def period_bounds(period: str) -> tuple[datetime, datetime]:
    """[début, fin[ du mois, en datetimes aware (fuseau du projet)."""
    year, month = parse_period(period)
    tz = timezone.get_current_timezone()
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=tz)
    return start, end


def fmt(amount: int) -> str:
    return f"{int(amount):,}".replace(",", " ")


def _entries(partner: Partner):
    return CommissionEntry.objects.filter(referral__partner=partner)


def _unversed(partner: Partner, end: datetime):
    return _entries(partner).filter(
        status=CommissionStatus.VALIDATED, payout__isnull=True, payment__paid_at__lt=end
    )


def carried_over(partner: Partner, period: str) -> int:
    """Commissions validées pas encore versées, jusqu'à la fin du mois."""
    _, end = period_bounds(period)
    return _unversed(partner, end).aggregate(t=Sum("commission_fcfa"))["t"] or 0


@transaction.atomic
def validate_month(partner: Partner, period: str, *, actor=None) -> int:
    """pending -> validated pour les paiements du mois. Jamais automatique."""
    start, end = period_bounds(period)
    qs = _entries(partner).filter(
        status=CommissionStatus.PENDING, payment__paid_at__gte=start, payment__paid_at__lt=end
    )
    ids = list(qs.values_list("pk", flat=True))
    if not ids:
        return 0
    CommissionEntry.objects.filter(pk__in=ids).update(
        status=CommissionStatus.VALIDATED, validated_at=timezone.now()
    )
    audit(
        "partner.commissions_validated",
        entity_type="Partner",
        entity_id=partner.pk,
        actor=actor,
        period=period,
        count=len(ids),
    )
    return len(ids)


@transaction.atomic
def build_payout(partner: Partner, period: str) -> Payout | None:
    """Crée (ou complète) le versement du mois ; None sous le minimum (cumul reporté)."""
    _, end = period_bounds(period)
    existing = Payout.objects.select_for_update().filter(partner=partner, period=period).first()
    if existing is not None and existing.status == PayoutStatus.PAID:
        raise ValidationError("Le versement de cette période est déjà payé.")
    eligible = list(_unversed(partner, end).select_for_update())
    new_total = sum(e.commission_fcfa for e in eligible)
    if existing is None:
        if new_total < settings.PARTNER_MIN_PAYOUT_FCFA:
            return None
        payout = Payout.objects.create(partner=partner, period=period, total_fcfa=new_total)
    else:
        payout = existing
        payout.total_fcfa += new_total
        payout.save(update_fields=["total_fcfa"])
    CommissionEntry.objects.filter(pk__in=[e.pk for e in eligible]).update(payout=payout)
    return payout


@transaction.atomic
def mark_paid(payout: Payout, reference: str, *, actor=None) -> Payout:
    """Marque le versement et ses lignes comme payés (référence Orange obligatoire)."""
    reference = (reference or "").strip()
    if not reference:
        raise ValidationError("Indiquez la référence Orange du versement.")
    locked = Payout.objects.select_for_update().get(pk=payout.pk)
    if locked.status == PayoutStatus.PAID:
        raise ValidationError("Ce versement est déjà marqué comme payé.")
    locked.status = PayoutStatus.PAID
    locked.orange_reference = reference[:80]
    locked.paid_at = timezone.now()
    locked.save(update_fields=["status", "orange_reference", "paid_at"])
    CommissionEntry.objects.filter(payout=locked).update(status=CommissionStatus.PAID)
    audit(
        "partner.payout_paid",
        entity_type="Payout",
        entity_id=locked.pk,
        actor=actor,
        partner_id=locked.partner_id,
        period=locked.period,
        total_fcfa=locked.total_fcfa,
        reference=locked.orange_reference,
    )
    payout.status, payout.orange_reference, payout.paid_at = (
        locked.status,
        locked.orange_reference,
        locked.paid_at,
    )
    return locked


# ── Relevé et exports ─────────────────────────────────────────────────────────

def _anonymous_ids(partner: Partner) -> dict[int, int]:
    """referral_id -> numéro stable (« Vendeur n »), parmi les inscriptions via le lien ayant une commission."""
    ids = (
        _entries(partner)
        .exclude(status=CommissionStatus.CANCELLED)
        .values_list("referral_id", flat=True)
        .distinct()
    )
    return {rid: rank for rank, rid in enumerate(sorted(set(ids)), start=1)}


def _months_left(referral: Referral, year: int, month: int) -> int:
    ends = referral.commission_ends_at
    if ends is None:
        return 0
    return max(0, (ends.year - year) * 12 + (ends.month - month))


def _month_entries(partner: Partner, period: str, *, with_cancelled=False):
    start, end = period_bounds(period)
    qs = (
        _entries(partner)
        .filter(payment__paid_at__gte=start, payment__paid_at__lt=end)
        .select_related("referral", "payment", "payout")
        .order_by("referral_id", "payment__paid_at")
    )
    return qs if with_cancelled else qs.exclude(status=CommissionStatus.CANCELLED)


def statement_text(partner: Partner, period: str) -> str:
    """Texte français prêt à copier dans WhatsApp. Aucune donnée identifiante du vendeur."""
    year, month = parse_period(period)
    _, end = period_bounds(period)
    anon = _anonymous_ids(partner)

    referrals = Referral.objects.filter(partner=partner, attributed_at__lt=end)
    valid_ids = list(referrals.filter(flagged=False).values_list("seller_id", flat=True))
    active = sum(1 for d in activation_dates(valid_ids).values() if d < end)
    payers = (
        _entries(partner)
        .exclude(status=CommissionStatus.CANCELLED)
        .filter(payment__paid_at__lt=end)
        .values("referral_id")
        .distinct()
        .count()
    )

    lines = [
        f"Relevé HayaFlash · {partner.name}",
        f"Période : {MONTHS_FR[month - 1]} {year}",
        f"Vendeurs inscrits via votre lien : {referrals.count()} · actifs : {active} · payants : {payers}",
        "",
    ]
    entries = list(_month_entries(partner, period))
    if not entries:
        lines.append("Aucune commission ce mois-ci.")
    month_total = 0
    for entry in entries:
        left = _months_left(entry.referral, year, month)
        left_text = f"{left} mois restants" if left > 1 else f"{left} mois restant"
        plan = PLAN_LABELS.get(entry.payment.plan, entry.payment.plan)
        lines.append(f"Vendeur {anon[entry.referral_id]} · {plan} · {left_text}")
        lines.append(
            f"  Net : {fmt(entry.net_fcfa)} FCFA · {entry.percent} % · "
            f"commission : {fmt(entry.commission_fcfa)} FCFA"
        )
        month_total += entry.commission_fcfa
    cumul = carried_over(partner, period)
    lines += ["", f"Commission du mois : {fmt(month_total)} FCFA", f"Cumul non versé : {fmt(cumul)} FCFA"]

    payout = Payout.objects.filter(partner=partner, period=period).first()
    if payout is not None and payout.status == PayoutStatus.PAID:
        lines.append(
            f"Versement effectué : référence {payout.orange_reference} · "
            f"le {timezone.localtime(payout.paid_at):%d/%m/%Y}"
        )
    elif payout is not None:
        lines.append(f"Versement de {fmt(payout.total_fcfa)} FCFA à effectuer avant le {payout.due_date:%d/%m/%Y}")
    elif cumul >= settings.PARTNER_MIN_PAYOUT_FCFA:
        due = Payout(partner=partner, period=period).due_date
        lines.append(f"Versement à venir : {fmt(cumul)} FCFA avant le {due:%d/%m/%Y}")
    elif entries or cumul:
        lines.append(
            f"Pas de versement ce mois : minimum {fmt(settings.PARTNER_MIN_PAYOUT_FCFA)} FCFA "
            "(le cumul est reporté au mois suivant)."
        )
    return "\n".join(lines)


def csv_safe(value) -> str:
    """Neutralise l'injection de formules (= + - @) par une apostrophe en tête."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _csv(header: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([csv_safe(h) for h in header])
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
    return "﻿" + buffer.getvalue()  # BOM : Excel lit l'UTF-8


def _paid_date(entry) -> str:
    return f"{timezone.localtime(entry.payment.paid_at):%d/%m/%Y}" if entry.payment.paid_at else ""


def partner_csv(partner: Partner, period: str) -> tuple[str, str]:
    """Export remis au partenaire : anonymisé. Retourne (contenu, nom de fichier)."""
    anon = _anonymous_ids(partner)
    year, month = parse_period(period)
    rows = [
        [
            period,
            f"Vendeur {anon[e.referral_id]}",
            f"{PLAN_LABELS.get(e.payment.plan, e.payment.plan)} · {_months_left(e.referral, year, month)} mois restants",
            e.net_fcfa,
            e.percent,
            e.commission_fcfa,
            e.get_status_display(),
            _paid_date(e),
        ]
        for e in _month_entries(partner, period)
    ]
    header = [
        "Période", "Vendeur", "Formule", "Net (FCFA)", "Commission (%)",
        "Commission (FCFA)", "Statut", "Date de paiement",
    ]
    return _csv(header, rows), f"hayaflash-partenaire-{partner.code}-{period}.csv"


def internal_csv(partner: Partner, period: str) -> tuple[str, str]:
    """Export interne complet (équipe HayaFlash) : ne jamais le transmettre au partenaire."""
    rows = [
        [
            period,
            partner.name,
            e.referral.seller.user.display_name,
            e.referral.seller.business_name,
            e.referral.seller.user.phone,
            PLAN_LABELS.get(e.payment.plan, e.payment.plan),
            e.gross_fcfa,
            e.net_fcfa,
            e.percent,
            e.commission_fcfa,
            e.get_status_display(),
            e.payout.orange_reference if e.payout_id else "",
            _paid_date(e),
        ]
        for e in _month_entries(partner, period, with_cancelled=True).select_related(
            "referral__seller__user"
        )
    ]
    header = [
        "Période", "Partenaire", "Vendeur (nom)", "Boutique", "Téléphone", "Formule",
        "Montant payé (FCFA)", "Net (FCFA)", "Commission (%)", "Commission (FCFA)",
        "Statut", "Référence versement", "Date de paiement",
    ]
    return _csv(header, rows), f"hayaflash-interne-{partner.code}-{period}.csv"
