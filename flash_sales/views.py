"""Views pour la gestion des ventes flash (vendeur authentifie)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.context_processors import request_pwa_install_invite

from .forms import FlashSaleForm
from .models import FlashSale, SaleInterest
from .services.ordering import (
    live_now_q,
    seller_done_q,
    seller_processing_q,
    seller_upcoming_q,
)
from .services.crud import (
    can_seller_create_sale,
    clone_flash_sale,
    create_flash_sale,
    save_sale_audio,
    update_flash_sale,
)
from subscriptions.models import Plan, PLAN_FEATURES, PLAN_PRICES
from subscriptions.services.limits import get_or_create_subscription, get_sale_quota


def _get_seller(request):
    return request.user.seller_profile


@login_required
def flash_sale_list_view(request):
    seller = _get_seller(request)
    sales = FlashSale.objects.filter(owner=seller).select_related("owner")
    # Onglets calcules par l'heure, pas par le statut brut (voir
    # services.ordering, section "Espace vendeur").
    now = timezone.now()
    sales_scheduled = sales.filter(seller_upcoming_q(now)).order_by("start_time")
    sales_live = sales.filter(live_now_q(now)).order_by("end_time")
    sales_closed = sales.filter(seller_processing_q(now)).order_by("-end_time")
    sales_done = sales.filter(seller_done_q()).order_by("-end_time")
    quota = get_sale_quota(seller)
    ctx = {
        "sales_scheduled": sales_scheduled,
        "sales_live": sales_live,
        "sales_closed": sales_closed,
        "sales_done": sales_done,
        "quota": quota,
        "tab_list": [
            ("scheduled", "Programmées", sales_scheduled.count()),
            ("live", "En cours", sales_live.count()),
            ("closed", "Traitement", sales_closed.count()),
            ("done", "Terminées", sales_done.count()),
        ],
        "pro_features": [
            "Ventes flash illimitées chaque mois",
            "Statistiques et analyses avancées",
            "Priorité dans les résultats de recherche",
            "Support vendeur prioritaire",
            "Accès aux fonctionnalités bêta en avant-première",
        ],
    }
    # Onglet ouvert par defaut : "En cours" s'il y a une vente live.
    ctx["default_tab"] = "live" if ctx["tab_list"][1][2] else "scheduled"
    return render(request, "flash_sales/list.html", ctx)


@login_required
def flash_sale_create_view(request):
    seller = _get_seller(request)
    can_create, reason = can_seller_create_sale(seller)
    if not can_create:
        # Render paywall instead of just showing error + redirect
        quota = get_sale_quota(seller)
        sub = get_or_create_subscription(seller)

        # Build plan options with pricing and features
        plans = []
        for plan_key in [Plan.FREE, Plan.MEDIUM, Plan.PRO]:
            plan_info = {
                "key": plan_key,
                "label": dict(Plan.choices)[plan_key],
                "price": PLAN_PRICES[plan_key],
                "features": PLAN_FEATURES[plan_key],
                "is_current": sub.plan == plan_key and not sub.is_expired,
            }
            # Mark MEDIUM/PRO as recommended
            if plan_key == Plan.MEDIUM and not sub.is_paid:
                plan_info["recommended"] = True
            plans.append(plan_info)

        ctx = {
            "quota": quota,
            "plans": plans,
            "current_plan": sub.plan,
            "reason": reason,
        }
        return render(request, "flash_sales/quota_exceeded.html", ctx)

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
                category=data.get("category", ""),
                cover_image=data.get("cover_image"),
                max_orders=data.get("max_orders"),
            )
            audio = request.FILES.get("description_audio")
            if audio:
                save_sale_audio(sale=sale, audio_file=audio)
            messages.success(request, "Vente créée avec succès !")
            # Bandeau "Installez votre espace vendeur" sur la page suivante (1re
            # vente ; relance a la vente suivante si "Plus tard" — plafond cote JS).
            request_pwa_install_invite(request, "seller")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "flash_sales/create.html", {"form": form})


@login_required
def flash_sale_detail_view(request, pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    from products.services.crud import products_for_sale

    products = products_for_sale(sale, only_active=False)
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
                category=data.get("category", ""),
                cover_image=data.get("cover_image"),
                max_orders=data.get("max_orders"),
            )
            messages.success(request, "Vente mise à jour.")
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
        messages.success(request, "Vente ouverte ! Les commandes sont acceptées.")
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
        messages.success(request, "Vente fermée.")
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
        messages.success(request, "Vente annulée.")
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
        request_pwa_install_invite(request, "seller")
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
        # Serialises dans le template via |json_script (CSP : pas de JS inline).
        "timeline": timeline_30d,
        "top_products": get_top_products(seller.pk),
    }

    if sub.is_pro:
        context["timeline_year"] = get_revenue_timeline_monthly(seller.pk)

    return render(request, "flash_sales/analytics_dashboard.html", context)
