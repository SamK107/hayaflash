from django.contrib import admin

from delivery.models import Delivery


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "status",
        "cod_amount",
        "cod_collected",
        "address_preview",
        "created_at",
    )
    list_filter = ("status", "cod_collected", "geo_method")
    search_fields = ("order__pk", "address_text", "assigned_to")
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="Address")
    def address_preview(self, obj: Delivery) -> str:
        text = obj.address_text or ""
        return text[:60] + ("…" if len(text) > 60 else "")
