from __future__ import annotations

from django.core.exceptions import ValidationError

from flash_sales.models import FlashSale


def assert_flash_sale_accepts_orders(flash_sale: FlashSale | None) -> None:
    """
    Authorize placing an order: ``flash_sale`` must exist and
    ``flash_sale.is_live()`` must be true (time window only).
    """
    if flash_sale is None:
        raise ValidationError(
            {"flash_sale": "A flash sale instance is required to place an order."}
        )
    if not flash_sale.is_live():
        raise ValidationError(
            {
                "flash_sale": (
                    "Orders are only accepted while the flash sale window is active "
                    "(timezone.now() must fall between start_time and end_time)."
                )
            }
        )
