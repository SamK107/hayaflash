"""Commandes suivies du grossiste : « Livré et payé » et « Pas livré » (spec §15.1, §15.2).

Cloisonnement : uniquement les lignes portant sur SES produits importes ; jamais le code a
4 chiffres de la cliente, jamais les autres produits ni les autres clientes du revendeur.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import distributor_required
from .models import DistribSettlement
from .services import settlement as settlement_service

S = DistribSettlement.Status

STATUS_FILTERS = [("", "Toutes")] + [
    (S.ORDERED, "Commandées"),
    (S.IN_DELIVERY, "En livraison"),
    (S.DELIVERED_BY_SHOP, "Livrées"),
    (S.PAID_CONFIRMED, "Livrées et payées"),
    (S.NOT_DELIVERED, "Pas livrées"),
    (S.CANCELLED, "Annulées"),
]


def _text(exc: ValidationError) -> str:
    return " ".join(exc.messages)


def auto_confirm_info(line: DistribSettlement, now) -> dict:
    """Compte a rebours visible des trois parties (§15.1)."""
    if line.status not in settlement_service.OPEN_STATUSES:
        return {"kind": "none"}
    if line.auto_confirm_at is None:
        return {"kind": "waiting"}  # « Démarre à la confirmation »
    seconds = (line.auto_confirm_at - now).total_seconds()
    return {"kind": "running", "hours": max(0, int(seconds // 3600) + (1 if seconds % 3600 else 0))}


def _line(request, pk: int) -> DistribSettlement:
    return get_object_or_404(
        DistribSettlement.objects.select_related("distributor__user"), pk=pk, distributor=request.distributor
    )


@distributor_required
def orders_list(request):
    distributor = request.distributor
    status = request.GET.get("statut", "")
    invite_id = request.GET.get("revendeur", "")
    lines = DistribSettlement.objects.filter(distributor=distributor).select_related(
        "invite", "order", "order__delivery", "imported_product__wholesale_product"
    )
    if status in {value for value, _ in DistribSettlement.Status.choices}:
        lines = lines.filter(status=status)
    if invite_id.isdigit():
        lines = lines.filter(invite_id=int(invite_id))
    now = timezone.now()
    rows = []
    for line in lines[:100]:
        delivery = getattr(line.order, "delivery", None)
        rows.append(
            {
                "line": line,
                "countdown": auto_confirm_info(line, now),
                "address": delivery.address_text if delivery else "",
                "can_act": line.status in settlement_service.OPEN_STATUSES,
            }
        )
    return render(
        request,
        "distrib/orders.html",
        {
            "distributor": distributor,
            "rows": rows,
            "status": status,
            "invite_id": invite_id,
            "status_filters": STATUS_FILTERS,
            "invites": distributor.invites.all(),
            "reasons": DistribSettlement.NotDeliveredReason.choices,
        },
    )


@distributor_required
@require_POST
def order_confirm(request, pk: int):
    line = _line(request, pk)
    try:
        _, changed = settlement_service.distributor_confirm(line, request.user)
    except ValidationError as exc:
        messages.error(request, _text(exc))
    else:
        messages.success(request, "Livraison confirmée." if changed else "Déjà confirmée.")
    return redirect("distrib:orders")


@distributor_required
@require_POST
def order_not_delivered(request, pk: int):
    line = _line(request, pk)
    try:
        settlement_service.declare_not_delivered(
            line, request.user, reason=request.POST.get("reason", ""), note=request.POST.get("note", "")
        )
    except ValidationError as exc:
        messages.error(request, _text(exc))
    else:
        messages.success(request, "« Pas livré » enregistré. La commande de la boutique n'est pas modifiée.")
    return redirect("distrib:orders")
