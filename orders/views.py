from __future__ import annotations

import csv
import time
from collections.abc import Callable

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from accounts.models import SellerProfile
from orders.services.client_order import resolve_client_order_page
from orders.services.dashboard import (
    advance_order_status,
    get_dashboard_kpis_cached,
    get_order_row_context,
    list_dashboard_order_rows,
)

PARTIAL_MIN_INTERVAL_SECONDS = 3.0


@require_GET
def client_order_page(request):
    """Public quick-order page."""
    context = resolve_client_order_page(request)
    return render(request, "orders/client_order.html", context)


def _require_seller(user):
    if not user.is_authenticated:
        return False
    return SellerProfile.objects.filter(user=user, is_active=True).exists()


def _rate_limited_partial_html(
    request,
    *,
    slot: str,
    build_html: Callable[[], str],
) -> HttpResponse:
    uid = request.user.pk
    now = time.time()
    tkey = f"dash:{uid}:t:{slot}"
    hkey = f"dash:{uid}:h:{slot}"
    last = cache.get(tkey)
    if last is not None and (now - float(last)) < PARTIAL_MIN_INTERVAL_SECONDS:
        cached = cache.get(hkey)
        if isinstance(cached, str) and cached:
            return HttpResponse(cached, content_type="text/html; charset=utf-8")
    html = build_html()
    cache.set(tkey, now, 30)
    cache.set(hkey, html, 30)
    return HttpResponse(html, content_type="text/html; charset=utf-8")


@login_required
def seller_dashboard(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")
    from flash_sales.models import FlashSale, FlashSaleStatus
    seller = request.user.seller_profile
    live_sale = (
        FlashSale.objects.filter(owner=seller, status=FlashSaleStatus.LIVE)
        .order_by("-start_time")
        .first()
    )
    next_sale = None
    if not live_sale:
        next_sale = (
            FlashSale.objects.filter(owner=seller, status=FlashSaleStatus.SCHEDULED)
            .order_by("start_time")
            .first()
        )
    return render(request, "orders/dashboard.html", {
        "live_sale": live_sale,
        "next_sale": next_sale,
    })


@login_required
def seller_dashboard_kpi_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    def build() -> str:
        return render_to_string(
            "orders/partials/kpi.html",
            {"kpis": get_dashboard_kpis_cached(request.user)},
            request=request,
        )

    return _rate_limited_partial_html(request, slot="kpi", build_html=build)


@login_required
def seller_dashboard_orders_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    def build() -> str:
        return render_to_string(
            "orders/partials/orders_list.html",
            {"order_rows": list_dashboard_order_rows(request.user)},
            request=request,
        )

    return _rate_limited_partial_html(request, slot="orders", build_html=build)


@login_required
@require_GET
def export_orders_csv(request, pk: int):
    """GET /seller/flash-sales/<pk>/export.csv — téléchargement CSV commandes."""
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    from flash_sales.models import FlashSale
    from orders.models import Order

    seller = request.user.seller_profile
    flash_sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    orders = (
        Order.service_objects
        .filter(flash_sale=flash_sale)
        .prefetch_related("items")
        .order_by("created_at")
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = (
        f'attachment; filename="commandes-{flash_sale.public_slug}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        "#", "Client", "Téléphone", "Produits", "Total FCFA", "Statut", "Heure"
    ])
    for order in orders:
        produits = " | ".join(
            f"{item.product_name_snapshot} x{item.quantity}"
            for item in order.items.all()
        )
        writer.writerow([
            order.pk,
            order.customer_name or "",
            order.customer_phone or "",
            produits,
            int(order.total_amount),
            order.get_status_display(),
            order.created_at.strftime("%H:%M"),
        ])

    return response


@login_required
@require_POST
def seller_order_advance_status(request, order_id: int):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")
    try:
        advance_order_status(user=request.user, order_id=order_id)
    except PermissionDenied:
        return HttpResponseForbidden("Not allowed.")
    except ValidationError as exc:
        msg = "; ".join(getattr(exc, "messages", [])) or str(exc)
        return HttpResponse(msg, status=400)

    row = get_order_row_context(request.user, order_id)
    if row is None:
        return HttpResponseForbidden("Order not found.")
    html = render_to_string(
        "orders/partials/order_row.html",
        {"row": row},
        request=request,
    )
    return HttpResponse(html, content_type="text/html; charset=utf-8")


@login_required
@require_POST
def bulk_confirm_orders(request):
    """POST /seller/orders/bulk-confirm/ — confirme plusieurs commandes en attente."""
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    order_ids = request.POST.getlist("order_ids")
    if not order_ids:
        return HttpResponse("Aucune commande sélectionnée.", status=400)

    from orders.models import Order, OrderStatus
    seller = request.user.seller_profile
    updated = (
        Order.service_objects
        .filter(
            pk__in=order_ids,
            flash_sale__owner=seller,
            status=OrderStatus.PENDING,
        )
        .update(status=OrderStatus.CONFIRMED)
    )

    try:
        from core.models import audit
        audit(
            "orders.bulk_confirmed",
            entity_type="Order",
            entity_id=0,
            request=request,
            count=updated,
            order_ids=[int(i) for i in order_ids],
        )
    except Exception:
        pass

    return HttpResponse(
        f"{updated} commande(s) confirmée(s).",
        content_type="text/plain; charset=utf-8",
    )


@login_required
@require_POST
def bulk_mark_delivered(request):
    """POST /seller/orders/bulk-delivered/ — marque plusieurs commandes livrées."""
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    order_ids = request.POST.getlist("order_ids")
    if not order_ids:
        return HttpResponse("Aucune commande sélectionnée.", status=400)

    from orders.models import Order, OrderStatus
    seller = request.user.seller_profile
    updated = (
        Order.service_objects
        .filter(
            pk__in=order_ids,
            flash_sale__owner=seller,
            status=OrderStatus.CONFIRMED,
        )
        .update(status=OrderStatus.DELIVERED)
    )

    try:
        from core.models import audit
        audit(
            "orders.bulk_delivered",
            entity_type="Order",
            entity_id=0,
            request=request,
            count=updated,
            order_ids=[int(i) for i in order_ids],
        )
    except Exception:
        pass

    return HttpResponse(
        f"{updated} commande(s) marquée(s) livrée(s).",
        content_type="text/plain; charset=utf-8",
    )
