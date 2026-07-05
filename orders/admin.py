from __future__ import annotations

from django.contrib import admin

from orders.models import Order, OrderItem


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
