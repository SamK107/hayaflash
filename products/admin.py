from __future__ import annotations

from django.contrib import admin

from products.models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "flash_sale", "created_at")
    list_filter = ("flash_sale",)
    search_fields = ("name", "flash_sale__title")
    autocomplete_fields = ("flash_sale",)
    readonly_fields = ("created_at", "updated_at")
