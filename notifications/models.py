from django.db import models


class Notification(models.Model):
    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS      = "sms",      "SMS"
        EMAIL    = "email",    "Email"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        SENT    = "sent",    "Envoyee"
        FAILED  = "failed",  "Echouee"

    recipient_phone = models.CharField(max_length=20, verbose_name="Destinataire")
    channel         = models.CharField(max_length=20, choices=Channel.choices, verbose_name="Canal")
    message         = models.TextField(verbose_name="Message")
    status          = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True, verbose_name="Statut"
    )
    error_message   = models.TextField(blank=True, verbose_name="Erreur")
    sent_at         = models.DateTimeField(null=True, blank=True, verbose_name="Envoyee le")
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["status", "channel"])]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self) -> str:
        return f"[{self.channel}] -> {self.recipient_phone} ({self.status})"
