from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Plan(models.TextChoices):
    FREE = "free", "Gratuit"
    MEDIUM = "medium", "Medium"
    PRO = "pro", "Pro"


# Tarifs, quotas, durees et fonctionnalites : en base (PlanConfig), lus
# UNIQUEMENT via subscriptions/services/plans.py. Les valeurs de secours
# (DEFAULT_*) vivent dans ce service, pas ici.


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
        from subscriptions.services.plans import get_monthly_limit

        return get_monthly_limit(self.plan)

    @property
    def plan_label(self) -> str:
        return self.get_plan_display()

    @property
    def plan_price(self) -> int:
        from subscriptions.services.plans import get_official_price

        return get_official_price(self.plan)

    @property
    def features(self) -> list[str]:
        from subscriptions.services.plans import get_features

        return get_features(self.plan)

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
    # Tarif special par vendeur (SellerPriceOverride) : null = prix officiel.
    # PROTECT : un tarif special deja utilise ne peut plus etre supprime
    # (historique des paiements).
    price_override = models.ForeignKey(
        "subscriptions.SellerPriceOverride",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        verbose_name="Tarif spécial",
    )
    is_special_price = models.BooleanField(
        default=False, db_index=True, verbose_name="Tarif spécial"
    )
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


class PlanConfig(models.Model):
    """Valeurs administrables d'un plan (une ligne par plan, 3 lignes fixes).

    Les codes FREE / MEDIUM / PRO restent dans le code (Plan). Un changement
    ici s'applique aux NOUVEAUX paiements uniquement : SubscriptionPayment.amount
    fige le montant de chaque paiement. Lecture via services/plans.py.
    """

    plan = models.CharField(
        max_length=20, choices=Plan.choices, unique=True, verbose_name="Plan"
    )
    price = models.PositiveIntegerField(
        verbose_name="Prix (FCFA)",
        help_text="FCFA entiers, envoyé tel quel à Orange Money (2000 = 2 000 FCFA).",
    )
    monthly_sales_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Ventes par mois",
        help_text="Vide = illimité.",
    )
    duration_days = models.PositiveIntegerField(
        default=31, verbose_name="Durée (jours)"
    )
    features = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Fonctionnalités",
        help_text=(
            'Liste de textes, ex. ["Page publique vendeur", "Commandes en ligne"]. '
            "La ligne du quota (« 10 ventes flash par mois ») est ajoutée "
            "automatiquement : ne pas la saisir."
        ),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Actif",
        help_text="Inactif = plan non proposé à la souscription (Medium/Pro).",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Modifié par",
    )

    class Meta:
        verbose_name = "Configuration de plan"
        verbose_name_plural = "Configuration des plans"
        ordering = ["price"]

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.plan == Plan.FREE:
            if self.price != 0:
                errors["price"] = "Le plan Gratuit doit rester à 0 FCFA."
            if not self.is_active:
                errors["is_active"] = "Le plan Gratuit ne peut pas être désactivé."
        elif (self.price or 0) < 100:
            errors["price"] = "Minimum 100 FCFA pour un plan payant."
        if not isinstance(self.features, list) or not all(
            isinstance(f, str) for f in self.features
        ):
            errors["features"] = "Doit être une liste de textes."
        if not self.duration_days:
            errors["duration_days"] = "Durée minimale : 1 jour."
        other = {Plan.MEDIUM: Plan.PRO, Plan.PRO: Plan.MEDIUM}.get(self.plan)
        if other is not None:
            other_limit = (
                PlanConfig.objects.filter(plan=other)
                .values_list("monthly_sales_limit", flat=True)
                .first()
            )
            medium = self.monthly_sales_limit if self.plan == Plan.MEDIUM else other_limit
            pro = self.monthly_sales_limit if self.plan == Plan.PRO else other_limit
            # Limite MEDIUM <= limite PRO ; PRO vide = illimite (toujours ok).
            if pro is not None and (medium is None or medium > pro):
                errors["monthly_sales_limit"] = (
                    "La limite Medium doit rester inférieure ou égale à la limite Pro "
                    f"(Medium : {medium if medium is not None else 'illimité'}, "
                    f"Pro : {pro})."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from subscriptions.services.plans import invalidate_plan_cache

        invalidate_plan_cache()

    def __str__(self) -> str:
        return f"{self.get_plan_display()} — {self.price} FCFA"


class OverrideReason(models.TextChoices):
    TEST = "test", "Test de paiement"
    PILOT = "pilote", "Vendeur pilote"
    PARTNER = "partenaire", "Partenaire"
    PROMO = "promo", "Promotion"


SPECIAL_PRICE_MIN = 100
SPECIAL_PRICE_MAX_DAYS = 30


class SellerPriceOverride(models.Model):
    """Tarif special temporaire pour UN vendeur (test de paiement, pilote, promo).

    Ne modifie jamais le prix des autres vendeurs. Le montant est choisi cote
    serveur a l'initiation du paiement (services/plans.py:get_price_quote),
    jamais lu depuis le formulaire.
    """

    seller = models.ForeignKey(
        "accounts.SellerProfile",
        on_delete=models.CASCADE,
        related_name="price_overrides",
        verbose_name="Vendeur",
    )
    plan = models.CharField(
        max_length=20,
        choices=[(Plan.MEDIUM.value, "Medium"), (Plan.PRO.value, "Pro")],
        verbose_name="Plan",
    )
    price = models.PositiveIntegerField(
        verbose_name="Prix spécial (FCFA)",
        help_text=f"Entre {SPECIAL_PRICE_MIN} FCFA et le prix officiel du plan.",
    )
    duration_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Durée (jours)",
        help_text="Vide = durée du plan. Ex. 1 pour un test de paiement.",
    )
    reason = models.CharField(
        max_length=20, choices=OverrideReason.choices, verbose_name="Motif"
    )
    reason_detail = models.CharField(
        max_length=200, blank=True, verbose_name="Précision"
    )
    starts_at = models.DateTimeField(default=timezone.now, verbose_name="Début")
    expires_at = models.DateTimeField(
        verbose_name="Fin",
        help_text=f"Obligatoire, au plus {SPECIAL_PRICE_MAX_DAYS} jours après le début.",
    )
    max_uses = models.PositiveIntegerField(default=1, verbose_name="Utilisations max")
    uses_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Utilisations",
        help_text="Incrémenté uniquement quand un paiement réussit (webhook).",
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Créé par",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tarif spécial vendeur"
        verbose_name_plural = "Tarifs spéciaux vendeurs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["seller", "plan", "is_active"])]

    def clean(self):
        from datetime import timedelta

        from django.core.exceptions import ValidationError

        from subscriptions.services.plans import get_official_price

        errors = {}
        if self.plan not in (Plan.MEDIUM, Plan.PRO):
            errors["plan"] = "Tarif spécial possible sur Medium ou Pro uniquement."
        elif self.price is not None:
            official = get_official_price(self.plan)
            if self.price < SPECIAL_PRICE_MIN:
                errors["price"] = f"Minimum {SPECIAL_PRICE_MIN} FCFA."
            elif self.price > official:
                errors["price"] = (
                    f"Ne peut pas dépasser le prix officiel ({official} FCFA)."
                )
        if self.starts_at and self.expires_at:
            if self.expires_at <= self.starts_at:
                errors["expires_at"] = "Doit être postérieure au début."
            elif self.expires_at > self.starts_at + timedelta(
                days=SPECIAL_PRICE_MAX_DAYS
            ):
                errors["expires_at"] = (
                    f"Au plus {SPECIAL_PRICE_MAX_DAYS} jours après le début."
                )
        if self.max_uses is not None and self.max_uses < 1:
            errors["max_uses"] = "Au moins 1."
        if self.duration_days is not None and self.duration_days < 1:
            errors["duration_days"] = "Au moins 1 jour (ou vide)."
        if errors:
            raise ValidationError(errors)

    def is_usable(self, now=None) -> bool:
        now = now or timezone.now()
        return (
            self.is_active
            and self.starts_at <= now < self.expires_at
            and self.uses_count < self.max_uses
        )

    @property
    def status_label(self) -> str:
        now = timezone.now()
        if not self.is_active:
            return "Désactivé"
        if self.uses_count >= self.max_uses:
            return "Épuisé"
        if now >= self.expires_at:
            return "Expiré"
        if now < self.starts_at:
            return "À venir"
        return "Actif"

    def __str__(self) -> str:
        return (
            f"{self.seller} — {self.get_plan_display()} à {self.price} FCFA "
            f"({self.get_reason_display()})"
        )
