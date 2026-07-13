from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "action",
        "entity_type",
        "entity_id",
        "actor",
        "ip_address",
    )
    list_filter = ("action", "entity_type")
    search_fields = ("action", "entity_type", "actor__phone", "ip_address")
    readonly_fields = (
        "actor",
        "action",
        "entity_type",
        "entity_id",
        "metadata",
        "ip_address",
        "timestamp",
    )
    ordering = ("-timestamp",)

    def has_add_permission(self, request):
        return False  # Audit logs = lecture seule dans l'admin

    def has_change_permission(self, request, obj=None):
        return False
