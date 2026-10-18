from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class OrderStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    CONFIRMED = "confirmed", "Confirmé"
    OUT_FOR_DELIVERY = "out_for_delivery", "En livraison"
    DELIVERED = "delivered", "Livré et payé"
    CANCELLED = "cancelled", "Annulé"


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
        decimal_places=0,  # FCFA : unités entières, jamais de centimes
        default=Decimal("0"),
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
    price_snapshot = models.DecimalField(max_digits=12, decimal_places=0)  # FCFA entiers
    quantity = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.product_name_snapshot} x{self.quantity}"


class UnhonoredOrder(models.Model):
    """Commande non honoree : livraison refusee ou cliente injoignable (F-59 / D2).

    Une ligne est creee quand le vendeur marque la livraison « Echec ». Le
    numero (8 derniers chiffres) cumule ces echecs sur une fenetre glissante :
    voir ``orders.services.unhonored``. Une commande ensuite annulee par le
    vendeur ne compte plus.
    """

    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name="unhonored_record"
    )
    phone_key = models.CharField(max_length=16, db_index=True)
    seller = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.CASCADE,
        related_name="unhonored_orders",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Commande non honorée"
        verbose_name_plural = "Commandes non honorées"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Non honorée #{self.order_id} ({self.phone_key})"


class PhoneUnblock(models.Model):
    """Deblocage d'un numero : par une vendeuse (sa boutique) ou l'admin (global).

    Les echecs anterieurs au deblocage ne comptent plus pour la boutique
    concernee (``seller``) ou, si ``seller`` est vide, pour toutes.
    """

    phone_key = models.CharField(max_length=16, db_index=True)
    seller = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.CASCADE,
        related_name="phone_unblocks",
        null=True,
        blank=True,
        help_text="Vide = deblocage global (administration).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Déblocage de numéro"
        verbose_name_plural = "Déblocages de numéros"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        scope = f"boutique {self.seller_id}" if self.seller_id else "global"
        return f"Déblocage {self.phone_key} ({scope})"
