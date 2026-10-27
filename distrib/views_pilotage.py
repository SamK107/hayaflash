"""Pilotage HayaFlash (`/distrib/pilotage/`, reserve au staff)."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import staff_required
from .forms import DistributorCreateForm
from .models import DistribCorrection, DistribPayment, Distributor, DistribSettlement, DistribStatement
from .services import ceilings, dashboard, reliability
from .services import settlement as settlement_service
from .services import statements as statement_service
from .services.distributors import create_distributor


def _pilotage_context() -> dict:
    now = timezone.now()
    distributors = Distributor.objects.select_related("user").annotate(
        reseller_count=Count("invites", distinct=True),
        product_count=Count("wholesale_products", distinct=True),
    )
    rows = []
    for d in distributors:
        outstanding = ceilings.commission_outstanding(d)
        rows.append(
            {
                "d": d,
                "outstanding": outstanding,
                "level": ceilings.level(outstanding, d.credit_ceiling),
                "reliability": reliability.reliability(d, now),
            }
        )
    rows.sort(key=lambda r: (-len(r["reliability"]["alerts"]), r["d"].business_name.lower()))
    return {"distributors": distributors, "rows": rows, "totals": dashboard.pilotage_totals(now)}


@staff_required
def pilotage_home(request):
    return render(request, "distrib/pilotage/home.html", _pilotage_context())


@staff_required
def pilotage_fragment(request):
    response = render(request, "distrib/pilotage/_live.html", _pilotage_context())
    response["Cache-Control"] = "private, no-store"
    return response


@staff_required
def pilotage_distributor_create(request):
    form = DistributorCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            distributor, temporary_password = create_distributor(
                phone=data["phone_e164"],
                display_name=data["display_name"],
                business_name=data["business_name"],
                created_by=request.user,
                orange_money_number=data.get("orange_money_e164", ""),
                commission_rate=data["commission_rate"],
                pilot_until=data.get("pilot_until"),
            )
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
        else:
            # Pas de redirection : le mot de passe provisoire n'est montre qu'ici, une seule fois.
            response = render(
                request,
                "distrib/pilotage/distributor_created.html",
                {"distributor": distributor, "temporary_password": temporary_password},
            )
            response["Cache-Control"] = "no-store"
            return response
    return render(request, "distrib/pilotage/distributor_form.html", {"form": form})


@staff_required
def pilotage_signals(request):
    """Signaux pour l'equipe : lignes en conflit et corrections recentes (pas de litige dans l'outil)."""
    conflicts = DistribSettlement.objects.filter(conflict_flag=True).select_related(
        "distributor", "invite", "order"
    )
    corrections = DistribCorrection.objects.select_related("settlement", "author")[:20]
    return render(
        request,
        "distrib/pilotage/signals.html",
        {
            "conflicts": conflicts,
            "corrections": corrections,
            "distributors": Distributor.objects.all(),
            "statements": DistribStatement.objects.filter(
                status__in=(DistribStatement.Status.CONTESTED, DistribStatement.Status.ESCALATED)
            ).select_related("distributor", "invite"),
            "statuses": [(v, label) for v, label in DistribSettlement.Status.choices if v in settlement_service.CORRECTABLE_TO],
        },
    )


@staff_required
@require_POST
def pilotage_correct(request, pk: int):
    line = get_object_or_404(DistribSettlement, pk=pk)
    try:
        settlement_service.staff_correct(
            line, request.user, new_status=request.POST.get("new_status", ""), reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Correction enregistrée et journalisée.")
    return redirect("distrib:pilotage_signals")


@staff_required
@require_POST
def pilotage_payment(request, pk: int):
    """Enregistre un reglement de commission recu de ce grossiste (Orange Money, hors outil)."""
    distributor = get_object_or_404(Distributor, pk=pk)
    raw = (request.POST.get("amount") or "").strip()
    reference = (request.POST.get("reference") or "").strip()[:60]
    if not raw.isdigit() or int(raw) <= 0:
        messages.error(request, "Montant invalide : un nombre entier de FCFA, supérieur à 0.")
    else:
        DistribPayment.objects.create(
            distributor=distributor, amount=int(raw), reference=reference, recorded_by=request.user
        )
        messages.success(request, "Règlement enregistré.")
    return redirect("distrib:pilotage_signals")


def _statement_action(request, pk: int, action):
    statement = get_object_or_404(DistribStatement, pk=pk)
    try:
        action(statement, request.user, request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Action enregistrée et journalisée.")
    return redirect("distrib:pilotage_signals")


@staff_required
@require_POST
def pilotage_statement_close(request, pk: int):
    return _statement_action(request, pk, statement_service.staff_close_escalated)


@staff_required
@require_POST
def pilotage_statement_reopen(request, pk: int):
    return _statement_action(request, pk, statement_service.staff_reopen_escalated)
