from __future__ import annotations

from django.conf import settings
from django.db import models


class Order(models.Model):
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Order {self.pk} — {self.product}"
