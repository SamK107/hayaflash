from django.db import models
from django.utils import timezone


class Plan(models.TextChoices):
    FREE = "free", "Gratuit"
    PRO  = "pro",  "Pro"


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
        help_text="Null = Free perpetuel ou Pro actif sans expiration",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"

    @property
    def is_pro(self) -> bool:
        if self.plan == Plan.FREE:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def __str__(self) -> str:
        status = "Pro" if self.is_pro else "Gratuit"
        return f"{self.seller.business_name} — {status}"
