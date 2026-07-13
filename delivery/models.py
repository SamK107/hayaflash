from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Delivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        ASSIGNED = "assigned", "Livreur assigné"
        IN_TRANSIT = "in_transit", "En livraison"
        DELIVERED = "delivered", "Livré"
        FAILED = "failed", "Échec livraison"

    class GeoMethod(models.TextChoices):
        GPS = "gps", "GPS"
        MANUAL = "manual", "Manuel"
        TIMEOUT = "timeout", "Timeout"
        DENIED = "denied", "Refusé"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="delivery",
    )

    address_text = models.CharField(max_length=500)
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=8,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=11,
        decimal_places=8,
        null=True,
        blank=True,
    )
    geo_accuracy = models.FloatField(null=True, blank=True)
    geo_method = models.CharField(
        max_length=20,
        choices=GeoMethod.choices,
        default=GeoMethod.MANUAL,
    )
    delivery_notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    assigned_to = models.CharField(max_length=200, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    cod_amount = models.DecimalField(max_digits=10, decimal_places=2)
    cod_collected = models.BooleanField(default=False)
    cod_collected_at = models.DateTimeField(null=True, blank=True)
    cod_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_deliveries",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["order"]),
        ]

    def __str__(self) -> str:
        return f"Delivery {self.pk} — order={self.order_id}"

    def get_maps_url(self) -> str | None:
        if self.latitude is not None and self.longitude is not None:
            return f"https://www.google.com/maps?q={self.latitude},{self.longitude}"
        return None

    def get_waze_url(self) -> str | None:
        if self.latitude is not None and self.longitude is not None:
            return (
                f"https://waze.com/ul?ll={self.latitude},{self.longitude}&navigate=yes"
            )
        return None
