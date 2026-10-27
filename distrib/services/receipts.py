"""Confirmation par la cliente (spec §15.3) : facultative, sans aucune action du revendeur.

Le verrou reste la presomption de 72 h (§15.1) : ici la cliente peut seulement CONFIRMER plus tot
(ou signaler un conflit si le grossiste a declare « Pas livre »). Le code a 4 chiffres n'est
montre qu'a la cliente, jamais dans l'espace revendeur ni grossiste.
"""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from core.services import rate_limit
from core.services.client_ip import get_client_ip
from distrib.models import DistribSettlement, ImportedProduct
from distrib.services import settlement as settlement_service
from distrib.services.settlement import CUSTOMER_OPEN_STATUSES, raise_signal
from orders.models import Order, OrderStatus

S = DistribSettlement.Status

COOKIE_NAME = "hf_receipts"
COOKIE_FLAG_NAME = "hf_rc"  # drapeau sans donnee : evite un appel reseau aux visiteurs sans commande Distrib
COOKIE_MAX_AGE = 30 * 24 * 3600
MAX_TOKENS_IN_COOKIE = 5

# Seuls les ECHECS comptent (aucune ligne trouvee) : une cliente honnete qui commande puis confirme
# ne consomme rien. Par numero : 5 echecs/heure (un code a 4 chiffres reste hors de portee) ; par IP :
# plus large, car plusieurs clientes partagent parfois la meme IP mobile (CGNAT).
FAILURES_PER_HOUR_PER_PHONE = 5
FAILURES_PER_HOUR_PER_IP = 20
WINDOW_SECONDS = 3600

# /distrib/jeton/ : 60 jetons / 10 min / IP (largement au-dessus d'un usage normal, meme derriere un CGNAT).
CSRF_TOKENS_PER_WINDOW = 60
CSRF_WINDOW_SECONDS = 600

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_OM_CLEAN_RE = re.compile(r"[^A-Za-z0-9]")
OM_MAX_LENGTH = 30


# ── Numeros, references ───────────────────────────────────────────────────


def phone_key8(phone: str | None) -> str:
    """8 derniers chiffres (meme cle que `orders.services.unhonored`) ; vide si trop court."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-8:] if len(digits) >= 8 else ""


def clean_om_reference(raw: str | None) -> str:
    """Reference Orange Money facultative : chiffres et lettres seulement, longueur bornee."""
    return _OM_CLEAN_RE.sub("", raw or "")[:OM_MAX_LENGTH]


def clean_code(raw: str | None) -> str:
    code = re.sub(r"\s", "", raw or "")
    return code if re.fullmatch(r"\d{4}", code) else ""


# ── Limites de debit (echecs seulement, par numero et par IP) ─────────────


def _rate_keys(request, phone: str | None) -> list[tuple[str, int]]:
    keys = [(f"distrib_receipt:ip:{rate_limit.ip_fingerprint(get_client_ip(request))}", FAILURES_PER_HOUR_PER_IP)]
    key = phone_key8(phone)
    if key:
        keys.append((rate_limit.phone_key("distrib_receipt", key), FAILURES_PER_HOUR_PER_PHONE))
    return keys


def is_blocked(request, phone: str | None) -> bool:
    """Lecture seule : True si l'IP OU le numero a deja atteint son quota d'echecs de l'heure."""
    return any(rate_limit.is_limited(key, limit=limit) for key, limit in _rate_keys(request, phone))


def record_failure(request, phone: str | None) -> None:
    """Compte UN echec (aucune ligne ne correspond). Les reussites ne comptent jamais."""
    for key, limit in _rate_keys(request, phone):
        rate_limit.hit(key, limit=limit, window_seconds=WINDOW_SECONDS)


# ── Cookie des recus ──────────────────────────────────────────────────────


def tokens_from_cookie(value: str | None) -> list[str]:
    return [t for t in (value or "").split(".") if _TOKEN_RE.match(t)][:MAX_TOKENS_IN_COOKIE]


def merge_cookie(existing: str | None, new_tokens: list[str]) -> str:
    """Jetons uniquement, aucune donnee personnelle ; les plus recents d'abord, 5 au plus."""
    merged: list[str] = []
    for token in list(new_tokens) + tokens_from_cookie(existing):
        if token not in merged:
            merged.append(token)
    return ".".join(merged[:MAX_TOKENS_IN_COOKIE])


def set_receipt_cookies(response, request, value: str) -> None:
    secure = request.is_secure()
    response.set_cookie(
        COOKIE_NAME, value, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax", secure=secure
    )
    # Drapeau lisible par le JS : « il y a peut-etre un recu », rien d'autre.
    response.set_cookie(COOKIE_FLAG_NAME, "1", max_age=COOKIE_MAX_AGE, httponly=False, samesite="Lax", secure=secure)


