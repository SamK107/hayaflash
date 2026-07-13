from __future__ import annotations

from typing import TYPE_CHECKING

from core.services.slugs import flash_sale_slug_base, unique_slug_for_model

if TYPE_CHECKING:
    from flash_sales.models import FlashSale


def generate_unique_flash_sale_public_slug(flash_sale: FlashSale) -> str:
    base = flash_sale_slug_base(flash_sale.title)
    return unique_slug_for_model(
        type(flash_sale),
        field_name="public_slug",
        base=base,
        exclude_pk=flash_sale.pk,
        max_length=80,
    )
