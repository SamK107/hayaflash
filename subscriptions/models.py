from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Plan(models.TextChoices):
    FREE = "free", "Gratuit"
    MEDIUM = "medium", "Medium"
    PRO = "pro", "Pro"


PLAN_PRICES = {
    Plan.FREE: 0,
    Plan.MEDIUM: 2000,
    Plan.PRO: 5000,
}

PLAN_MONTHLY_SALES_LIMIT = {
    Plan.FREE: 3,
    Plan.MEDIUM: 10,
    Plan.PRO: None,  # illimite
}

PLAN_FEATURES = {
    Plan.FREE: [
        "3 ventes flash par mois",
        "Page publique vendeur",
        "Commandes en ligne",
        "Lien de partage WhatsApp",
    ],
    Plan.MEDIUM: [
        "10 ventes flash par mois",
        "Statistiques de ventes (30 derniers jours)",
        "Historique des commandes complet",
        "Page publique vendeur",
        "Commandes en ligne",
        "Lien de partage WhatsApp",
    ],
    Plan.PRO: [
        "Ventes flash illimitées",
        "Statistiques et analyses avancées (historique complet)",
        "Tableau de bord LIVE temps réel",
        "Notifications SMS automatiques",
        "Support prioritaire WhatsApp",
        "Accès aux nouvelles fonctionnalités en avant-première",
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
        null=True,
        blank=True,
        verbose_name="Expire le",
        help_text="Null = Free perpétuel ou plan actif sans expiration",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"

    @property
    def is_free(self) -> bool:
        return self.plan == Plan.FREE or (self.plan != Plan.FREE and self.is_expired)

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
    PENDING = "pending", "En attente"
    SUCCESS = "success", "Succès"
    FAILED = "failed", "Échec"
    CANCELLED = "cancelled", "Annulé"
    EXPIRED = "expired", "Expiré"


class PaymentProvider(models.TextChoices):
    ORANGE = "orange", "Orange Money"
    MOOV = "moov", "Moov Money"
    WAVE = "wave", "Wave"


class SubscriptionPayment(models.Model):
    """Trace chaque tentative de paiement d'abonnement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.CASCADE,
        related_name="subscription_payments",
    )
    plan = models.CharField(max_length=20, choices=Plan.choices)
    provider = models.CharField(max_length=20, choices=PaymentProvider.choices)
    amount = models.PositiveIntegerField(help_text="Montant en FCFA")
    phone = models.CharField(max_length=20, help_text="Numéro payé")
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    # Orange Money specifics
    # order_id: Maximum 24 characters (Orange Money HTTP 400 limit)
    # Validé à la création dans services/payment.py
    order_id = models.CharField(
        max_length=24,
        unique=True,
        db_index=True,
        help_text="Identifiant commande Orange Money (max 24 chars)",
    )
    # notif_token: Token unique pour lookup webhook (sécurité critique)
    # IMPORTANT: Cet identifiant est utilisé UNIQUEMENT pour la sécurité des webhooks.
    # Les webhooks font un lookup par notif_token (pas par order_id) pour assurer
    # que seuls les paiements stockés peuvent être activés. Pas de HMAC/signature requis.
    notif_token = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        help_text="Token de notification Orange Money (lookup webhook)",
    )
    txn_id = models.CharField(max_length=200, blank=True, default="")
    payment_url = models.URLField(blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    raw_callback = models.JSONField(default=dict, blank=True)
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Paiement abonnement"
        verbose_name_plural = "Paiements abonnement"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order_id"]),
            models.Index(fields=["notif_token"]),
            models.Index(fields=["seller", "status"]),
        ]

    def clean(self):
        """Validation de order_id ≤ 24 caractères."""
        super().clean()
        if len(self.order_id) > 24:
            raise ValueError(
                f"order_id ne doit pas dépasser 24 caractères ({len(self.order_id)} fournis)"
            )

    def save(self, *args, **kwargs):
        """Valide l'ordre_id avant sauvegarde."""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"{self.seller} — {self.plan} — {self.status} — {self.created_at:%d/%m/%Y}"
        )


class WebhookLog(models.Model):
    """
    Audit trail de toutes les notifications webhooks Orange Money.
    Utilisé pour déboguer et auditeur les paiements reçus.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        SubscriptionPayment,
        on_delete=models.CASCADE,
        related_name="webhook_logs",
        help_text="Paiement associé (si trouvé)",
    )
    # Le token du webhook (même si le paiement n'a pas été trouvé)
    notif_token = models.CharField(max_length=128, db_index=True)
    status = models.CharField(
        max_length=20,
        blank=True,
        help_text="Statut rapporté par Orange Money (success/failure/etc)",
    )
    txn_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="ID transaction Orange Money",
    )
    # Payload brut pour audit et débogage
    raw_payload = models.JSONField(
        help_text="Payload brut reçu du webhook (sans secrets)"
    )
    # Statut du traitement
    processed = models.BooleanField(
        default=True,
        help_text="True si le webhook a été traité (activation ou mise à jour du paiement)",
    )
    error_message = models.TextField(
        blank=True,
        help_text="Message d'erreur si le traitement a échoué",
    )
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log webhook Orange Money"
        verbose_name_plural = "Logs webhooks Orange Money"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["notif_token"]),
            models.Index(fields=["payment", "status"]),
        ]

    def __str__(self) -> str:
        return (
            f"Webhook {self.notif_token[:16]}... — "
            f"{self.status} — {self.created_at:%d/%m/%Y %H:%M:%S}"
        )
