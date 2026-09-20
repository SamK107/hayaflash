from __future__ import annotations

from django.contrib import admin

from flash_sales.models import FlashSale
from products.models import FlashSaleProduct


class FlashSaleProductInline(admin.TabularInline):
    model = FlashSaleProduct
    extra = 0
    fields = ("product", "promo_price", "display_order", "is_active")
    autocomplete_fields = ("product",)
    show_change_link = True


@admin.register(FlashSale)
class FlashSaleAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "owner",
        "status",
        "start_time",
        "end_time",
        "delivery_zone",
        "is_live_display",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "title",
        "owner__business_name",
        "owner__seller_code",
        "public_slug",
    )
    date_hierarchy = "start_time"
    readonly_fields = ("public_slug", "created_at", "updated_at")
    inlines = (FlashSaleProductInline,)

    fieldsets = (
        (
            "Informations",
            {
                "fields": ("title", "description", "cover_image", "public_slug"),
            },
        ),
        (
            "Planification",
            {
                "fields": ("owner", "start_time", "end_time", "status"),
            },
        ),
        (
            "Parametres",
            {
                "fields": ("delivery_zone", "max_orders"),
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

    @admin.display(description="Fenetre active", boolean=True)
    def is_live_display(self, obj):
        return obj.is_live()
