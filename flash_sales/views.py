"""Views pour la gestion des ventes flash (vendeur authentifie)."""

from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import FlashSaleForm
from .models import FlashSale, FlashSaleStatus, SaleInterest
from .services.crud import (
    can_seller_create_sale,
    clone_flash_sale,
    create_flash_sale,
    save_sale_audio,
    update_flash_sale,
)
from subscriptions.services.limits import get_or_create_subscription, get_sale_quota


def _get_seller(request):
    return request.user.seller_profile


@login_required
def flash_sale_list_view(request):
    seller = _get_seller(request)
    sales = FlashSale.objects.filter(owner=seller).select_related("owner")
    sales_scheduled = sales.filter(status=FlashSaleStatus.SCHEDULED)
    sales_live = sales.filter(status=FlashSaleStatus.LIVE)
    sales_closed = sales.filter(
        status__in=[FlashSaleStatus.CLOSED, FlashSaleStatus.EXECUTING]
    )
    sales_done = sales.filter(
        status__in=[FlashSaleStatus.COMPLETED, FlashSaleStatus.CANCELLED]
    )
    quota = get_sale_quota(seller)
    ctx = {
        "sales_scheduled": sales_scheduled,
        "sales_live": sales_live,
        "sales_closed": sales_closed,
        "sales_done": sales_done,
        "quota": quota,
        "tab_list": [
            ("scheduled", "Programmees", sales_scheduled.count()),
            ("live", "En cours", sales_live.count()),
            ("closed", "Traitement", sales_closed.count()),
            ("done", "Terminees", sales_done.count()),
        ],
        "pro_features": [
            "Ventes flash illimitees chaque mois",
            "Statistiques et analyses avancees",
            "Priorite dans les resultats de recherche",
            "Support vendeur prioritaire",
            "Acces aux fonctionnalites beta en avant-premiere",
        ],
    }
    return render(request, "flash_sales/list.html", ctx)


@login_required
def flash_sale_create_view(request):
    seller = _get_seller(request)
    can_create, reason = can_seller_create_sale(seller)
    if not can_create:
        messages.error(request, reason)
        return redirect("flash_sales:list")

    form = FlashSaleForm(
        request.POST or None,
        request.FILES or None,
        seller=seller,
    )
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            sale = create_flash_sale(
                owner=seller,
                title=data["title"],
                description=data.get("description", ""),
                start_time=data["start_time"],
                end_time=data["end_time"],
                delivery_zone=data.get("delivery_zone", ""),
                cover_image=data.get("cover_image"),
                max_orders=data.get("max_orders"),
            )
            audio = request.FILES.get("description_audio")
            if audio:
                save_sale_audio(sale=sale, audio_file=audio)
            messages.success(request, "Vente creee avec succes !")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "flash_sales/create.html", {"form": form})


@login_required
def flash_sale_detail_view(request, pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    products = sale.products.prefetch_related("media").order_by("display_order")
    return render(
        request,
        "flash_sales/detail.html",
        {
            "sale": sale,
            "products": products,
        },
    )


@login_required
def flash_sale_edit_view(request, pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    form = FlashSaleForm(
        request.POST or None,
        request.FILES or None,
        instance=sale,
        seller=seller,
        existing_sale_pk=sale.pk,
    )

    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            update_flash_sale(
                sale=sale,
                seller=seller,
                title=data["title"],
                description=data.get("description", ""),
                start_time=data["start_time"],
                end_time=data["end_time"],
                delivery_zone=data.get("delivery_zone", ""),
                cover_image=data.get("cover_image"),
                max_orders=data.get("max_orders"),
            )
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
        try:
            from core.models import audit

            audit(
                "flashsale.opened",
                entity_type="FlashSale",
                entity_id=sale.pk,
                request=request,
                title=sale.title,
            )
        except Exception:
            pass
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
        try:
            from core.models import audit

            audit(
                "flashsale.closed",
                entity_type="FlashSale",
                entity_id=sale.pk,
                request=request,
                title=sale.title,
            )
        except Exception:
            pass
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
        try:
            from core.models import audit

            audit(
                "flashsale.cancelled",
                entity_type="FlashSale",
                entity_id=sale.pk,
                request=request,
                title=sale.title,
            )
        except Exception:
            pass
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("flash_sales:list")


# Clone / Reprendre une vente


@login_required
def flash_sale_clone_view(request, pk: int):
    """Clone une vente et redirige vers l'edition."""
    if request.method != "POST":
        return redirect("flash_sales:detail", pk=pk)
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    try:
        new_sale = clone_flash_sale(sale=sale, seller=seller)
        messages.success(request, "Vente clonee ! Modifiez les dates puis ouvrez-la.")
        return redirect("flash_sales:edit", pk=new_sale.pk)
    except Exception as e:
        messages.error(request, str(e))
        return redirect("flash_sales:detail", pk=pk)


# Reservations d'interet


@login_required
def sale_interests_view(request):
    """Liste des reservations d'interet pour toutes les ventes du vendeur."""
    seller = _get_seller(request)
    sales_with_interests = (
        FlashSale.objects.filter(owner=seller, interests__isnull=False)
        .prefetch_related("interests")
        .distinct()
        .order_by("-start_time")
    )
    total_count = SaleInterest.objects.filter(flash_sale__owner=seller).count()
    ctx = {
        "sales_with_interests": sales_with_interests,
        "total_count": total_count,
    }
    return render(request, "flash_sales/interests.html", ctx)


@login_required
def flash_sale_interests_detail_view(request, pk: int):
    """Reservations d'interet pour une vente specifique."""
    seller = _get_seller(request)
    flash_sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    interests = flash_sale.interests.order_by("-created_at")
    return render(
        request,
        "flash_sales/interests_detail.html",
        {
            "flash_sale": flash_sale,
            "interests": interests,
            "total": interests.count(),
        },
    )


@login_required
def sale_interests_reset_view(request, pk: int):
    """Supprime toutes les reservations d'une vente (POST uniquement)."""
    if request.method != "POST":
        return redirect("flash_sales:interests")
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    deleted_count, _ = SaleInterest.objects.filter(flash_sale=sale).delete()
    messages.success(request, f"{deleted_count} reservation(s) supprimee(s).")
    return redirect("flash_sales:interests")


# Reporting / Analytics (MEDIUM / PRO)


@login_required
def seller_analytics_view(request):
    """Dashboard analytics — MEDIUM (30j) et PRO (annuel + par vente)."""
    from analytics.services.reporting import (
        get_revenue_timeline,
        get_revenue_timeline_monthly,
        get_top_products,
    )
    from orders.services.dashboard import get_dashboard_kpis

    seller = _get_seller(request)
    sub = get_or_create_subscription(seller)

    if not sub.has_stats:
        return render(request, "flash_sales/analytics_upgrade.html", {"sub": sub})

    # get_dashboard_kpis() prend un User (request.user), pas un SellerProfile.
    kpis = get_dashboard_kpis(request.user)

    timeline_30d = get_revenue_timeline(seller.pk, days=30)

    context = {
        "kpis": kpis,
        "sub": sub,
        "is_pro": sub.is_pro,
        "timeline_json": json.dumps(timeline_30d),
        "top_products": get_top_products(seller.pk),
    }

    if sub.is_pro:
        context["timeline_year_json"] = json.dumps(
            get_revenue_timeline_monthly(seller.pk)
        )

    return render(request, "flash_sales/analytics_dashboard.html", context)
