from __future__ import annotations

import json

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from analytics.services.abuse import normalize_tracking_source
from analytics.services.public_pages import (
    resolve_flash_sale_public_page,
    resolve_seller_public_page,
)
from analytics.services.seo import build_flash_sale_seo, build_seller_seo
from analytics.services.share_links import validate_whatsapp_redirect_target
from analytics.services.share_tracking import record_whatsapp_share
from analytics.services.view_tracking import record_page_view, resolve_share_link_by_token


def _apply_public_cache_headers(response: HttpResponse, *, etag: str | None) -> HttpResponse:
    response["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    if etag:
        response["ETag"] = f'"{etag}"'
    return response


def _client_accepts_etag(request, etag: str) -> bool:
    if_none_match = request.META.get("HTTP_IF_NONE_MATCH", "")
    return etag and if_none_match.strip('"') == etag


@require_GET
def seller_public_page(request, slug: str):
    context = resolve_seller_public_page(request, slug)
    if context.get("not_found"):
        raise Http404("Seller not found.")

    source = normalize_tracking_source(request.GET.get("src"))
    share_link = context.get("share_link")
    if share_link is not None:
        record_page_view(request, share_link=share_link, source=source)

    context["seo"] = build_seller_seo(request, context)
    etag = context.get("page_etag")
    if _client_accepts_etag(request, etag):
        response = HttpResponse(status=304)
        return _apply_public_cache_headers(response, etag=etag)

    response = render(request, "analytics/seller_public.html", context)
    return _apply_public_cache_headers(response, etag=etag)


@require_GET
def flash_sale_public_page(request, slug: str):
    context = resolve_flash_sale_public_page(request, slug)
    if context.get("not_found"):
        raise Http404("Flash sale not found.")

    source = normalize_tracking_source(request.GET.get("src"))
    share_link = context.get("share_link")
    if share_link is not None:
        record_page_view(request, share_link=share_link, source=source)

    context["seo"] = build_flash_sale_seo(request, context)
    etag = context.get("page_etag")
    if _client_accepts_etag(request, etag):
        response = HttpResponse(status=304)
        return _apply_public_cache_headers(response, etag=etag)

    response = render(request, "analytics/flash_sale_public.html", context)
    return _apply_public_cache_headers(response, etag=etag)


@require_GET
def track_whatsapp_share(request):
    """Secure tracked redirect to WhatsApp (mobile + desktop targets)."""
    token = (request.GET.get("ref") or "").strip()
    target = (request.GET.get("to") or "").strip()
    source = normalize_tracking_source(request.GET.get("src") or "whatsapp")

    if not validate_whatsapp_redirect_target(target):
        raise Http404("Invalid redirect target.")

    link = resolve_share_link_by_token(token)
    if link is not None:
        record_whatsapp_share(request, share_link=link, source=source)

    return HttpResponse(status=302, headers={"Location": target})


@require_POST
def flash_sale_interest(request, slug: str):
    """
    POST /f/<slug>/interest/
    Body JSON: { phone, name? }
    Enregistre une réservation d'intérêt pour la prochaine vente du vendeur.
    """
    from flash_sales.models import FlashSale, SaleInterest

    flash_sale = get_object_or_404(FlashSale, public_slug=slug)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON invalide."}, status=400)

    phone = (data.get("phone") or "").strip()
    name = (data.get("name") or "").strip()

    if not phone:
        return JsonResponse({"error": "Le téléphone est obligatoire."}, status=400)

    interest = SaleInterest.objects.create(
        flash_sale=flash_sale,
        phone=phone,
        name=name,
    )

    return JsonResponse({"id": interest.pk, "status": "ok"}, status=201)
