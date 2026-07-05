"""Views pour la gestion des ventes flash (vendeur authentifie)."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import FlashSaleForm
from .models import FlashSale, FlashSaleStatus
from .services.crud import can_seller_create_sale, create_flash_sale, update_flash_sale


def _get_seller(request):
    return request.user.seller_profile


@login_required
def flash_sale_list_view(request):
    seller = _get_seller(request)
    sales = FlashSale.objects.filter(owner=seller).select_related("owner")
    ctx = {
        "sales_scheduled": sales.filter(status=FlashSaleStatus.SCHEDULED),
        "sales_live": sales.filter(status=FlashSaleStatus.LIVE),
        "sales_closed": sales.filter(status__in=[FlashSaleStatus.CLOSED, FlashSaleStatus.EXECUTING]),
        "sales_done": sales.filter(status__in=[FlashSaleStatus.COMPLETED, FlashSaleStatus.CANCELLED]),
    }
    return render(request, "flash_sales/list.html", ctx)


@login_required
def flash_sale_create_view(request):
    seller = _get_seller(request)
    can_create, reason = can_seller_create_sale(seller)
    if not can_create:
        messages.error(request, reason)
        return redirect("flash_sales:list")

    form = FlashSaleForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            sale = create_flash_sale(owner=seller, **form.cleaned_data)
            messages.success(request, f"Vente cree avec succes !")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "flash_sales/create.html", {"form": form})


@login_required
def flash_sale_detail_view(request, pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    products = sale.products.prefetch_related("media").order_by("display_order")
    return render(request, "flash_sales/detail.html", {
        "sale": sale,
        "products": products,
    })


@login_required
def flash_sale_edit_view(request, pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    form = FlashSaleForm(request.POST or None, request.FILES or None, instance=sale)

    if request.method == "POST" and form.is_valid():
        try:
            update_flash_sale(sale=sale, seller=seller, **form.cleaned_data)
            messages.success(request, "Vente mise a jour.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "flash_sales/create.html", {"form": form, "sale": sale})


@login_required
def flash_sale_open_view(request, pk: int):
    if request.method != "POST":
        return redirect("flash_sales:detail", pk=pk)
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    try:
        sale.open_sale()
        messages.success(request, "Vente ouverte ! Les commandes sont acceptees.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("flash_sales:detail", pk=pk)


@login_required
def flash_sale_close_view(request, pk: int):
    if request.method != "POST":
        return redirect("flash_sales:detail", pk=pk)
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    try:
        sale.close_sale()
        messages.success(request, "Vente fermee.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("flash_sales:detail", pk=pk)


@login_required
def flash_sale_cancel_view(request, pk: int):
    if request.method != "POST":
        return redirect("flash_sales:detail", pk=pk)
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    try:
        sale.cancel_sale()
        messages.success(request, "Vente annulee.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("flash_sales:list")
