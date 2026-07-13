"""Service WhatsApp — lien wa.me en V1, WhatsApp Business API en V1.1."""

import logging
import urllib.parse

logger = logging.getLogger(__name__)


def build_whatsapp_order_message(order) -> str:
    """Construit le message de confirmation commande pour WhatsApp."""
    items_text = "\n".join(
        f"  - {item.product_name_snapshot} x{item.quantity} — {int(item.price_snapshot * item.quantity):,} FCFA"
        for item in order.items.all()
    )
    return (
        f"Commande confirmee !\n\n"
        f"Bonjour {order.customer_name},\n\n"
        f"Votre commande a bien ete enregistree :\n"
        f"{items_text}\n\n"
        f"Total : {int(order.total_amount):,} FCFA\n\n"
        f"Paiement a la livraison.\n\n"
        f"Commande via HayaFlash"
    )


def build_whatsapp_share_url(phone: str, message: str) -> str:
    """Retourne un lien wa.me pour envoyer un message WhatsApp."""
    encoded = urllib.parse.quote(message)
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    return f"https://wa.me/{clean_phone}?text={encoded}"
