from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import SellerProfile
from analytics.services.cache import (
    invalidate_flash_sale_public_cache,
    invalidate_seller_public_cache,
)
from flash_sales.models import FlashSale
from products.models import FlashSaleProduct, Product


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


def _invalidate_sales_public_cache(sale_ids) -> None:
    sales = FlashSale.objects.select_related("owner").filter(pk__in=list(sale_ids))
    for sale in sales:
        if not sale.public_slug:
            continue
        owner = sale.owner
        if owner.public_slug:
            invalidate_flash_sale_public_cache(
                flash_slug=sale.public_slug,
                seller_id=owner.pk,
                seller_slug=owner.public_slug,
            )


@receiver(post_save, sender=Product)
def invalidate_on_product_update(sender, instance: Product, **kwargs) -> None:
    # Un Product de catalogue peut etre rattache a plusieurs ventes
    # (FlashSaleProduct) : invalider le cache public de CHACUNE d'elles.
    sale_ids = FlashSaleProduct.objects.filter(product=instance).values_list(
        "flash_sale_id", flat=True
    )
    _invalidate_sales_public_cache(sale_ids)


@receiver(post_save, sender=FlashSaleProduct)
def invalidate_on_flash_sale_product_update(
    sender, instance: FlashSaleProduct, **kwargs
) -> None:
    # Prix promo / ordre / actif propres a une vente : invalider seulement
    # cette vente.
    _invalidate_sales_public_cache([instance.flash_sale_id])
