from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.conf import settings
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseRedirect,
)
from django.shortcuts import render
from django.urls import reverse
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST, require_safe

from accounts.access import redirect_without_seller_profile
from accounts.models import SellerProfile
from delivery.models import Delivery
from delivery.services.seller_dashboard import (
    apply_delivery_action_from_form,
    get_delivery_row_context,
    get_delivery_summary,
    list_delivery_rows,
    resolve_delivery_dashboard_page,
)

PARTIAL_MIN_INTERVAL_SECONDS = 3.0

AUDIO_PREFIX = "delivery/audio/"
AUDIO_CONTENT_TYPES = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
}


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
        return HttpResponseBadRequest("Le paramètre flash_sale_id est obligatoire.")
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
        return redirect_without_seller_profile(request)

    flash_sale_id = _parse_flash_sale_id(request)
    status_filter = request.GET.get("status") or "all"

    # Auto-redirect: if no sale selected, pick the seller's most recent one
    if flash_sale_id is None:
        from flash_sales.models import FlashSale

        first = (
            FlashSale.objects.filter(owner__user=request.user)
            .order_by("-created_at")
            .first()
        )
        if first is not None:
            return HttpResponseRedirect(
                f"{request.path}?flash_sale_id={first.pk}&status={status_filter}"
            )

    context = resolve_delivery_dashboard_page(
        user=request.user,
        flash_sale_id=flash_sale_id,
    )
    context["status_filter"] = status_filter
    context["filter_choices"] = [
        ("all", "Toutes"),
        ("pending", "En attente"),
        ("in_transit", "En cours"),
        ("delivered", "Livrées"),
        ("failed", "Échec"),
        ("cancelled", "Annulées"),
    ]
    # Template uses these aliases
    context["current_flash_sale"] = context.get("flash_sale")
    context["flash_sale_choices"] = context.get("flash_sales", [])
    context["current_flash_sale_id"] = flash_sale_id
    context["delivery_select_prefix"] = (
        f"?status={quote(status_filter or '')}&flash_sale_id="
    )
    return render(request, "delivery/deliveries_dashboard.html", context)


@login_required
@require_GET
def seller_deliveries_summary_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Profil vendeur requis.")

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
        return HttpResponseForbidden("Action non autorisée.")


@login_required
@require_GET
def seller_deliveries_list_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Profil vendeur requis.")

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
        return HttpResponseForbidden("Action non autorisée.")


_ACTION_SUCCESS_MESSAGES = {
    "confirm": "Commande confirmée.",
    "start_delivery": "Livraison démarrée.",
    "mark_delivered": "Livraison marquée comme livrée.",
    "mark_failed": "Livraison marquée comme échouée.",
}


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _deliveries_page_url(request, delivery_id: UUID) -> str:
    """Page complete des livraisons (meme vente que la livraison, si elle est au vendeur)."""
    url = reverse("orders:seller_deliveries_dashboard")
    flash_sale_id = (
        Delivery.objects.filter(
            pk=delivery_id, order__flash_sale__owner__user=request.user
        )
        .values_list("order__flash_sale_id", flat=True)
        .first()
    )
    return f"{url}?flash_sale_id={flash_sale_id}" if flash_sale_id else url


def _first_validation_message(exc: ValidationError) -> str:
    msgs = getattr(exc, "message_dict", None)
    if msgs:
        flat: list[str] = []
        for v in msgs.values():
            if isinstance(v, list):
                flat.extend(str(x) for x in v)
            else:
                flat.append(str(v))
        return flat[0] if flat else str(exc)
    return "; ".join(str(m) for m in getattr(exc, "messages", [str(exc)]))


def _safe_audio_name(name: str) -> bool:
    """Nom de fichier sous delivery/audio/, sans remontée de répertoire ni chemin absolu."""
    return (
        bool(name)
        and name.startswith(AUDIO_PREFIX)
        and "\\" not in name
        and ".." not in PurePosixPath(name).parts
    )


@require_safe
def seller_delivery_audio(request, delivery_id: UUID):
    """Note vocale d'un client (E4) : réservée au vendeur propriétaire de la livraison.

    404 pour tous les autres (anonyme, autre vendeur, équipe non propriétaire, livraison inconnue ou sans audio) :
    rien ne révèle l'existence d'une note. En staging et production, le fichier est servi par Nginx (X-Accel-Redirect
    vers la location interne /_protected_media/) ; en développement, par Django (FileResponse).
    """
    if not request.user.is_authenticated:
        raise Http404
    delivery = (
        Delivery.objects.filter(pk=delivery_id, order__flash_sale__owner__user=request.user)
        .exclude(audio_note="")
        .exclude(audio_note__isnull=True)
        .first()
    )
    if delivery is None:
        raise Http404
    name = delivery.audio_note.name
    if not _safe_audio_name(name) or not delivery.audio_note.storage.exists(name):
        raise Http404
    content_type = AUDIO_CONTENT_TYPES.get(PurePosixPath(name).suffix.lower(), "application/octet-stream")
    if settings.PROTECTED_MEDIA_X_ACCEL_REDIRECT:
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = settings.PROTECTED_MEDIA_URL_PREFIX + quote(name)
    else:
        try:
            handle = delivery.audio_note.open("rb")
        except (OSError, ValueError):
            raise Http404 from None
        response = FileResponse(handle, content_type=content_type)
        response["Content-Disposition"] = "inline"  # nom neutre : jamais de nom ni de numéro dans l'en-tête
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def seller_delivery_action(request, delivery_id: UUID):
    """Action sur une livraison.

    Requete HTMX (``HX-Request``) : fragment de la ligne (ou texte d'erreur 400).
    Envoi classique de formulaire : jamais de fragment nu, redirection vers la
    page des livraisons avec un message (succes ou erreur) en francais.
    """
    htmx = _is_htmx(request)
    if not _require_seller(request.user):
        return HttpResponseForbidden("Profil vendeur requis.")

    action = request.POST.get("action")
    if not isinstance(action, str) or not action.strip():
        if htmx:
            return HttpResponseBadRequest("L'action demandée est manquante.")
        messages.error(request, "L'action demandée est manquante.")
        return HttpResponseRedirect(_deliveries_page_url(request, delivery_id))
    action = action.strip()

    try:
        apply_delivery_action_from_form(
            user=request.user,
            delivery_id=delivery_id,
            action=action,
            form_data=request.POST,
        )
    except PermissionDenied:
        return HttpResponseForbidden("Action non autorisée.")
    except ValidationError as exc:
        message = _first_validation_message(exc)
        if htmx:
            return HttpResponse(message, status=400)
        messages.error(request, message)
        return HttpResponseRedirect(_deliveries_page_url(request, delivery_id))

    if not htmx:
        messages.success(
            request, _ACTION_SUCCESS_MESSAGES.get(action, "Livraison mise à jour.")
        )
        return HttpResponseRedirect(_deliveries_page_url(request, delivery_id))

    row = get_delivery_row_context(user=request.user, delivery_id=delivery_id)
    if row is None:
        return HttpResponseForbidden("Livraison introuvable.")
    html = render_to_string(
        "delivery/partials/delivery_row.html",
        {"row": row},
        request=request,
    )
    return HttpResponse(html, content_type="text/html; charset=utf-8")
