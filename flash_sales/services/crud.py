"""Services CRUD pour les ventes flash (vendeur authentifie)."""

from __future__ import annotations

from datetime import timedelta

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

    # Cloner les produits
    from products.models import Product, ProductMedia

    for p in sale.products.filter(is_active=True).order_by("display_order"):
        new_p = Product(
            flash_sale=new_sale,
            name=p.name,
            description=p.description,
            price=p.price,
            unit=p.unit,
            display_order=p.display_order,
            characteristics=p.characteristics,
            stock_initial=p.stock_initial,
            stock_available=p.stock_initial,  # reset au stock initial
            is_active=True,
        )
        if p.description_audio:
            new_p.description_audio = p.description_audio.name
        new_p.save()
        # Cloner les medias (meme fichier, pas de copie physique)
        for m in p.media.all():
            ProductMedia.objects.create(
                product=new_p,
                media_type=m.media_type,
                file=m.file.name if m.file else None,
                video_url=m.video_url,
                alt_text=m.alt_text,
                order=m.order,
            )

    return new_sale


def can_seller_create_sale(seller) -> tuple[bool, str]:
    """Verifie les limites du plan abonnement du vendeur."""
    try:
        from subscriptions.services.limits import can_create_flash_sale

        return can_create_flash_sale(seller)
    except Exception:
        return True, ""  # Fail open si subscriptions non disponible
