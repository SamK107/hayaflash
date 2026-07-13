from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Plan(models.TextChoices):
    FREE   = "free",   "Gratuit"
    MEDIUM = "medium", "Medium"
    PRO    = "pro",    "Pro"


PLAN_PRICES = {
    Plan.FREE:   0,
    Plan.MEDIUM: 2000,
    Plan.PRO:    5000,
}

PLAN_MONTHLY_SALES_LIMIT = {
    Plan.FREE:   3,
    Plan.MEDIUM: 3,
    Plan.PRO:    None,   # illimite
}

PLAN_FEATURES = {
    Plan.FREE: [
        "3 ventes flash par mois",
        "Page publique vendeur",
        "Commandes en ligne",
        "Lien de partage WhatsApp",
    ],
    Plan.MEDIUM: [
        "3 ventes flash par mois",
        "Statistiques de ventes (30 derniers jours)",
        "Historique des commandes complet",
        "Page publique vendeur",
        "Commandes en ligne",
        "Lien de partage WhatsApp",
    ],
    Plan.PRO: [
        "Ventes flash illimitees",
        "Statistiques et analyses avancees (historique complet)",
        "Tableau de bord LIVE temps reel",
        "Notifications SMS automatiques",
        "Support prioritaire WhatsApp",
        "Acces aux nouvelles fonctionnalites en avant-premiere",
    ],
}


class Subscription(models.Model):
    seller = models.OneToOneField(
        "accounts.SellerProfile",
        on_delete=models.CASCADE,
        related_name="subscription",
        verbose_name="Vendeur",
    )
    plan = models.CharField(
        max_length=20,
        choices=Plan.choices,
        default=Plan.FREE,
        db_index=True,
        verbose_name="Plan",
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Expire le",
        help_text="Null = Free perpetuel ou plan actif sans expiration",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"

    @property
    def is_free(self) -> bool:
        return self.plan == Plan.FREE or (
            self.plan != Plan.FREE and self.is_expired
        )

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at < timezone.now())

    @property
    def is_medium(self) -> bool:
        return self.plan == Plan.MEDIUM and not self.is_expired

    @property
    def is_pro(self) -> bool:
        return self.plan == Plan.PRO and not self.is_expired

    @property
    def is_paid(self) -> bool:
        return self.is_medium or self.is_pro

    @property
    def has_stats(self) -> bool:
        return self.is_medium or self.is_pro

    @property
    def has_advanced_stats(self) -> bool:
        return self.is_pro

    @property
    def monthly_sales_limit(self):
        return PLAN_MONTHLY_SALES_LIMIT.get(self.plan)

    @property
    def plan_label(self) -> str:
        return self.get_plan_display()

    @property
    def plan_price(self) -> int:
        return PLAN_PRICES.get(self.plan, 0)

    @property
    def features(self) -> list[str]:
        return PLAN_FEATURES.get(self.plan, [])

    def __str__(self) -> str:
        status = self.plan_label
        if self.is_expired:
            status += " (expire)"
        return f"{self.seller.business_name} — {status}"


class PaymentStatus(models.TextChoices):
    PENDING   = "pending",   "En attente"
    SUCCESS   = "success",   "Succes"
    FAILED    = "failed",    "Echec"
    CANCELLED = "cancelled", "Annule"
    EXPIRED   = "expired",   "Expire"


class PaymentProvider(models.TextChoices):
    ORANGE = "orange", "Orange Money"
    MOOV   = "moov",   "Moov Money"
    WAVE   = "wave",   "Wave"


class SubscriptionPayment(models.Model):
    """Trace chaque tentative de paiement d'abonnement."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller      = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.CASCADE,
        related_name="subscription_payments",
    )
    plan        = models.CharField(max_length=20, choices=Plan.choices)
    provider    = models.CharField(max_length=20, choices=PaymentProvider.choices)
    amount      = models.PositiveIntegerField(help_text="Montant en FCFA")
    phone       = models.CharField(max_length=20, help_text="Numero paye")
    status      = models.CharField(
        max_length=20, choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING, db_index=True,
    )
    # Orange Money specifics
    order_id    = models.CharField(max_length=100, unique=True, db_index=True)
    pay_token   = models.CharField(max_length=200, blank=True, default="")
    txn_id      = models.CharField(max_length=200, blank=True, default="")
    payment_url = models.URLField(blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    raw_callback = models.JSONField(default=dict, blank=True)
    # Dates
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    paid_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Paiement abonnement"
        verbose_name_plural = "Paiements abonnement"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order_id"]),
            models.Index(fields=["seller", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.seller} — {self.plan} — {self.status} — {self.created_at:%d/%m/%Y}"
