from __future__ import annotations

from decimal import Decimal

from django.db import models


class Product(models.Model):
    flash_sale = models.ForeignKey(
        "flash_sales.FlashSale",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Vente flash",
    )
    name = models.CharField(max_length=255, verbose_name="Nom du produit")
    description = models.TextField(blank=True, verbose_name="Description")
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Prix (FCFA)",
    )
    stock_initial = models.IntegerField(default=0, verbose_name="Stock initial")
    stock_available = models.IntegerField(default=0, verbose_name="Stock disponible")
    unit = models.CharField(
        max_length=50,
        default="piece",
        verbose_name="Unite",
        help_text="piece, kg, lot, carton...",
    )
    characteristics = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Caracteristiques",
    )
    description_audio = models.FileField(
        upload_to="audio/products/",
        null=True,
        blank=True,
        verbose_name="Description vocale",
        help_text="Enregistrement audio de la description (WebM/OGG)",
    )
    display_order = models.IntegerField(default=0, verbose_name="Ordre d'affichage")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "-created_at"]
        verbose_name = "Produit"
        verbose_name_plural = "Produits"
        indexes = [
            models.Index(fields=["flash_sale", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.flash_sale_id})"

    @property
    def is_available(self):
        return self.is_active and self.stock_available > 0

    @property
    def stock_percentage(self):
        if self.stock_initial == 0:
            return 0
        return int((self.stock_available / self.stock_initial) * 100)


class ProductMedia(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="media",
        verbose_name="Produit",
    )
    media_type = models.CharField(
        max_length=10,
        choices=MediaType.choices,
        default=MediaType.IMAGE,
        verbose_name="Type",
    )
    file = models.ImageField(
        upload_to="products/images/",
        null=True,
        blank=True,
        verbose_name="Fichier image",
    )
    video_url = models.URLField(
        blank=True,
        verbose_name="URL video",
        help_text="Lien YouTube, TikTok ou autre",
    )
    alt_text = models.CharField(max_length=200, blank=True, verbose_name="Texte alt")
    order = models.IntegerField(default=0, verbose_name="Ordre")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        verbose_name = "Media produit"
        verbose_name_plural = "Medias produits"

    def __str__(self):
        return f"Media #{self.order} - {self.product.name}"


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name="Produit",
    )
    type = models.CharField(
        max_length=50,
        verbose_name="Type",
        help_text="couleur, taille, pointure...",
    )
    value = models.CharField(max_length=100, verbose_name="Valeur")
    stock = models.IntegerField(default=0, verbose_name="Stock variante")
    price_delta = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Difference de prix",
    )

    class Meta:
        unique_together = ("product", "type", "value")
        verbose_name = "Variante"
        verbose_name_plural = "Variantes"

    def __str__(self):
        return f"{self.product.name} - {self.type}: {self.value}"


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        RESERVATION = "reservation", "Reservation (commande)"
        RELEASE     = "release",     "Liberation (annulation)"
        CORRECTION  = "correction",  "Correction manuelle"
        INITIAL     = "initial",     "Stock initial"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_movements",
        verbose_name="Produit",
    )
    order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        verbose_name="Commande",
    )
    quantity_change = models.IntegerField(
        verbose_name="Variation de stock",
        help_text="Negatif = sortie, positif = entree",
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        verbose_name="Type de mouvement",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Mouvement de stock"
        verbose_name_plural = "Mouvements de stock"
        indexes = [
            models.Index(fields=["product", "created_at"]),
        ]

    def __str__(self):
        sign = "+" if self.quantity_change > 0 else ""
        return f"{self.product.name} {sign}{self.quantity_change} ({self.movement_type})"
