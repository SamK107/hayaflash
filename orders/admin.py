from __future__ import annotations

from django.contrib import admin

from orders.models import Order, OrderItem, PhoneUnblock, UnhonoredOrder


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product",
        "product_name_snapshot",
        "price_snapshot",
        "quantity",
    )
    autocomplete_fields = ("product",)

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "client_request_id",
        "status",
        "customer_name",
        "customer_phone",
        "flash_sale",
        "product",
        "buyer",
        "created_at",
    )
    list_filter = ("status", "flash_sale")
    search_fields = (
        "client_request_id",
        "customer_name",
        "customer_phone",
        "flash_sale__title",
    )
    autocomplete_fields = ("flash_sale", "product", "buyer")
    readonly_fields = ("created_at", "updated_at", "product", "buyer")
    inlines = [OrderItemInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "product",
        "product_name_snapshot",
        "price_snapshot",
        "quantity",
    )
    list_filter = ("order__flash_sale",)
    search_fields = ("product_name_snapshot", "order__client_request_id")
    autocomplete_fields = ("order", "product")
    readonly_fields = (
        "product_name_snapshot",
        "price_snapshot",
        "quantity",
    )


@admin.register(UnhonoredOrder)
class UnhonoredOrderAdmin(admin.ModelAdmin):
    """Commandes non honorées (F-59). Action : débloquer globalement les numéros choisis."""

    list_display = ("id", "order", "phone_key", "seller", "created_at")
    list_filter = ("seller",)
    search_fields = ("phone_key", "order__customer_phone", "order__customer_name")
    readonly_fields = ("order", "phone_key", "seller", "created_at")
    actions = ["unblock_selected_phones"]

    def has_add_permission(self, request) -> bool:
        return False

    @admin.action(description="Débloquer les numéros sélectionnés (toutes les boutiques)")
    def unblock_selected_phones(self, request, queryset):
        from orders.services.unhonored import unblock_phone

        keys = set(queryset.values_list("phone_key", flat=True))
        for key in keys:
            unblock_phone(key, by_user=request.user, seller=None)
        self.message_user(request, f"{len(keys)} numéro(s) débloqué(s) pour toutes les boutiques.")


@admin.register(PhoneUnblock)
class PhoneUnblockAdmin(admin.ModelAdmin):
    list_display = ("id", "phone_key", "seller", "created_by", "created_at")
    list_filter = ("seller",)
    search_fields = ("phone_key",)
    readonly_fields = ("created_at",)
