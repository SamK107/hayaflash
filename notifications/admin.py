from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["recipient_phone", "channel", "status", "created_at", "sent_at"]
    list_filter = ["channel", "status"]
    search_fields = ["recipient_phone", "message"]
    readonly_fields = ["sent_at", "created_at", "updated_at"]
    date_hierarchy = "created_at"
