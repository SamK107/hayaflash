from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class FlashSaleStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Programmee"
    LIVE = "live", "En cours"
    CLOSED = "closed", "Fermee"
    EXECUTING = "executing", "En execution"
    COMPLETED = "completed", "Terminee"
    CANCELLED = "cancelled", "Annulee"


class FlashSale(models.Model):
    title = models.CharField(max_length=255, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Description")
    cover_image = models.ImageField(
        upload_to="flash_sales/covers/",
        null=True,
        blank=True,
        verbose_name="Image de couverture",
    )
    public_slug = models.SlugField(
        max_length=80,
        unique=True,
        blank=True,
        db_index=True,
        help_text="Slug public pour la page de partage (/f/<slug>/).",
    )
    start_time = models.DateTimeField(verbose_name="Debut")
    end_time = models.DateTimeField(verbose_name="Fin")
    status = models.CharField(
        max_length=16,
        choices=FlashSaleStatus.choices,
        default=FlashSaleStatus.SCHEDULED,
        db_index=True,
        verbose_name="Statut",
    )
    owner = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.PROTECT,
        related_name="flash_sales",
        verbose_name="Vendeur",
    )
    delivery_zone = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Zone de livraison",
        help_text="Ex: Bamako, ACI 2000, Kalaban Coura",
    )
    max_orders = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Plafond de commandes",
        help_text="Laisser vide pour illimite",
    )
    description_audio = models.FileField(
        upload_to="audio/sales/",
        null=True,
        blank=True,
        verbose_name="Description vocale",
        help_text="Enregistrement audio de la description (WebM/OGG)",
    )
    teasers = models.TextField(
        blank=True,
        default="",
        verbose_name="Teasers page d'attente",
        help_text="Un teaser par ligne. Ex: 8 sacs de luxe · 15 montres · 5 parfums",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_time"]
        verbose_name = "Vente flash"
        verbose_name_plural = "Ventes flash"

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.end_time is not None and self.start_time is not None:
            if self.end_time <= self.start_time:
                raise ValidationError("La fin doit être après le début.")

    def save(self, *args, **kwargs):
        if not self.public_slug:
            from flash_sales.services.slugs import (
                generate_unique_flash_sale_public_slug,
            )

            self.public_slug = generate_unique_flash_sale_public_slug(self)
        super().save(*args, **kwargs)

    def is_live(self):
        now = timezone.now()
        return self.start_time <= now <= self.end_time

    @property
    def is_scheduled(self):
        return self.status == FlashSaleStatus.SCHEDULED

    @property
    def accepts_orders(self):
        now = timezone.now()
        return (
            self.status == FlashSaleStatus.LIVE
            and self.start_time <= now <= self.end_time
        )

    def open_sale(self):
        non_reopenable = {
            FlashSaleStatus.CANCELLED,
            FlashSaleStatus.COMPLETED,
            FlashSaleStatus.CLOSED,
            FlashSaleStatus.EXECUTING,
            FlashSaleStatus.LIVE,
        }
        if self.status in non_reopenable:
            raise ValueError(
                f"Impossible d'ouvrir une vente avec le statut '{self.status}'."
            )
        self.status = FlashSaleStatus.LIVE
        self.save(update_fields=["status", "updated_at"])

    def close_sale(self):
        self.status = FlashSaleStatus.CLOSED
        self.save(update_fields=["status", "updated_at"])

    def complete_sale(self):
        self.status = FlashSaleStatus.COMPLETED
        self.save(update_fields=["status", "updated_at"])

    def cancel_sale(self):
        if self.status == FlashSaleStatus.LIVE:
            raise ValueError(
                "Impossible d'annuler une vente en cours. Fermez-la d'abord."
            )
        self.status = FlashSaleStatus.CANCELLED
        self.save(update_fields=["status", "updated_at"])


class SaleInterest(models.Model):
    """
    Réservation d'intérêt d'un client pour la prochaine vente flash d'un vendeur.
    Créée depuis la page publique /f/<slug>/ quand la vente est terminée.
    """

    flash_sale = models.ForeignKey(
        FlashSale,
        on_delete=models.CASCADE,
        related_name="interests",
        verbose_name="Vente flash",
    )
    phone = models.CharField(max_length=32, verbose_name="Téléphone")
    name = models.CharField(max_length=150, blank=True, verbose_name="Nom")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Réservation d'intérêt"
        verbose_name_plural = "Réservations d'intérêt"
        indexes = [
            models.Index(fields=["flash_sale", "created_at"]),
        ]

    def __str__(self):
        return f"{self.phone} → {self.flash_sale}"
