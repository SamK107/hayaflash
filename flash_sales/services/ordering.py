from __future__ import annotations

from django.core.exceptions import ValidationError

from flash_sales.models import FlashSale, FlashSaleStatus

# Statuts qui autorisent une commande (en plus de la fenetre horaire).
# SCHEDULED reste accepte : si Celery beat est en retard, une vente dont l'heure
# d'ouverture est passee n'a pas encore ete basculee en LIVE mais doit deja
# prendre les commandes. Tout statut de fin (fermee par le vendeur, en
# execution, terminee, annulee) bloque, meme dans la fenetre horaire.
ORDERABLE_STATUSES = frozenset({FlashSaleStatus.LIVE, FlashSaleStatus.SCHEDULED})

MSG_SALE_ENDED = (
    "Cette vente est terminée ou a été annulée : les commandes ne sont plus acceptées."
)
MSG_OUTSIDE_WINDOW = (
    "Cette vente n'est pas ouverte en ce moment : les commandes sont acceptées "
    "uniquement pendant la vente flash."
)


def assert_flash_sale_accepts_orders(flash_sale: FlashSale | None) -> None:
    """
    Autorise la prise de commande : ``flash_sale`` doit exister, avoir un statut
    commandable (LIVE ou SCHEDULED) et ``flash_sale.is_live()`` doit etre vrai
    (fenetre horaire). Point de controle unique pour la page /order/, l'API
    ``POST /api/v1/orders/`` et ``create_order()``.
    """
    if flash_sale is None:
        raise ValidationError(
            {"flash_sale": "Vente introuvable : impossible de passer commande."}
        )
    if flash_sale.status not in ORDERABLE_STATUSES:
        raise ValidationError({"flash_sale": MSG_SALE_ENDED})
    if not flash_sale.is_live():
        raise ValidationError({"flash_sale": MSG_OUTSIDE_WINDOW})
