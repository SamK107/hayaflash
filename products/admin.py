from __future__ import annotations

from django.contrib import admin

from products.models import Product, ProductMedia, ProductVariant, StockMovement


class ProductMediaInline(admin.TabularInline):
    model = ProductMedia
    extra = 1
    fields = ("media_type", "file", "video_url", "alt_text", "order")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ("type", "value", "stock", "price_delta")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "flash_sale",
        "price",
        "stock_available",
        "stock_initial",
        "unit",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "flash_sale__status")
    search_fields = ("name", "flash_sale__title")
    readonly_fields = ("created_at", "updated_at")
    inlines = [ProductMediaInline, ProductVariantInline]

    fieldsets = (
        (
            "Informations",
            {
                "fields": ("flash_sale", "name", "description", "price", "unit"),
            },
        ),
        (
            "Stock",
            {
                "fields": (
                    "stock_initial",
                    "stock_available",
                    "display_order",
                    "is_active",
                ),
            },
        ),
        (
            "Caracteristiques",
            {
                "fields": ("characteristics",),
                "classes": ("collapse",),
            },
        ),
        (
            "Dates",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "quantity_change",
        "movement_type",
        "order",
        "created_at",
    )
    list_filter = ("movement_type",)
    search_fields = ("product__name",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