def sync_cookies(response, request) -> None:
    """Efface les cookies quand plus aucun recu n'est ouvert : plus d'appel /distrib/bandeau/ inutile."""
    tokens = tokens_from_cookie(request.COOKIES.get(COOKIE_NAME))
    if open_lines_for_tokens(tokens):
        return
    for name in (COOKIE_NAME, COOKIE_FLAG_NAME):
        if name in request.COOKIES:
            response.delete_cookie(name, path="/", samesite="Lax")


# ── Recherche ─────────────────────────────────────────────────────────────


def open_lines_for_order(order_id, phone: str) -> list[DistribSettlement]:
    """Lignes Distrib ouvertes d'une commande SI le telephone saisi est celui de la commande."""
    key = phone_key8(phone)
    if not key:
        return []
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return []
    lines = DistribSettlement.objects.filter(order_id=order_id, status__in=CUSTOMER_OPEN_STATUSES).select_related(
        "order", "imported_product__wholesale_product"
    )
    return [line for line in lines if phone_key8(line.order.customer_phone) == key and line.receipt_code]


def order_for_phone(order_id, phone: str):
    """La commande SI le telephone saisi est celui de la commande, sinon None (meme reponse dans les deux cas)."""
    key = phone_key8(phone)
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return None
    if not key:
        return None
    order = Order.service_objects.filter(pk=order_id).first()
    if order is None or phone_key8(order.customer_phone) != key:
        return None
    return order


def line_is_pending_creation(order) -> bool:
    """Commande contenant un produit importe dont la ligne de suivi n'existe pas encore (creation differee)."""
    has_imported = ImportedProduct.objects.filter(product__order_items__order=order).exists()
    return has_imported and not DistribSettlement.objects.filter(order=order).exists()


def find_open_lines(phone: str, code: str) -> list[DistribSettlement]:
    """Lignes ouvertes dont le code ET le telephone correspondent (aucune difference visible si non)."""
    key = phone_key8(phone)
    code = clean_code(code)
    if not key or not code:
        return []
    lines = DistribSettlement.objects.filter(
        receipt_code=code, status__in=CUSTOMER_OPEN_STATUSES, customer_confirmed_at__isnull=True
    ).select_related("order", "imported_product__wholesale_product")
    return [line for line in lines if phone_key8(line.order.customer_phone) == key]


def open_lines_for_tokens(tokens: list[str]) -> list[DistribSettlement]:
    if not tokens:
        return []
    return list(
        DistribSettlement.objects.filter(
            receipt_token__in=tokens, status__in=CUSTOMER_OPEN_STATUSES, customer_confirmed_at__isnull=True
        )
        .select_related("imported_product__wholesale_product")
        .order_by("-created_at")
    )


# ── Confirmation ──────────────────────────────────────────────────────────


def customer_confirm(token: str, om_reference: str = "") -> tuple[DistribSettlement | None, str]:
    """« J'ai recu ma commande ». Retourne `(ligne, resultat)` :

    - `confirmed` : ligne passee a `paid_confirmed` (source `customer`) ;
    - `conflict`  : ligne declaree « Pas livre » par le grossiste : AUCUN changement de statut,
                    `conflict_flag` + signal au pilotage uniquement ;
    - `recorded`  : deja confirmee, la reference est simplement enregistree ;
    - `already` / `closed` : sans effet (double confirmation, commande annulee, jeton inconnu).
    Le code a 4 chiffres est invalide des la premiere confirmation.
    """
    if not _TOKEN_RE.match(token or ""):
        return None, "closed"
    om = clean_om_reference(om_reference)
    now = timezone.now()
    with transaction.atomic():
        line = (
            DistribSettlement.objects.select_for_update()
            .select_related("distributor", "order", "imported_product__wholesale_product")
            .filter(receipt_token=token)
            .first()
        )
        if line is None:
            return None, "closed"
        if line.customer_confirmed_at is not None:
            return line, "already"
        if line.status == S.CANCELLED or line.order.status == OrderStatus.CANCELLED:
            return line, "closed"
        if line.status == S.NOT_DELIVERED:
            result = "conflict"
            line.conflict_flag = True
        elif line.status == S.PAID_CONFIRMED:
            result = "recorded"
        else:
            settlement_service._mark_paid(
                line, source=DistribSettlement.ConfirmationSource.CUSTOMER, by=None, at=now
            )
            result = "confirmed"
        line.customer_confirmed_at = now
        line.customer_om_reference = om
        line.receipt_code = ""  # code invalide apres confirmation
        line.save()
        if result == "conflict":
            raise_signal(line, "customer_confirmed_not_delivered")
    return line, result

