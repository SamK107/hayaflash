"""Releves hebdomadaires et versements des marges (spec §15.4) : silence = accord, aucun montant libre.

Le grossiste ne saisit JAMAIS un montant : il regle un releve calcule par le systeme, en une fois,
en donnant la reference Orange Money. Le montant du versement est recopie du releve.

Cycle d'un releve :
  to_pay --(Paye, tentative 1)--> paid --(72 h sans reponse ou « Oui »)--> accepted
  paid --(« Pas recu »)--> contested (contest_count 1) --(une redeclaration, reference differente)--> paid
  paid (tentative 2) --(« Pas recu »)--> escalated (contest_count 2) : l'equipe seule cloture ou rouvre.
Un montant conteste ou escalade reste DU dans tous les calculs (marges dues, plafonds, retards).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.models import audit
from distrib.models import DistribSettlement, DistribStatement, Distributor, ResellerInvite, ResellerPayout

logger = logging.getLogger(__name__)

SS = DistribStatement.Status
PS = ResellerPayout.Status

CONTEST_WINDOW = timedelta(hours=72)
OM_MAX_LENGTH = 40
_OM_CLEAN_RE = re.compile(r"[^A-Za-z0-9]")


def clean_reference(raw: str | None) -> str:
    """Reference Orange Money : chiffres et lettres, longueur bornee, jamais vide."""
    return _OM_CLEAN_RE.sub("", raw or "")[:OM_MAX_LENGTH]


# ── Cloture hebdomadaire ──────────────────────────────────────────────────


def week_bounds(now=None):
    """Semaine ECOULEE : `(lundi, dimanche, borne)` ; `borne` = lundi courant 00:00 local (exclue).

    Une ligne confirmee a 00:00:00 ou plus le lundi appartient au releve suivant."""
    now_local = timezone.localtime(now or timezone.now())
    this_monday = now_local.date() - timedelta(days=now_local.weekday())
    cutoff = timezone.make_aware(datetime.combine(this_monday, time.min))
    return this_monday - timedelta(days=7), this_monday - timedelta(days=1), cutoff


def close_weekly_statements(now=None) -> int:
    """Genere un releve par revendeur pour la semaine ecoulee. Idempotent (unicite revendeur + semaine).

    Rattache les lignes `paid_confirmed` non couvertes confirmees avant la borne ; le montant est la
    somme des marges. Un releve a 0 FCFA n'est pas cree. Une erreur sur un revendeur n'arrete pas les autres."""
    now = now or timezone.now()
    period_start, period_end, cutoff = week_bounds(now)
    invite_ids = list(
        DistribSettlement.objects.filter(
            status=DistribSettlement.Status.PAID_CONFIRMED,
            statement__isnull=True,
            payout__isnull=True,
            paid_confirmed_at__lt=cutoff,
        )
        .values_list("invite_id", flat=True)
        .distinct()
    )
    created = 0
    for invite_id in invite_ids:
        try:
            with transaction.atomic():
                if DistribStatement.objects.filter(invite_id=invite_id, period_start=period_start).exists():
                    continue  # deja cloture : les retardataires iront au releve suivant
                lines = list(
                    DistribSettlement.objects.select_for_update()
                    .filter(
                        invite_id=invite_id,
                        status=DistribSettlement.Status.PAID_CONFIRMED,
                        statement__isnull=True,
                        payout__isnull=True,
                        paid_confirmed_at__lt=cutoff,
                    )
                )
                amount = sum((line.reseller_margin for line in lines), Decimal("0"))
                if not lines or amount <= 0:
                    continue
                invite = ResellerInvite.objects.get(pk=invite_id)
                statement = DistribStatement.objects.create(
                    distributor_id=invite.distributor_id,
                    invite=invite,
                    period_start=period_start,
                    period_end=period_end,
                    amount=amount,
                    line_count=len(lines),
                    closed_at=now,
                )
                DistribSettlement.objects.filter(pk__in=[line.pk for line in lines]).update(statement=statement)
                created += 1
        except Exception:
            logger.exception("distrib: cloture du releve du revendeur %s en echec", invite_id)
    return created


# ── « Paye » (grossiste) ──────────────────────────────────────────────────


def declare_paid(statement: DistribStatement, user, om_reference: str) -> ResellerPayout:
    """Le grossiste regle le releve ENTIER. Montant recopie, jamais saisi ; reference obligatoire.

    Deuxieme appel sur un releve deja paye : refuse sans effet (double clic). Sur un releve conteste
    une seule fois, une redeclaration est permise, avec une reference DIFFERENTE."""
    reference = clean_reference(om_reference)
    if not reference:
        raise ValidationError("La référence Orange Money est obligatoire.")
    with transaction.atomic():
        locked = DistribStatement.objects.select_for_update().select_related("distributor").get(pk=statement.pk)
        if locked.distributor.user_id != user.pk:
            raise PermissionDenied
        if locked.status == SS.TO_PAY:
            pass
        elif locked.status == SS.CONTESTED and locked.contest_count == 1:
            previous = {p.om_reference.lower() for p in locked.payouts.all()}
            if reference.lower() in previous:
                raise ValidationError("Indiquez une nouvelle référence Orange Money, différente de la précédente.")
        elif locked.status == SS.ESCALATED:
            raise ValidationError("Ce relevé est entre les mains de l'équipe HayaFlash.")
        else:
            raise ValidationError("Ce relevé est déjà payé.")
        attempt = locked.payouts.aggregate(m=Max("attempt"))["m"] or 0
        now = timezone.now()
        payout = ResellerPayout.objects.create(
            distributor_id=locked.distributor_id,
            invite_id=locked.invite_id,
            statement=locked,
            attempt=attempt + 1,
            amount=locked.amount,  # recopie du releve
            paid_at=now,
            om_reference=reference,
            recorded_by=user,
            status=PS.DECLARED,
            contest_deadline=now + CONTEST_WINDOW,
        )
        locked.lines.update(payout=payout)  # exactement les lignes du releve
        locked.status = SS.PAID
        locked.save(update_fields=["status"])
        audit(
            "distrib.statement_paid",
            entity_type="DistribStatement",
            entity_id=locked.pk,
            actor=user,
            attempt=payout.attempt,
        )
    return payout


# ── Reponse du revendeur ──────────────────────────────────────────────────


def answer_payout(payout: ResellerPayout, user, *, accept: bool, reason: str = "") -> ResellerPayout:
    """« Oui, recu » ou « Pas recu » (motif). Seul le revendeur concerne, une seule fois."""
    reason = (reason or "").strip()[:255]
    with transaction.atomic():
        statement = DistribStatement.objects.select_for_update().select_related("invite").get(pk=payout.statement_id)
        locked = ResellerPayout.objects.select_for_update().get(pk=payout.pk)
        seller = getattr(user, "seller_profile", None)
        if seller is None or statement.invite.seller_id != seller.pk:
            raise PermissionDenied
        if locked.status != PS.DECLARED or statement.status != SS.PAID:
            raise ValidationError("Ce versement n'attend plus de réponse.")
        if accept:
            locked.status = PS.ACCEPTED
            locked.accepted_source = ResellerPayout.AcceptedSource.RESELLER
            statement.status = SS.ACCEPTED
        else:
            if not reason:
                raise ValidationError("Indiquez en quelques mots pourquoi vous n'avez pas reçu le versement.")
            locked.status = PS.CONTESTED
            locked.contest_reason = reason
            statement.contest_count += 1
            statement.status = SS.ESCALATED if statement.contest_count >= 2 else SS.CONTESTED
        locked.save()
        statement.save(update_fields=["status", "contest_count"])
        if not accept:
            audit(
                "distrib.signal.payout_escalated" if statement.status == SS.ESCALATED else "distrib.signal.payout_contested",
                entity_type="DistribStatement",
                entity_id=statement.pk,
                actor=user,
                distributor_id=statement.distributor_id,
                attempt=locked.attempt,
            )
    return locked


def accept_due_payouts(now=None) -> int:
    """Silence = accord : sans reponse avant `contest_deadline`, le versement est accepte."""
    now = now or timezone.now()
    ids = list(
        ResellerPayout.objects.filter(status=PS.DECLARED, contest_deadline__lte=now).values_list("pk", flat=True)
    )
    done = 0
    for pk in ids:
        try:
            with transaction.atomic():
                payout = ResellerPayout.objects.select_for_update().get(pk=pk)
                statement = DistribStatement.objects.select_for_update().get(pk=payout.statement_id)
                if payout.status != PS.DECLARED or payout.contest_deadline is None or payout.contest_deadline > now:
                    continue
                payout.status = PS.ACCEPTED
                payout.accepted_source = ResellerPayout.AcceptedSource.AUTO
                payout.save(update_fields=["status", "accepted_source"])
                if statement.status == SS.PAID:
                    statement.status = SS.ACCEPTED
                    statement.save(update_fields=["status"])
                done += 1
        except Exception:
            logger.exception("distrib: acceptation automatique du versement %s en echec", pk)
    return done


# ── Equipe HayaFlash (releve escalade) ────────────────────────────────────


def _staff_guard(user, reason: str) -> str:
    if not getattr(user, "is_staff", False):
        raise PermissionDenied
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Le motif est obligatoire.")
    return reason[:255]


def staff_close_escalated(statement: DistribStatement, user, reason: str) -> DistribStatement:
    """L'equipe cloture : releve et dernier versement `accepted`, source `staff`."""
    reason = _staff_guard(user, reason)
    with transaction.atomic():
        locked = DistribStatement.objects.select_for_update().get(pk=statement.pk)
        if locked.status != SS.ESCALATED:
            raise ValidationError("Seul un relevé escaladé peut être clos par l'équipe.")
        payout = locked.payouts.order_by("-attempt").first()
        if payout is not None:
            payout.status = PS.ACCEPTED
            payout.accepted_source = ResellerPayout.AcceptedSource.STAFF
            payout.save(update_fields=["status", "accepted_source"])
        locked.status = SS.ACCEPTED
        locked.save(update_fields=["status"])
        audit("distrib.statement_closed_by_staff", entity_type="DistribStatement", entity_id=locked.pk,
              actor=user, reason=reason)
    return locked


