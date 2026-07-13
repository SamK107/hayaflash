from django.contrib import admin
from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["seller", "plan", "is_pro", "expires_at", "created_at"]
    list_filter = ["plan"]
    search_fields = ["seller__business_name", "seller__user__email"]
    readonly_fields = ["created_at", "updated_at"]
