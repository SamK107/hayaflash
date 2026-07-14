from __future__ import annotations

from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone

from .models import SellerProfile, User


class SellerProfileInline(admin.StackedInline):
    model = SellerProfile
    extra = 0
    can_delete = False
    max_num = 1


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("phone",)

    list_display = (
        "phone",
        "display_name",
        "is_staff",
        "is_active",
        "is_phone_verified",
        "date_joined",
    )

    list_filter = ("is_active", "is_staff", "is_phone_verified")

    search_fields = ("phone", "display_name", "email")

    readonly_fields = ("date_joined", "updated_at")

    inlines = [SellerProfileInline]

    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        (
            "Profile",
            {"fields": ("display_name", "email", "is_phone_verified")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important dates",
            {"fields": ("last_login", "date_joined", "updated_at")},
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "display_name", "password1", "password2"),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("phone",)
        return self.readonly_fields

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("seller_profile")


# ── Actions simulation abonnement (depuis la liste vendeurs) ──────────────────

def _seller_set_plan(plan_key, label, days):
    def action(modeladmin, request, queryset):
        from subscriptions.models import Plan, Subscription
        expires = timezone.now() + timedelta(days=days) if days else None
        count = 0
        for profile in queryset.select_related("user"):
            sub, _ = Subscription.objects.get_or_create(
                seller=profile,
                defaults={"plan": Plan.FREE},
            )
            sub.plan = plan_key
            sub.expires_at = expires
            sub.save(update_fields=["plan", "expires_at", "updated_at"])
            count += 1
        suffix = f"{days} jours" if days else "perpetuel"
        messages.success(
            request,
            f"[OK] {count} vendeur(s) passe(s) en plan {label} ({suffix}) -- simulation.",
        )

    action.__name__ = f"seller_plan_{plan_key}"
    action.short_description = (
        f"[Simulation] Plan {label} ({days}j)" if days else f"[Simulation] Plan {label} (perpetuel)"
    )
    return action


_action_free   = _seller_set_plan("free",   "Gratuit", None)
_action_medium = _seller_set_plan("medium", "Medium",  90)
_action_pro    = _seller_set_plan("pro",    "Pro",     90)


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display  = ("seller_code", "user", "business_name", "current_plan", "is_active")
    list_filter   = ("is_active",)
    search_fields = ("seller_code", "business_name", "user__phone", "user__display_name")
    actions = [_action_free, _action_medium, _action_pro]

    @admin.display(description="Plan actuel")
    def current_plan(self, obj):
        try:
            sub = obj.subscription
        except Exception:
            return "—"
        colors = {"free": "#6B7280", "medium": "#5B2EFF", "pro": "#FF4D2E"}
        color = colors.get(sub.plan, "#6B7280")
        return (
            f'<span style="background:{color};color:#fff;padding:2px 8px;'
            f'border-radius:9999px;font-size:.72rem;font-weight:700;">'
            f'{sub.get_plan_display().upper()}</span>'
        )
    current_plan.allow_tags = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").prefetch_related("subscription")
