"""Services CRUD pour les ventes flash (vendeur authentifie)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from flash_sales.models import FlashSale, FlashSaleStatus

logger = logging.getLogger(__name__)


def create_flash_sale(
    *,
    owner,
    title: str,
    description: str = "",
    start_time,
    end_time,
    delivery_zone: str = "",
    category: str = "",
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
        category=category or "",
        max_orders=max_orders,
        status=FlashSaleStatus.SCHEDULED,
    )
    if cover_image:
        sale.cover_image = cover_image
    sale.full_clean()
    sale.save()
    return sale


def save_sale_audio(*, sale: FlashSale, audio_file) -> FlashSale:
    """Attache un fichier audio de description a une vente."""
    sale.description_audio = audio_file
    sale.save(update_fields=["description_audio"])
    return sale


def update_flash_sale(*, sale: FlashSale, seller, **kwargs) -> FlashSale:
    """Met a jour une vente (seulement si scheduled)."""
    if sale.owner != seller:
        raise PermissionDenied("Cette vente ne vous appartient pas.")
    if sale.status not in (FlashSaleStatus.SCHEDULED,):
        raise ValidationError(
            "Une vente en cours ou terminee ne peut plus etre modifiee."
        )

    allowed = {
        "title",
        "description",
        "start_time",
        "end_time",
        "delivery_zone",
        "category",
        "cover_image",
        "max_orders",
    }
    for key, value in kwargs.items():
        if key in allowed:
            setattr(sale, key, value)

    sale.full_clean()
    sale.save()
    return sale


def clone_flash_sale(*, sale: FlashSale, seller) -> FlashSale:
    """Clone une vente et ses produits (sans commandes ni stock consomme).

    La nouvelle vente est SCHEDULED avec des dates provisoires (J+1).
    Le vendeur doit editer les dates avant d'ouvrir.
    """
    if sale.owner != seller:
        raise PermissionDenied("Cette vente ne vous appartient pas.")

    now = timezone.now()
    new_start = now + timedelta(days=1)
    new_end = now + timedelta(days=1, hours=2)

    new_sale = FlashSale(
        owner=seller,
        title=f"Copie de {sale.title}",
        description=sale.description,
        delivery_zone=sale.delivery_zone,
        category=sale.category,
        max_orders=sale.max_orders,
        start_time=new_start,
        end_time=new_end,
        status=FlashSaleStatus.SCHEDULED,
    )
    # Reutilise la meme image de couverture (pas de copie physique du fichier)
    if sale.cover_image:
        new_sale.cover_image = sale.cover_image.name
    if sale.description_audio:
        new_sale.description_audio = sale.description_audio.name
    new_sale.save()

    # Relier la nouvelle vente aux MEMES produits du catalogue (le catalogue
    # est desormais reutilisable entre ventes : plus de duplication de
    # Product/ProductMedia ici, seulement le lien FlashSaleProduct, avec le
    # meme prix promo et le meme ordre que sur la vente d'origine).
    from products.models import FlashSaleProduct

    links = (
        FlashSaleProduct.objects.filter(flash_sale=sale, is_active=True)
        .select_related("product")
        .order_by("display_order")
    )
    for link in links:
        FlashSaleProduct.objects.create(
            flash_sale=new_sale,
            product=link.product,
            promo_price=link.promo_price,
            display_order=link.display_order,
            is_active=True,
        )

    return new_sale


def can_seller_create_sale(seller) -> tuple[bool, str]:
    """Verifie les limites du plan abonnement du vendeur."""
    try:
        from subscriptions.services.limits import can_create_flash_sale

        return can_create_flash_sale(seller)
    except Exception:
        # Fail-closed : une panne cote subscriptions (DB, bug futur, migration
        # cassee) ne doit jamais desactiver silencieusement le quota. On refuse
        # la creation plutot que de laisser un vendeur FREE creer des ventes
        # illimitees sans controle.
        logger.exception("Quota check failed for seller %s", getattr(seller, "pk", seller))
        return False, "Impossible de verifier votre quota. Reessayez."
