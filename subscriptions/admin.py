from __future__ import annotations

from datetime import timedelta

from django.contrib import admin, messages
from django.utils import timezone

from .models import Plan, Subscription, SubscriptionPayment


# -- Actions de simulation ----------------------------------------------------

def _set_plan(plan, days):
    label_map = {Plan.FREE: "Gratuit", Plan.MEDIUM: "Medium", Plan.PRO: "Pro"}
    label = label_map[plan]
    suffix = "%d jours" % days if days else "perpetuel"

    def action(modeladmin, request, queryset):
        expires = timezone.now() + timedelta(days=days) if days else None
        updated = queryset.update(plan=plan, expires_at=expires)
        msg = "[OK] %d abonnement(s) passe(s) en %s (%s) -- simulation sans paiement." % (
            updated, label, suffix
        )
        messages.success(request, msg)

    action.__name__ = "set_plan_%s" % plan
    action.short_description = "[Simulation] Plan %s (%s)" % (label, suffix)
    return action


action_set_free   = _set_plan(Plan.FREE,   None)
action_set_medium = _set_plan(Plan.MEDIUM, 90)
action_set_pro    = _set_plan(Plan.PRO,    90)


# -- SubscriptionAdmin --------------------------------------------------------

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display       = ["seller", "plan_badge", "is_paid", "expires_at", "updated_at"]
    list_filter        = ["plan"]
    search_fields      = ["seller__business_name", "seller__user__phone"]
    readonly_fields    = ["created_at", "updated_at"]
    list_display_links = ["seller"]
    actions            = [action_set_free, action_set_medium, action_set_pro]

    @admin.display(description="Plan", ordering="plan")
    def plan_badge(self, obj):
        colors = {Plan.FREE: "#6B7280", Plan.MEDIUM: "#5B2EFF", Plan.PRO: "#FF4D2E"}
        color = colors.get(obj.plan, "#6B7280")
        label = obj.get_plan_display().upper()
        return (
            '<span style="background:%s;color:#fff;padding:2px 10px;'
            'border-radius:9999px;font-size:.75rem;font-weight:700;">%s</span>'
            % (color, label)
        )
    plan_badge.allow_tags = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("seller__user")


# -- SubscriptionPaymentAdmin -------------------------------------------------

@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display  = ["seller", "plan", "amount", "provider", "status", "created_at"]
    list_filter   = ["status", "plan", "provider"]
    search_fields = ["seller__business_name", "seller__user__phone", "order_id"]
    readonly_fields = [
        "id", "order_id", "pay_token", "txn_id",
        "raw_response", "raw_callback",
        "created_at", "updated_at", "paid_at",
    ]
    ordering = ["-created_at"]
