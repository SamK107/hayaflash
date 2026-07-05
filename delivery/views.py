from __future__ import annotations

import time
from collections.abc import Callable
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from accounts.models import SellerProfile
from delivery.services.seller_dashboard import (
    apply_delivery_action_from_form,
    get_delivery_row_context,
    get_delivery_summary,
    list_delivery_rows,
    resolve_delivery_dashboard_page,
)

PARTIAL_MIN_INTERVAL_SECONDS = 3.0


def _require_seller(user) -> bool:
    if not user.is_authenticated:
        return False
    return SellerProfile.objects.filter(user=user, is_active=True).exists()


def _parse_flash_sale_id(request) -> int | None:
    raw = request.GET.get("flash_sale_id")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _require_flash_sale_id(request) -> int | HttpResponseBadRequest:
    flash_sale_id = _parse_flash_sale_id(request)
    if flash_sale_id is None:
        return HttpResponseBadRequest("flash_sale_id query parameter is required.")
    return flash_sale_id


def _rate_limited_partial_html(
    request,
    *,
    slot: str,
    build_html: Callable[[], str],
) -> HttpResponse:
    uid = request.user.pk
    now = time.time()
    tkey = f"dl:{uid}:t:{slot}"
    hkey = f"dl:{uid}:h:{slot}"
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
@require_GET
def seller_deliveries_dashboard(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    flash_sale_id = _parse_flash_sale_id(request)
    status_filter = request.GET.get("status") or "all"
    context = resolve_delivery_dashboard_page(
        user=request.user,
        flash_sale_id=flash_sale_id,
    )
    context["status_filter"] = status_filter
    context["filter_choices"] = [
        ("all", "Toutes"),
        ("pending", "En attente"),
        ("in_transit", "En cours"),
        ("delivered", "Livrees"),
        ("failed", "Echecs"),
    ]
    # Template uses these aliases
    context["current_flash_sale"] = context.get("flash_sale")
    context["flash_sale_choices"] = context.get("flash_sales", [])
    context["current_flash_sale_id"] = flash_sale_id
    return render(request, "delivery/deliveries_dashboard.html", context)


@login_required
@require_GET
def seller_deliveries_summary_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    flash_sale_id = _require_flash_sale_id(request)
    if isinstance(flash_sale_id, HttpResponseBadRequest):
        return flash_sale_id

    def build() -> str:
        summary = get_delivery_summary(
            user=request.user,
            flash_sale_id=flash_sale_id,
        )
        return render_to_string(
            "delivery/partials/delivery_summary.html",
            {"summary": summary},
            request=request,
        )

    slot = f"summary:{flash_sale_id}"
    try:
        return _rate_limited_partial_html(request, slot=slot, build_html=build)
    except PermissionDenied:
        return HttpResponseForbidden("Not allowed.")


@login_required
@require_GET
def seller_deliveries_list_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    flash_sale_id = _require_flash_sale_id(request)
    if isinstance(flash_sale_id, HttpResponseBadRequest):
        return flash_sale_id

    status_filter = request.GET.get("status") or "all"

    def build() -> str:
        rows = list_delivery_rows(
            user=request.user,
            flash_sale_id=flash_sale_id,
            status_filter=status_filter,
        )
        return render_to_string(
            "delivery/partials/delivery_list.html",
            {"delivery_rows": rows},
            request=request,
        )

    slot = f"list:{flash_sale_id}:{status_filter}"
    try:
        return _rate_limited_partial_html(request, slot=slot, build_html=build)
    except PermissionDenied:
        return HttpResponseForbidden("Not allowed.")


@login_required
@require_POST
def seller_delivery_action(request, delivery_id: UUID):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    action = request.POST.get("action")
    if not isinstance(action, str) or not action.strip():
        return HttpResponseBadRequest("action is required.")

    try:
        apply_delivery_action_from_form(
            user=request.user,
            delivery_id=delivery_id,
            action=action.strip(),
            form_data=request.POST,
        )
    except PermissionDenied:
        return HttpResponseForbidden("Not allowed.")
    except ValidationError as exc:
        msgs = getattr(exc, "message_dict", None)
        if msgs:
            flat = []
            for v in msgs.values():
                if isinstance(v, list):
                    flat.extend(str(x) for x in v)
                else:
                    flat.append(str(v))
            return HttpResponse(flat[0] if flat else str(exc), status=400)
        return HttpResponse(str(exc), status=400)

    row = get_delivery_row_context(user=request.user, delivery_id=delivery_id)
    if row is None:
        return HttpResponseForbidden("Delivery not found.")
    html = render_to_string(
        "delivery/partials/delivery_row.html",
        {"row": row},
        request=request,
    )
    return HttpResponse(html, content_type="text/html; charset=utf-8")
