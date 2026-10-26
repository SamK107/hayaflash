"""Confirmation par la cliente (spec §15.3) : pages publiques, sans compte.

- `/distrib/recu/` (POST) : acces 1, le code a 4 chiffres est rendu a la cliente qui vient de commander
  depuis CE telephone (id de commande ET telephone doivent correspondre) et le cookie des recus est pose ;
- `/distrib/bandeau/` : fragment du bandeau discret, lu depuis le cookie, jamais mis en cache ;
- `/distrib/confirmer/` : acces 2, telephone + code a 4 chiffres ;
- `/distrib/recu/<jeton>/` : page de confirmation (lien du bandeau).

Toutes les reponses d'echec sont identiques, que le couple existe ou non.
"""

from __future__ import annotations

from django.middleware.csrf import get_token
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from core.services import rate_limit
from core.services.client_ip import get_client_ip

from .access import feature_required
from .forms import ReceiptLookupForm
from .services import receipts

NEUTRAL_MESSAGE = "Aucune commande en attente ne correspond à ces informations."
TOO_MANY_MESSAGE = "Trop d'essais. Réessayez dans une heure."


def _no_store(response):
    response["Cache-Control"] = "private, no-store"
    response["Vary"] = "Cookie"
    return response


@feature_required
@require_GET
@never_cache
def receipt_csrf(request):
    """Jeton CSRF pour `receipt.js` : la page publique d'une vente est servie en cache, sans jeton ni cookie.

    Un jeton CSRF n'a rien de secret (toute page Django en emet un) ; la limite par IP evite seulement
    qu'on martele la route. Une visiteuse a deja le cookie apres le 1er appel : un appel par commande au plus."""
    if rate_limit.hit(
        f"distrib_csrf:ip:{rate_limit.ip_fingerprint(get_client_ip(request))}",
        limit=receipts.CSRF_TOKENS_PER_WINDOW, window_seconds=receipts.CSRF_WINDOW_SECONDS,
    ):
        return _no_store(JsonResponse({"csrf": ""}, status=429))
    return _no_store(JsonResponse({"csrf": get_token(request)}))


@feature_required
@require_POST
def receipt_hint(request):
    """Acces 1 : renvoie le code a la cliente et pose le cookie `hf_receipts`.

    Seul un couple (commande, telephone) qui ne correspond a rien compte comme un echec ; la cliente qui
    commande n'use jamais son quota, meme pour une commande sans produit importe.
    """
    order_id = request.POST.get("order_id", "")
    phone = request.POST.get("phone", "")
    if receipts.is_blocked(request, phone):
        return _no_store(JsonResponse({"lines": [], "blocked": True}, status=429))
    order = receipts.order_for_phone(order_id, phone)
    if order is None:
        receipts.record_failure(request, phone)
        return _no_store(JsonResponse({"lines": []}))
    lines = receipts.open_lines_for_order(order_id, phone)
    payload = {"lines": [{"name": line.imported_product.wholesale_product.name, "code": line.receipt_code} for line in lines]}
    if not lines and receipts.line_is_pending_creation(order):
        payload["retry"] = True  # creation differee de la ligne : le script peut reessayer
    response = JsonResponse(payload)
    if lines:
        value = receipts.merge_cookie(
            request.COOKIES.get(receipts.COOKIE_NAME), [line.receipt_token for line in lines]
        )
        receipts.set_receipt_cookies(response, request, value)
    return _no_store(response)


@feature_required
@require_GET
@never_cache
def receipt_banner(request):
    """Fragment du bandeau discret ; vide (204) s'il n'y a rien a confirmer."""
    tokens = receipts.tokens_from_cookie(request.COOKIES.get(receipts.COOKIE_NAME))
    lines = receipts.open_lines_for_tokens(tokens)
    if not lines:
        response = _no_store(HttpResponse(status=204))
        receipts.sync_cookies(response, request)
        return response
    # Un seul bandeau : la commande la plus recente.
    return _no_store(render(request, "distrib/_receipt_banner.html", {"line": lines[0]}))


@feature_required
def receipt_lookup(request):
    """Acces 2 : numero + code a 4 chiffres. Reponse neutre si rien ne correspond."""
    form = ReceiptLookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if receipts.is_blocked(request, data["phone_e164"]):
            return _no_store(render(request, "distrib/receipt_lookup.html", {"form": form, "message": TOO_MANY_MESSAGE}, status=429))
        lines = receipts.find_open_lines(data["phone_e164"], data["code"])
        if lines:
            return _no_store(render(request, "distrib/receipt_confirm.html", {"lines": lines, "line": lines[0]}))
        receipts.record_failure(request, data["phone_e164"])
        return _no_store(render(request, "distrib/receipt_lookup.html", {"form": form, "message": NEUTRAL_MESSAGE}))
    return _no_store(render(request, "distrib/receipt_lookup.html", {"form": form}))


@feature_required
@require_GET
def receipt_page(request, token: str):
    """Page ouverte par le bandeau : la cliente confirme depuis son telephone."""
    lines = [
        line for line in receipts.open_lines_for_tokens(
            receipts.tokens_from_cookie(request.COOKIES.get(receipts.COOKIE_NAME))
        )
        if line.receipt_token == token
    ]
    if not lines:
        return _no_store(render(request, "distrib/receipt_done.html", {"result": "closed"}))
    return _no_store(render(request, "distrib/receipt_confirm.html", {"lines": lines, "line": lines[0]}))


@feature_required
@require_POST
def receipt_validate(request):
    """« J'ai recu ma commande » (+ reference Orange Money facultative)."""
    token = request.POST.get("token", "")
    # Le jeton est long et non devinable : pas de compteur ici (il doublerait celui de la recherche).
    line, result = receipts.customer_confirm(token, request.POST.get("om_reference", ""))
    response = _no_store(render(request, "distrib/receipt_done.html", {"result": result, "line": line}))
    receipts.sync_cookies(response, request)
    return response
