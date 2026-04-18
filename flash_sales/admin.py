from __future__ import annotations

from django.contrib import admin

from flash_sales.models import FlashSale
from products.models import Product


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0
    fields = ("name",)
    show_change_link = True


@admin.register(FlashSale)
class FlashSaleAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "start_time", "end_time", "is_live_display")
    list_filter = ("status", "owner")
    search_fields = ("title", "owner__seller_code", "owner__business_name")
    autocomplete_fields = ("owner",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "start_time"
    inlines = (ProductInline,)

    fieldsets = (
        (None, {"fields": ("title", "owner", "status")}),
        ("Schedule", {"fields": ("start_time", "end_time")}),
        ("Meta", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Live window", boolean=True)
    def is_live_display(self, obj: FlashSale) -> bool:
        return obj.is_live()
