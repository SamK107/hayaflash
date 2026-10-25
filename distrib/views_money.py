"""Argent : releves et versements (grossiste), « Mes gains » (revendeur) — spec §15.4, §15.6, §15.7.

Aucun champ montant dans les formulaires : le releve est calcule, le grossiste ne donne que la
reference Orange Money, le revendeur ne repond que « Oui » ou « Pas recu » (+ motif).
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import distributor_required, reseller_required
from .models import DistribPayment, DistribSettlement, DistribStatement, ResellerInvite, ResellerPayout
from .services import ceilings, statements
from .services import settlement as settlement_service
from .views_orders import auto_confirm_info


def _text(exc: ValidationError) -> str:
    return " ".join(exc.messages)


# ── Grossiste ─────────────────────────────────────────────────────────────


@distributor_required
def statements_list(request):
    distributor = request.distributor
    now = timezone.now()
    outstanding = ceilings.commission_outstanding(distributor)
    resellers = []
    for invite in distributor.invites.filter(status__in=("accepted", "revoked")):
        due = ceilings.reseller_due(invite)
        resellers.append({"invite": invite, "due": due, "level": ceilings.reseller_level(invite)})
    rows = []
    for statement in distributor.statements.select_related("invite").prefetch_related("payouts")[:50]:
        can_pay = statement.status == DistribStatement.Status.TO_PAY or (
            statement.status == DistribStatement.Status.CONTESTED and statement.contest_count == 1
        )
        rows.append(
            {
                "statement": statement,
                "can_pay": can_pay,
                "redeclare": statement.status == DistribStatement.Status.CONTESTED,
                "payout": statement.payouts.all().order_by("-attempt").first() if statement.pk else None,
            }
        )
    return render(
        request,
        "distrib/statements.html",
        {
            "distributor": distributor,
            "rows": rows,
            "resellers": resellers,
            "outstanding": outstanding,
            "commission_level": ceilings.level(outstanding, distributor.credit_ceiling),
            "overdue": statements.overdue_statements(distributor, now),
            "payments": DistribPayment.objects.filter(distributor=distributor)[:10],
        },
    )


@distributor_required
def statement_detail(request, pk: int):
    statement = get_object_or_404(
        DistribStatement.objects.select_related("invite"), pk=pk, distributor=request.distributor
    )
    lines = statement.lines.select_related("imported_product__wholesale_product", "order")
    return render(
        request,
        "distrib/statement_detail.html",
        {"distributor": request.distributor, "statement": statement, "lines": lines,
         "payouts": statement.payouts.order_by("attempt")},
    )


@distributor_required
@require_POST
def statement_pay(request, pk: int):
    # Cloisonnement : uniquement mes propres releves (404 sinon), puis controle du proprietaire.
    statement = get_object_or_404(DistribStatement, pk=pk, distributor=request.distributor)
    try:
        statements.declare_paid(statement, request.user, request.POST.get("om_reference", ""))
    except ValidationError as exc:
        messages.error(request, _text(exc))
    else:
        messages.success(request, "Versement déclaré. Le revendeur a 72 h pour répondre ; sans réponse, il est accepté.")
    return redirect("distrib:statements")


# ── Revendeur ─────────────────────────────────────────────────────────────


@reseller_required
def my_gains(request):
    now = timezone.now()
    invites = list(
        ResellerInvite.objects.filter(seller=request.seller, status__in=("accepted", "revoked")).select_related(
            "distributor"
        )
    )
    blocks = []
    for invite in invites:
        due = ceilings.reseller_due(invite)
        open_lines = [
            {"line": line, "countdown": auto_confirm_info(line, now)}
            for line in DistribSettlement.objects.filter(
                invite=invite, status__in=settlement_service.OPEN_STATUSES
            ).select_related("imported_product__wholesale_product")
        ]
        waiting = DistribSettlement.objects.filter(
            invite=invite, status=DistribSettlement.Status.PAID_CONFIRMED, statement__isnull=True
        ).select_related("imported_product__wholesale_product")
        blocks.append(
            {
                "invite": invite,
                "due": due,
                "level": ceilings.level(due, invite.distributor.reseller_credit_ceiling),
                "ceiling": invite.distributor.reseller_credit_ceiling,
                "open_lines": open_lines,
                "waiting": waiting,
                "statements": invite.statements.prefetch_related("payouts", "lines")[:20],
                "confirmed_lines": DistribSettlement.objects.filter(invite=invite)
                .exclude(customer_confirmed_at=None)
                .select_related("imported_product__wholesale_product")[:10],
            }
        )
    return render(request, "distrib/my_gains.html", {"blocks": blocks})


@reseller_required
@require_POST
def payout_answer(request, pk: int):
    payout = get_object_or_404(ResellerPayout, pk=pk, invite__seller=request.seller)
    decision = request.POST.get("decision")
    if decision not in ("accept", "contest"):
        return redirect("distrib:my_gains")
    try:
        statements.answer_payout(
            payout, request.user, accept=decision == "accept", reason=request.POST.get("reason", "")
        )
    except PermissionDenied:
        raise
    except ValidationError as exc:
        messages.error(request, _text(exc))
    else:
        if decision == "accept":
            messages.success(request, "Merci, versement confirmé.")
        else:
            messages.info(request, "Pas reçu : l'équipe HayaFlash est prévenue. Le montant reste dû.")
    return redirect("distrib:my_gains")
