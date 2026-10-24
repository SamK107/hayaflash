"""Stock du grossiste (allouer / reprendre) et catalogue cote revendeur (importer)."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .access import distributor_required, reseller_required
from .models import ImportedProduct, ResellerInvite, WholesaleProduct
from .services import allocation, ceilings
from .services.catalog import allocated_total, available_qty


def _text(exc: ValidationError) -> str:
    return " ".join(exc.messages)


# ── Grossiste ─────────────────────────────────────────────────────────────


@distributor_required
def stock(request):
    distributor = request.distributor
    rows = []
    for wp in distributor.wholesale_products.all():
        imports = list(
            wp.imports.select_related("invite", "product").order_by("invite__display_name")
        )
        rows.append(
            {
                "product": wp,
                "allocated": allocated_total(wp),
                "available": available_qty(wp),
                "sold": sum(allocation.sold_qty(i) for i in imports),
                "imports": [
                    {
                        "imported": i,
                        "in_shop": i.product.stock_available,
                        "sold": allocation.sold_qty(i),
                        "below_minimum": i.product.price < wp.min_retail_price,
                        "blocked": ceilings.allocation_block_reason(distributor, i.invite),
                    }
                    for i in imports
                ],
            }
        )
    return render(
        request,
        "distrib/stock.html",
        {
            "distributor": distributor,
            "rows": rows,
            "commission_blocked": ceilings.commission_level(distributor) == ceilings.LEVEL_BLOCKED,
        },
    )


def _stock_action(request, pk: int, action):
    # Cloisonnement : uniquement les produits importes depuis MON catalogue.
    imported = get_object_or_404(
        ImportedProduct, pk=pk, wholesale_product__distributor=request.distributor
    )
    try:
        action(imported=imported, quantity=request.POST.get("quantity", ""), actor=request.user)
    except ValidationError as exc:
        messages.error(request, _text(exc))
    else:
        messages.success(request, "Stock mis à jour.")
    return redirect("distrib:stock")


@distributor_required
@require_POST
def stock_allocate(request, pk: int):
    return _stock_action(request, pk, allocation.allocate)


@distributor_required
@require_POST
def stock_take_back(request, pk: int):
    return _stock_action(request, pk, allocation.take_back)


# ── Revendeur ─────────────────────────────────────────────────────────────


def _my_invite(request, invite_pk: int) -> ResellerInvite:
    return get_object_or_404(
        ResellerInvite.objects.select_related("distributor"),
        pk=invite_pk,
        seller=request.seller,
        status=ResellerInvite.Status.ACCEPTED,
    )


@reseller_required
def reseller_catalog(request, invite_pk: int):
    invite = _my_invite(request, invite_pk)
    imported_by_wp = {
        i.wholesale_product_id: i
        for i in invite.imports.select_related("product")
    }
    items = []
    for wp in invite.distributor.wholesale_products.filter(is_active=True).prefetch_related("images"):
        items.append({"product": wp, "imported": imported_by_wp.get(wp.pk)})
    return render(
        request,
        "distrib/reseller_catalog.html",
        {
            "invite": invite,
            "items": items,
            "suspended": invite.distributor.is_suspended,
            "blocked": ceilings.allocation_block_reason(invite.distributor, invite),
        },
    )


@reseller_required
@require_POST
def reseller_import(request, invite_pk: int, wp_pk: int):
    invite = _my_invite(request, invite_pk)
    # Seul le catalogue du grossiste auquel je suis rattache est importable.
    wp = get_object_or_404(WholesaleProduct, pk=wp_pk, distributor=invite.distributor, is_active=True)
    try:
        allocation.import_product(
            invite=invite,
            wholesale_product=wp,
            retail_price=request.POST.get("retail_price", ""),
            actor=request.user,
        )
    except ValidationError as exc:
        messages.error(request, _text(exc))
    else:
        messages.success(
            request,
            f"« {wp.name} » est dans votre boutique. Le grossiste va maintenant lui allouer du stock.",
        )
    return redirect("distrib:reseller_catalog", invite_pk=invite.pk)