def staff_reopen_escalated(statement: DistribStatement, user, reason: str) -> DistribStatement:
    """L'equipe rouvre : `to_pay`, lignes detachees du versement, compteur remis a zero.

    Le grossiste peut alors regler a nouveau (nouvelle tentative, numerotee a la suite)."""
    reason = _staff_guard(user, reason)
    with transaction.atomic():
        locked = DistribStatement.objects.select_for_update().get(pk=statement.pk)
        if locked.status != SS.ESCALATED:
            raise ValidationError("Seul un relevé escaladé peut être rouvert par l'équipe.")
        locked.lines.update(payout=None)
        locked.status = SS.TO_PAY
        locked.contest_count = 0
        locked.save(update_fields=["status", "contest_count"])
        audit("distrib.statement_reopened_by_staff", entity_type="DistribStatement", entity_id=locked.pk,
              actor=user, reason=reason)
    return locked


# ── Lecture : retards ─────────────────────────────────────────────────────


def overdue_statements(distributor: Distributor, now=None):
    """Releves `to_pay` clos depuis plus de `payout_delay_days` (alerte grossiste, revendeur, pilotage)."""
    now = now or timezone.now()
    limit = now - timedelta(days=distributor.payout_delay_days)
    return DistribStatement.objects.filter(distributor=distributor, status=SS.TO_PAY, closed_at__lt=limit)


def unsettled_statements(distributor: Distributor):
    """Releves contestes ou escalades : toujours dus et signales."""
    return DistribStatement.objects.filter(distributor=distributor, status__in=(SS.CONTESTED, SS.ESCALATED))
