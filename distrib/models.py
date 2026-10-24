"""Module Distrib : grossistes / revendeurs (docs/specs/SPEC_03_DISTRIB_V1.md).

Principes (§2) : app independante (aucune app existante n'importe `distrib`), aucun
champ ajoute aux modeles existants, montants en FCFA entiers, numeros en E.164.
Le lien produit <-> grossiste vit ici (`ImportedProduct`), jamais dans `products`.
"""

from __future__ import annotations

import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.choices import SaleCategory
from core.uploads import RandomUploadPath
from core.validators import IMAGE_VALIDATORS


def _fcfa(**kwargs) -> models.DecimalField:
    """Montant en FCFA : unites entieres, jamais de centimes."""
    return models.DecimalField(max_digits=12, decimal_places=0, **kwargs)


def generate_receipt_token() -> str:
    """Jeton long non devinable du recu client (§15.3)."""
    return secrets.token_urlsafe(24)


class Distributor(models.Model):
    """Le grossiste. Cree uniquement par l'equipe HayaFlash (§5.1)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="distributor"
    )
    business_name = models.CharField("Nom commercial", max_length=160)
    contact_phone = models.CharField("Téléphone de contact", max_length=16, blank=True)
    orange_money_number = models.CharField("Numéro Orange Money", max_length=16, blank=True)

    is_active = models.BooleanField("Actif", default=True)
    is_suspended = models.BooleanField("Suspendu", default=False)
    suspended_reason = models.CharField("Motif de suspension", max_length=255, blank=True)

    commission_rate = models.DecimalField(
        "Taux de commission (%)", max_digits=5, decimal_places=2, default=Decimal("6")
    )
    commission_min = _fcfa(verbose_name="Commission minimum (FCFA)", default=Decimal("250"))
    commission_max = _fcfa(verbose_name="Commission maximum par commande (FCFA)", default=Decimal("1500"))
    pilot_until = models.DateField(
        "Période d'essai jusqu'au", null=True, blank=True,
        help_text="Avant cette date, la commission n'est pas facturable.",
    )
    credit_ceiling = _fcfa(verbose_name="Plafond d'encours de commission (FCFA)", default=Decimal("10000"))
    reseller_credit_ceiling = _fcfa(
        verbose_name="Plafond de marges dues par revendeur (FCFA)", default=Decimal("10000")
    )
    payout_delay_days = models.PositiveIntegerField("Délai de versement (jours)", default=3)
    auto_confirm_hours = models.PositiveIntegerField(
        "Confirmation automatique après (heures)", default=72
    )

    # Seuils de l'indice de fiabilite (§15.5), pilotage uniquement.
    alert_not_delivered_percent = models.PositiveIntegerField(
        "Alerte « Pas livré » (%)", default=20
    )
    alert_conflicts = models.PositiveIntegerField("Alerte conflits (nombre)", default=1)
    alert_contested = models.PositiveIntegerField("Alerte versements contestés (nombre)", default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="distributors_created",
    )

    class Meta:
        ordering = ["business_name"]
        verbose_name = "Grossiste"
        verbose_name_plural = "Grossistes"

    def __str__(self) -> str:
        return self.business_name


class ResellerInvite(models.Model):
    """Liste prealable du grossiste : un numero invite, jamais un blocage d'inscription."""

    class Status(models.TextChoices):
        INVITED = "invited", "Invité"
        ACCEPTED = "accepted", "Accepté"
        DECLINED = "declined", "Refusé"
        REVOKED = "revoked", "Révoqué"

    distributor = models.ForeignKey(Distributor, on_delete=models.CASCADE, related_name="invites")
    display_name = models.CharField("Nom", max_length=120)
    phone = models.CharField("Téléphone (E.164)", max_length=16)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INVITED)
    seller = models.ForeignKey(
        "accounts.SellerProfile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="distrib_invites",
    )
    invited_at = models.DateTimeField(default=timezone.now)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-invited_at"]
        verbose_name = "Revendeur invité"
        verbose_name_plural = "Revendeurs invités"
        constraints = [
            models.UniqueConstraint(fields=["distributor", "phone"], name="distrib_invite_unique_phone"),
        ]
        indexes = [models.Index(fields=["phone", "status"])]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.phone}) → {self.distributor}"


