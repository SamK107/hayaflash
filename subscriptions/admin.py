from django.contrib import admin
from .models import Subscription, SubscriptionPayment


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["seller", "plan", "is_pro", "expires_at", "created_at"]
    list_filter = ["plan"]
    search_fields = ["seller__business_name", "seller__user__email"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ["seller", "plan", "amount", "provider", "status", "created_at"]
    list_filter = ["status", "plan", "provider"]
    search_fields = ["seller__business_name", "seller__user__phone", "order_id"]
    readonly_fields = [
        "id",
        "order_id",
        "pay_token",
        "txn_id",
        "raw_response",
        "raw_callback",
        "created_at",
        "updated_at",
        "paid_at",
    ]
    ordering = ["-created_at"]
