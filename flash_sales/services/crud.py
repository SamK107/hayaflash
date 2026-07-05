"""Services CRUD pour les ventes flash (vendeur authentifie)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from flash_sales.models import FlashSale, FlashSaleStatus


def create_flash_sale(
    *,
    owner,
    title: str,
    description: str = "",
    start_time,
    end_time,
    delivery_zone: str = "",
    cover_image=None,
    max_orders: int | None = None,
) -> FlashSale:
    """Cree une nouvelle vente flash pour un vendeur."""
    if end_time <= start_time:
        raise ValidationError("La date de fin doit etre apres la date de debut.")
    if start_time < timezone.now():
        raise ValidationError("La date de debut ne peut pas etre dans le passe.")

    sale = FlashSale(
        owner=owner,
        title=title.strip(),
        description=description.strip() if description else "",
        start_time=start_time,
        end_time=end_time,
        delivery_zone=delivery_zone.strip() if delivery_zone else "",
        max_orders=max_orders,
        status=FlashSaleStatus.SCHEDULED,
    )
    if cover_image:
        sale.cover_image = cover_image
    sale.full_clean()
    sale.save()
    return sale


def update_flash_sale(*, sale: FlashSale, seller, **kwargs) -> FlashSale:
    """Met a jour une vente (seulement si scheduled)."""
    if sale.owner != seller:
        raise PermissionDenied("Cette vente ne vous appartient pas.")
    if sale.status not in (FlashSaleStatus.SCHEDULED,):
        raise ValidationError("Une vente en cours ou terminee ne peut plus etre modifiee.")

    allowed = {"title", "description", "start_time", "end_time", "delivery_zone", "cover_image", "max_orders"}
    for key, value in kwargs.items():
        if key in allowed:
            setattr(sale, key, value)

    sale.full_clean()
    sale.save()
    return sale


def can_seller_create_sale(seller) -> tuple[bool, str]:
    """Verifie les limites du plan abonnement du vendeur."""
    try:
        from subscriptions.services.limits import can_create_flash_sale
        return can_create_flash_sale(seller)
    except Exception:
        return True, ""  # Fail open si subscriptions non disponible
