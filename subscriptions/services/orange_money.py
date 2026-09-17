"""
Client Orange Money Web Payment — Mali
API Reference: https://developer.orange.com/apis/orange-money-webpay-ml
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# URLs Orange Money Mali
OM_TOKEN_URL = "https://api.orange.com/oauth/v3/token"
OM_PAYMENT_URL = "https://api.orange.com/orange-money-webpay/ml/v1/webpayment"
OM_CURRENCY = "XOF"  # Devise Orange Money Mali (FCFA)
OM_LANG = "fr"


class OrangeMoneyError(Exception):
    """Erreur provenant de l'API Orange Money."""


def _get_access_token() -> str:
    """Obtient un Bearer token OAuth2 via client_credentials."""
    client_id = settings.ORANGE_MONEY_CLIENT_ID
    client_secret = settings.ORANGE_MONEY_CLIENT_SECRET
    if not client_id or not client_secret:
        raise OrangeMoneyError(
            "ORANGE_MONEY_CLIENT_ID / ORANGE_MONEY_CLIENT_SECRET manquants."
        )

    resp = requests.post(
        OM_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=15,
    )
    if resp.status_code != 200:
        raise OrangeMoneyError(
            f"Echec obtention token Orange ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()["access_token"]


def _safe_reference(ref: str, max_len: int = 50) -> str:
    """Nettoie la reference : ASCII alphanumerique + espaces + tirets simples uniquement."""
    import unicodedata

    # Normaliser les accents
    nfkd = unicodedata.normalize("NFKD", ref)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    # Garder seulement alphanumerique, espace, tiret, underscore
    cleaned = "".join(c if c.isalnum() or c in " -_" else " " for c in ascii_str)
    # Collaper les espaces multiples et tronquer
    return " ".join(cleaned.split())[:max_len]


def initiate_payment(
    *,
    amount: int,
    order_id: str,
    notif_token: str,
    return_url: str,
    cancel_url: str,
    notif_url: str,
    reference: str = "HayaFlash",
) -> dict[str, Any]:
    """
    Lance un paiement Orange Money.

    Args:
        amount: Montant en XOF (centimes, ex: 2000 = 20 XOF)
        order_id: Identifiant commande unique (max 24 chars)
        notif_token: Token pour lookup webhook (généré côté app, stocké AVANT appel)
        return_url: URL où rediriger après paiement
        cancel_url: URL où rediriger si annulation
        notif_url: URL du webhook pour notification async
        reference: Description pour le relevé bancaire

    Retourne un dict avec:
        - payment_url: URL vers laquelle rediriger le client
        - raw: réponse complete d'Orange Money
    """
    merchant_key = settings.ORANGE_MONEY_MERCHANT_KEY
    if not merchant_key:
        raise OrangeMoneyError("ORANGE_MONEY_MERCHANT_KEY manquant.")

    # Valider order_id ≤ 24 caractères
    if len(order_id) > 24:
        raise OrangeMoneyError(
            f"order_id dépasse 24 chars ({len(order_id)} fournis). "
            f"Orange Money retournera HTTP 400."
        )

    token = _get_access_token()

    payload = {
        "merchant_key": merchant_key,
        "currency": OM_CURRENCY,
        "order_id": order_id,
        "notif_token": notif_token,  # Token pour le webhook
        "amount": amount,
        "return_url": return_url,
        "cancel_url": cancel_url,
        "notif_url": notif_url,
        "lang": OM_LANG,
        "reference": _safe_reference(reference),
    }

    # SSL verification est activée par défaut dans requests
    # (pas de verify=False, crucial pour la sécurité)
    resp = requests.post(
        OM_PAYMENT_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=20,
        verify=True,  # Explicitement activer pour documenter la sécurité
    )

    logger.info(
        "Orange Money initiate — order_id=%s notif_token=%s status=%s",
        order_id,
        notif_token[:16] + "...",
        resp.status_code,
    )

    if resp.status_code not in (200, 201):
        raise OrangeMoneyError(
            f"Initiation paiement echouee ({resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json()
    payment_url = data.get("payment_url") or data.get("paymentUrl") or ""

    if not payment_url:
        raise OrangeMoneyError(f"Pas d'URL de paiement dans la reponse: {data}")

    return {
        "payment_url": payment_url,
        "raw": data,
    }


def verify_callback(callback_data: dict) -> dict[str, Any]:
    """
    Analyse les données de callback Orange Money.

    IMPORTANT: Retourne le notif_token pour lookup sécurisé du paiement.
    Les webhooks DOIVENT faire un lookup par notif_token (pas par order_id)
    pour éviter les injections/spoofing.

    Retourne:
        - success (bool)
        - notif_token (str) — Token pour lookup du paiement (sécurité)
        - order_id (str) — Pour audit seulement (ne pas utiliser pour lookup)
        - status (str) — Statut du paiement
        - txn_id (str) — ID transaction Orange Money
        - phone (str) — Numéro du payeur
    """
    status = (callback_data.get("status") or "").upper()
    notif_token = (
        callback_data.get("notif_token") or callback_data.get("notifToken") or ""
    )
    order_id = callback_data.get("orderId") or callback_data.get("order_id") or ""
    txn_id = callback_data.get("txnid") or callback_data.get("txnId") or ""
    phone = callback_data.get("subscribernumber") or callback_data.get("phone") or ""

    logger.info(
        "Orange Money callback — notif_token=%s status=%s txn_id=%s",
        notif_token[:16] + "..." if notif_token else "MISSING",
        status,
        txn_id,
    )

    return {
        "success": status in ("SUCCESS", "200", "SUCCESSFULL"),
        "notif_token": notif_token,  # Clé primaire pour lookup
        "order_id": order_id,  # Audit seulement
        "status": status,
        "txn_id": txn_id,
        "phone": phone,
        "raw": callback_data,
    }
