from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class OrderStatus(models.TextChoices):
    PENDING          = "pending",          "En attente"
    CONFIRMED        = "confirmed",        "Confirmé"
    OUT_FOR_DELIVERY = "out_for_delivery", "En livraison"
    DELIVERED        = "delivered",        "Livré et payé"
    CANCELLED        = "cancelled",        "Annulé"


class GuardedOrderManager(models.Manager):
    """Blocks accidental ``Order.objects.create()`` outside the service layer."""

    def create(self, **kwargs):  # type: ignore[override]
        raise RuntimeError(
            "Order.objects.create() is disabled. Persist new orders only via "
            "orders.services.create_order.create_order()."
        )


class Order(models.Model):
    """Legacy ``product`` / ``buyer`` rows may coexist with service-layer fields."""

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    flash_sale = models.ForeignKey(
        "flash_sales.FlashSale",
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_phone = models.CharField(max_length=32, blank=True, null=True)
    status = models.CharField(
        max_length=16,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
    )
    client_request_id = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        null=True,
        blank=True,
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = GuardedOrderManager()
    service_objects = models.Manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        if self.flash_sale_id:
            return f"Order {self.pk} — flash_sale={self.flash_sale_id}"
        return f"Order {self.pk} — legacy"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    product_name_snapshot = models.CharField(max_length=255)
    price_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.product_name_snapshot} x{self.quantity}"
