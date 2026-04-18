from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class FlashSaleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    LIVE = "live", "Live"
    CLOSED = "closed", "Closed"


class FlashSale(models.Model):
    title = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=FlashSaleStatus.choices,
        default=FlashSaleStatus.DRAFT,
        db_index=True,
    )
    owner = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.PROTECT,
        related_name="flash_sales",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_time"]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "End time must be after start time."})

    def is_live(self) -> bool:
        """Whether an order may be placed now; uses django.utils.timezone.now() plus schedule and live status."""
        now = timezone.now()
        in_window = self.start_time <= now <= self.end_time
        published = self.status == FlashSaleStatus.LIVE
        return published and in_window

    def open_sale(self) -> None:
        if self.status == FlashSaleStatus.CLOSED:
            raise ValueError("Cannot open a closed flash sale.")
        self.status = FlashSaleStatus.LIVE
        self.save(update_fields=["status", "updated_at"])

    def close_sale(self) -> None:
        self.status = FlashSaleStatus.CLOSED
        self.save(update_fields=["status", "updated_at"])
