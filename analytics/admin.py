from django.contrib import admin

from analytics.models import ShareEvent, ShareLink


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = (
        "token",
        "link_type",
        "seller",
        "flash_sale",
        "product",
        "click_count",
        "share_count",
        "conversion_count",
        "created_at",
    )
    list_filter = ("link_type",)
    search_fields = ("token", "seller__seller_code", "flash_sale__title")
    readonly_fields = ("token", "created_at", "updated_at")


@admin.register(ShareEvent)
class ShareEventAdmin(admin.ModelAdmin):
    list_display = ("share_link", "event_type", "source", "order", "created_at")
    list_filter = ("event_type", "source")
    search_fields = ("share_link__token",)
    readonly_fields = ("created_at",)
