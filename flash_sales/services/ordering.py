from __future__ import annotations

from django.core.exceptions import ValidationError

from flash_sales.models import FlashSale


def assert_flash_sale_accepts_orders(flash_sale: FlashSale | None) -> None:
    """
    Authorize placing an order: only when ``flash_sale.is_live()`` is true.
    Call this from views / services before persisting an ``Order``.
    """
    if flash_sale is None:
        raise ValidationError(
            "This product is not linked to a flash sale; orders are not allowed."
        )
    if not flash_sale.is_live():
        raise ValidationError(
            "Orders are only allowed while the flash sale is live "
            "(FlashSale.is_live() is the source of truth)."
        )