class WholesaleProduct(models.Model):
    """Catalogue de gros du grossiste."""

    distributor = models.ForeignKey(Distributor, on_delete=models.CASCADE, related_name="wholesale_products")
    name = models.CharField("Nom", max_length=255)
    description = models.TextField("Description", blank=True)
    category = models.CharField(
        "Catégorie", max_length=20, choices=SaleCategory.choices, blank=True
    )
    wholesale_price = _fcfa(verbose_name="Prix de gros (FCFA)")
    min_retail_price = _fcfa(verbose_name="Prix de vente minimum (FCFA)")
    stock_total = models.PositiveIntegerField("Stock total", default=0)
    is_active = models.BooleanField("Actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Produit de gros"
        verbose_name_plural = "Produits de gros"

    def __str__(self) -> str:
        return self.name


class WholesaleProductImage(models.Model):
    wholesale_product = models.ForeignKey(
        WholesaleProduct, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(
        upload_to=RandomUploadPath("distrib/wholesale"), validators=IMAGE_VALIDATORS
    )
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "Image de produit de gros"
        verbose_name_plural = "Images de produits de gros"

    def save(self, *args, **kwargs):
        from core.services.image_optimize import is_pending_upload, resize_uploaded_image

        if is_pending_upload(self.image):
            resize_uploaded_image(self.image)
        super().save(*args, **kwargs)


class ImportedProduct(models.Model):
    """Lien produit de la boutique <-> catalogue de gros (jamais dans `products`)."""

    wholesale_product = models.ForeignKey(
        WholesaleProduct, on_delete=models.PROTECT, related_name="imports"
    )
    invite = models.ForeignKey(ResellerInvite, on_delete=models.PROTECT, related_name="imports")
    product = models.OneToOneField(
        "products.Product", on_delete=models.CASCADE, related_name="distrib_import"
    )
    allocated_qty = models.PositiveIntegerField("Quantité actuellement allouée", default=0)
    hidden_prev_active = models.BooleanField(
        "État actif avant masquage", null=True, blank=True,
        help_text="Renseigné quand l'équipe masque les produits du grossiste (réversible).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Produit importé"
        verbose_name_plural = "Produits importés"
        constraints = [
            models.UniqueConstraint(
                fields=["wholesale_product", "invite"], name="distrib_import_unique_per_reseller"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.wholesale_product} → {self.invite.display_name}"


class AllocationMovement(models.Model):
    """Journal des allocations : + allocation, − reprise."""

    imported_product = models.ForeignKey(
        ImportedProduct, on_delete=models.CASCADE, related_name="movements"
    )
    quantity_change = models.IntegerField()
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Mouvement d'allocation"
        verbose_name_plural = "Mouvements d'allocation"


class DistribStatement(models.Model):
    """Relevé hebdomadaire des marges d'un revendeur (§15.4)."""

    class Status(models.TextChoices):
        TO_PAY = "to_pay", "À régler"
        PAID = "paid", "Payé"
        ACCEPTED = "accepted", "Accepté"
        CONTESTED = "contested", "Contesté"
        ESCALATED = "escalated", "Escaladé (équipe)"

    distributor = models.ForeignKey(Distributor, on_delete=models.CASCADE, related_name="statements")
    invite = models.ForeignKey(ResellerInvite, on_delete=models.PROTECT, related_name="statements")
    period_start = models.DateField()
    period_end = models.DateField()
    amount = _fcfa(default=Decimal("0"))
    line_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TO_PAY)
    contest_count = models.PositiveSmallIntegerField(default=0)
    closed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-period_start", "-pk"]
        verbose_name = "Relevé"
        verbose_name_plural = "Relevés"
        constraints = [
            models.UniqueConstraint(fields=["invite", "period_start"], name="distrib_statement_unique_period"),
        ]


class ResellerPayout(models.Model):
    """Versement d'un relevé au revendeur : une ligne par déclaration (1 ou 2)."""

    class Status(models.TextChoices):
        DECLARED = "declared", "Déclaré"
        ACCEPTED = "accepted", "Accepté"
        CONTESTED = "contested", "Contesté"

    class AcceptedSource(models.TextChoices):
        RESELLER = "reseller", "Revendeur"
        AUTO = "auto", "Automatique"
        STAFF = "staff", "Équipe HayaFlash"

    distributor = models.ForeignKey(Distributor, on_delete=models.CASCADE, related_name="payouts")
    invite = models.ForeignKey(ResellerInvite, on_delete=models.PROTECT, related_name="payouts")
    statement = models.ForeignKey(DistribStatement, on_delete=models.PROTECT, related_name="payouts")
    attempt = models.PositiveSmallIntegerField(default=1)
    amount = _fcfa(help_text="Recopié du relevé, jamais saisi.")
    paid_at = models.DateTimeField(default=timezone.now)
    om_reference = models.CharField("Référence Orange Money", max_length=40)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DECLARED)
    contest_deadline = models.DateTimeField(null=True, blank=True)
    contest_reason = models.CharField(max_length=255, blank=True)
    accepted_source = models.CharField(
        max_length=10, choices=AcceptedSource.choices, blank=True
    )

    class Meta:
        ordering = ["-paid_at", "-pk"]
        verbose_name = "Versement au revendeur"
        verbose_name_plural = "Versements aux revendeurs"
        constraints = [
            models.UniqueConstraint(fields=["statement", "attempt"], name="distrib_payout_unique_attempt"),
        ]


class DistribSettlement(models.Model):
    """Suivi d'un article vendu (une ligne par `OrderItem` de produit importé)."""

    class Status(models.TextChoices):
        ORDERED = "ordered", "Commandé"
        IN_DELIVERY = "in_delivery", "En livraison"
        DELIVERED_BY_SHOP = "delivered_by_shop", "Livré (boutique)"
        PAID_CONFIRMED = "paid_confirmed", "Livré et payé"
        CANCELLED = "cancelled", "Annulé"
        NOT_DELIVERED = "not_delivered", "Pas livré"

    class ConfirmationSource(models.TextChoices):
        DISTRIBUTOR = "distributor", "Grossiste"
        CUSTOMER = "customer", "Cliente"
        AUTO = "auto", "Automatique"

    class NotDeliveredReason(models.TextChoices):
        REFUSED = "refused", "La cliente a refusé"
        ABSENT = "absent", "Cliente absente ou injoignable"
        CANCELLED = "cancelled", "Annulée par la cliente"
        OTHER = "other", "Autre"

    distributor = models.ForeignKey(Distributor, on_delete=models.CASCADE, related_name="settlements")
    invite = models.ForeignKey(ResellerInvite, on_delete=models.PROTECT, related_name="settlements")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="distrib_settlements")
    order_item = models.ForeignKey(
        "orders.OrderItem", null=True, blank=True, on_delete=models.CASCADE,
        related_name="distrib_settlements",
    )
    imported_product = models.ForeignKey(
        ImportedProduct, on_delete=models.PROTECT, related_name="settlements"
    )
    quantity = models.PositiveIntegerField()
    sale_amount = _fcfa()
    wholesale_amount = _fcfa()
    reseller_margin = _fcfa()
    commission_amount = _fcfa(default=Decimal("0"))
    commission_billable = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ORDERED)
    paid_confirmed_at = models.DateTimeField(null=True, blank=True)
    paid_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    confirmation_source = models.CharField(
        max_length=12, choices=ConfirmationSource.choices, blank=True
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    auto_confirm_at = models.DateTimeField(null=True, blank=True)

    not_delivered_reason = models.CharField(
        max_length=10, choices=NotDeliveredReason.choices, blank=True
    )
    not_delivered_note = models.CharField(max_length=200, blank=True)
    declared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    declared_at = models.DateTimeField(null=True, blank=True)

    statement = models.ForeignKey(
        DistribStatement, null=True, blank=True, on_delete=models.SET_NULL, related_name="lines"
    )
    payout = models.ForeignKey(
        ResellerPayout, null=True, blank=True, on_delete=models.SET_NULL, related_name="lines"
    )

    receipt_token = models.CharField(max_length=64, unique=True, default=generate_receipt_token)
    receipt_code = models.CharField(max_length=4, blank=True)
    customer_confirmed_at = models.DateTimeField(null=True, blank=True)
    customer_om_reference = models.CharField(max_length=40, blank=True)
    conflict_flag = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Suivi de vente"
        verbose_name_plural = "Suivis de vente"
        constraints = [
            models.UniqueConstraint(fields=["order_item"], name="distrib_settlement_unique_item"),
        ]
        indexes = [
            models.Index(fields=["distributor", "status"]),
            models.Index(fields=["invite", "status"]),
        ]


class DistribPayment(models.Model):
    """Règlement des commissions à HayaFlash (enregistré par l'équipe)."""

    distributor = models.ForeignKey(Distributor, on_delete=models.CASCADE, related_name="payments")
    amount = _fcfa()
    paid_at = models.DateTimeField(default=timezone.now)
    reference = models.CharField("Référence Orange Money", max_length=60, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-paid_at", "-pk"]
        verbose_name = "Règlement de commission"
        verbose_name_plural = "Règlements de commission"


class DistribCorrection(models.Model):
    """Correction d'une ligne de suivi (équipe ou système), toujours motivée (§15.1)."""

    settlement = models.ForeignKey(DistribSettlement, on_delete=models.CASCADE, related_name="corrections")
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    reason = models.CharField(max_length=255)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Vide = correction automatique du système.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Correction"
        verbose_name_plural = "Corrections"
