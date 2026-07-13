from __future__ import annotations

import uuid

from django.db import models

from orders.models import Order


class PaymentProvider(models.TextChoices):
    ORANGE_MONEY = "orange_money", "Orange Money"
    MTN = "mtn", "MTN"
    MOOV = "moov", "Moov"


class PaymentTransactionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"


class LedgerEntryType(models.TextChoices):
    DEBIT = "debit", "Debit"
    CREDIT = "credit", "Credit"


class LedgerAccount(models.TextChoices):
    USER_WALLET = "user_wallet", "User wallet"
    PLATFORM_COMMISSION = "platform_commission", "Platform commission"


class PaymentTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="payment_transactions",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=8, default="XOF")
    provider = models.CharField(max_length=32, choices=PaymentProvider.choices)
    status = models.CharField(
        max_length=16,
        choices=PaymentTransactionStatus.choices,
        default=PaymentTransactionStatus.PENDING,
        db_index=True,
    )
    provider_reference = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
    )
    client_reference = models.UUIDField(unique=True, editable=False)
    payer_phone = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Payment {self.id} ({self.status})"


class LedgerEntry(models.Model):
    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(max_length=16, choices=LedgerEntryType.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    account = models.CharField(max_length=64, choices=LedgerAccount.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.entry_type} {self.amount} {self.account}"
