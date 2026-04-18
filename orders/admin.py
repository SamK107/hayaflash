from __future__ import annotations

from django.contrib import admin

from orders.models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "buyer", "created_at")
    list_filter = ("product__flash_sale",)
    autocomplete_fields = ("product", "buyer")
    readonly_fields = ("created_at",)
