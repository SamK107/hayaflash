from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Journal d'audit forensic — toutes les actions critiques du système."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        verbose_name="Acteur",
    )
    action = models.CharField(max_length=100, db_index=True, verbose_name="Action")
    entity_type = models.CharField(max_length=50, db_index=True, verbose_name="Entité")
    entity_id = models.BigIntegerField(db_index=True, verbose_name="ID entité")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Métadonnées")
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="Adresse IP"
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journaux d'audit"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["action", "timestamp"]),
        ]

    def __str__(self) -> str:
        actor = self.actor_id or "system"
        return f"[{self.timestamp}] {actor} → {self.action} {self.entity_type}#{self.entity_id}"


def audit(
    action: str,
    *,
    entity_type: str,
    entity_id: int,
    actor=None,
    request=None,
    **metadata,
) -> AuditLog:
    """Helper pour créer une entrée d'audit en une ligne.

    Usage::
        from core.models import audit
        audit("order.created", entity_type="Order", entity_id=order.pk,
              request=request, flash_sale_id=sale.pk, total=float(order.total_amount))
    """
    ip = None
    if request is not None:
        actor = actor or (request.user if request.user.is_authenticated else None)
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = x_forwarded.split(",")[0].strip() if x_forwarded else request.META.get("REMOTE_ADDR")

    return AuditLog.objects.create(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
        ip_address=ip,
    )
