"""Confirmation par la cliente (spec §15.3) : pages publiques, sans compte.

- `/distrib/recu/` (POST) : acces 1, le code a 4 chiffres est rendu a la cliente qui vient de commander
  depuis CE telephone (id de commande ET telephone doivent correspondre) et le cookie des recus est pose ;
- `/distrib/bandeau/` : fragment du bandeau discret, lu depuis le cookie, jamais mis en cache ;
- `/distrib/confirmer/` : acces 2, telephone + code a 4 chiffres ;
- `/distrib/recu/<jeton>/` : page de confirmation (lien du bandeau).

Toutes les reponses d'echec sont identiques, que le couple existe ou non.
"""

from __future__ import annotations

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

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
@require_POST
def receipt_hint(request):
    """Acces 1 : renvoie le code a la cliente et pose le cookie `hf_receipts`."""
    order_id = request.POST.get("order_id", "")
    phone = request.POST.get("phone", "")
    if receipts.attempts_exceeded(request, phone):
        return _no_store(JsonResponse({"lines": []}, status=429))
    lines = receipts.open_lines_for_order(order_id, phone)
    response = JsonResponse(
        {"lines": [{"name": line.imported_product.wholesale_product.name, "code": line.receipt_code} for line in lines]}
    )
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
        return _no_store(HttpResponse(status=204))
    # Un seul bandeau : la commande la plus recente.
    return _no_store(render(request, "distrib/_receipt_banner.html", {"line": lines[0]}))


@feature_required
def receipt_lookup(request):
    """Acces 2 : numero + code a 4 chiffres. Reponse neutre si rien ne correspond."""
    form = ReceiptLookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if receipts.attempts_exceeded(request, data["phone_e164"]):
            return _no_store(render(request, "distrib/receipt_lookup.html", {"form": form, "message": TOO_MANY_MESSAGE}, status=429))
        lines = receipts.find_open_lines(data["phone_e164"], data["code"])
        if lines:
            return _no_store(render(request, "distrib/receipt_confirm.html", {"lines": lines, "line": lines[0]}))
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
    response = render(request, "distrib/receipt_done.html", {"result": result, "line": line})
    return _no_store(response)
