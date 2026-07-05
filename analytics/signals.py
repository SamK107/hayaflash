from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import SellerProfile
from analytics.services.cache import invalidate_flash_sale_public_cache, invalidate_seller_public_cache
from flash_sales.models import FlashSale
from products.models import Product


@receiver(post_save, sender=SellerProfile)
def invalidate_on_seller_update(sender, instance: SellerProfile, **kwargs) -> None:
    if instance.public_slug:
        invalidate_seller_public_cache(
            seller_id=instance.pk,
            seller_slug=instance.public_slug,
        )


@receiver(post_save, sender=FlashSale)
def invalidate_on_flash_sale_update(sender, instance: FlashSale, **kwargs) -> None:
    if not instance.public_slug:
        return
    owner = instance.owner
    if owner.public_slug:
        invalidate_flash_sale_public_cache(
            flash_slug=instance.public_slug,
            seller_id=owner.pk,
            seller_slug=owner.public_slug,
        )


@receiver(post_save, sender=Product)
def invalidate_on_product_update(sender, instance: Product, **kwargs) -> None:
    if not instance.flash_sale_id:
        return
    sale = FlashSale.objects.select_related("owner").filter(pk=instance.flash_sale_id).first()
    if sale is None or not sale.public_slug:
        return
    owner = sale.owner
    if owner.public_slug:
        invalidate_flash_sale_public_cache(
            flash_slug=sale.public_slug,
            seller_id=owner.pk,
            seller_slug=owner.public_slug,
        )
