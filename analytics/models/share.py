from __future__ import annotations

from django.db import models
from django.utils.crypto import get_random_string


class ShareLinkType(models.TextChoices):
    SELLER = "seller", "Seller storefront"
    FLASH_SALE = "flash_sale", "Flash sale"
    PRODUCT = "product", "Product order link"


class ShareEventType(models.TextChoices):
    PAGE_VIEW = "page_view", "Page view"
    CLICK = "click", "Click"
    WHATSAPP_SHARE = "whatsapp_share", "WhatsApp share"
    CONVERSION = "conversion", "Order conversion"


class ShareLink(models.Model):
    """
    Stable attribution token for viral links.
    One row per target (``target_key``).
    """

    token = models.CharField(max_length=24, unique=True, db_index=True, editable=False)
    link_type = models.CharField(
        max_length=16, choices=ShareLinkType.choices, db_index=True
    )
    seller = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="share_links",
    )
    flash_sale = models.ForeignKey(
        "flash_sales.FlashSale",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="share_links",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="share_links",
    )
    target_key = models.CharField(max_length=64, unique=True, editable=False)
    click_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)
    conversion_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["token"], name="an_sl_token_idx"),
            models.Index(fields=["link_type", "seller"], name="an_sl_type_seller_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.link_type}:{self.token}"

    def compute_target_key(self) -> str:
        if self.link_type == ShareLinkType.SELLER and self.seller_id:
            return f"seller:{self.seller_id}"
        if self.link_type == ShareLinkType.FLASH_SALE and self.flash_sale_id:
            return f"flash_sale:{self.flash_sale_id}"
        if self.link_type == ShareLinkType.PRODUCT and self.product_id:
            return f"product:{self.product_id}"
        raise ValueError("ShareLink target FKs do not match link_type.")

    def save(self, *args, **kwargs):
        if not self.target_key:
            self.target_key = self.compute_target_key()
        if not self.token:
            self.token = generate_unique_share_token(type(self))
        super().save(*args, **kwargs)


class ShareEvent(models.Model):
    share_link = models.ForeignKey(
        ShareLink,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(
        max_length=20,
        choices=ShareEventType.choices,
        db_index=True,
    )
    source = models.CharField(max_length=32, blank=True, db_index=True)
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="share_events",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["share_link", "event_type"], name="an_se_link_type_idx"
            ),
            models.Index(
                fields=["share_link", "created_at"], name="an_se_link_created_idx"
            ),
            models.Index(fields=["source", "created_at"], name="an_se_src_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"


def generate_unique_share_token(model_class, length: int = 10) -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    while True:
        candidate = get_random_string(length, allowed_chars=alphabet)
        if not model_class.objects.filter(token=candidate).exists():
            return candidate
