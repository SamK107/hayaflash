from __future__ import annotations

from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from django.template.response import TemplateResponse
from django.utils.html import format_html

from accounts.services.suspension import SuspensionError, reactivate_shop, suspend_shop
from core.services.client_ip import get_client_ip

from .models import SellerProfile, ShopReport, User


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


def _suspension_action(*, active: bool):
    """Suspendre / reactiver des boutiques. Motif obligatoire, page de confirmation, AuditLog."""
    label = "Réactiver" if active else "Suspendre"
    service = reactivate_shop if active else suspend_shop
    template = "admin/accounts/sellerprofile/suspension_form.html"

    def action(modeladmin, request, queryset):
        if request.POST.get("apply"):
            reason = request.POST.get("reason", "")
            if not reason.strip():
                messages.error(request, "Le motif est obligatoire : aucune boutique modifiée.")
                return None
            ip = get_client_ip(request)
            ip = None if ip in ("", "unknown") else ip
            done = 0
            for shop in queryset:
                try:
                    service(shop, actor=request.user, reason=reason, ip=ip)
                    done += 1
                except SuspensionError as exc:
                    messages.error(request, f"{shop.business_name or shop.seller_code} : {exc}")
            if done:
                verb = "réactivée(s)" if active else "suspendue(s)"
                messages.success(request, f"[OK] {done} boutique(s) {verb}.")
            return None
        context = {
            **modeladmin.admin_site.each_context(request),
            "opts": modeladmin.model._meta,
            "title": f"{label} la boutique",
            "label": label,
            "active": active,
            "shops": list(queryset),
            "selected": request.POST.getlist(helpers.ACTION_CHECKBOX_NAME),
            "action_name": action.__name__,
        }
        return TemplateResponse(request, template, context)

    action.__name__ = "reactivate_shops" if active else "suspend_shops"
    action.short_description = f"{label} la boutique (motif obligatoire)"
    return action


_action_suspend   = _suspension_action(active=False)
_action_reactivate = _suspension_action(active=True)


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display  = ("seller_code", "user", "business_name", "current_plan", "is_active", "trust_level", "reports_count", "assisted_entry")
    list_filter   = ("is_active", "trust_level")
    search_fields = ("seller_code", "business_name", "user__phone", "user__display_name")
    actions = [_action_free, _action_medium, _action_pro, _action_suspend, _action_reactivate]

    @admin.display(description="Signalements", ordering="_reports_count")
    def reports_count(self, obj):
        count = getattr(obj, "_reports_count", None)
        if count is None:
            count = obj.shop_reports.count()
        if not count:
            return 0
        from django.urls import reverse

        url = reverse("admin:accounts_shopreport_changelist") + f"?shop__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, count)

    @admin.display(description="Plan actuel")
    def current_plan(self, obj):
        try:
            sub = obj.subscription
        except Exception:
            return "—"
        colors = {"free": "#6B7280", "medium": "#5B2EFF", "pro": "#FF4D2E"}
        color = colors.get(sub.plan, "#6B7280")
        # format_html (allow_tags n'existe plus depuis Django 2.0 : le HTML
        # s'affichait en texte brut).
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:.72rem;font-weight:700;">{}</span>',
            color,
            sub.get_plan_display().upper(),
        )

    @admin.display(description="Saisie assistée")
    def assisted_entry(self, obj):
        from django.urls import reverse

        return format_html(
            '<a href="{}">Créer une vente pour cette boutique</a>',
            reverse("assist:start", args=[obj.pk]),
        )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user")
            .prefetch_related("subscription")
            .annotate(_reports_count=Count("shop_reports", distinct=True))
        )


@admin.register(ShopReport)
class ShopReportAdmin(admin.ModelAdmin):
    """Signalements de cliente. Lecture seule sauf statut et note interne ; aucun envoi automatique."""

    list_display = ("created_at", "shop", "reason", "status", "shop_reports_total")
    list_filter = ("status", "reason", ("shop", admin.RelatedOnlyFieldListFilter))
    search_fields = ("shop__business_name", "shop__seller_code", "message")
    list_select_related = ("shop",)
    readonly_fields = ("shop", "reason", "message", "contact", "created_at")
    fields = ("shop", "reason", "message", "contact", "created_at", "status", "internal_note")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        totals = (
            ShopReport.objects.filter(shop_id=OuterRef("shop_id"))
            .values("shop_id")
            .annotate(n=Count("id"))
            .values("n")
        )
        return super().get_queryset(request).annotate(_shop_total=Subquery(totals))

    @admin.display(description="Signalements (boutique)")
    def shop_reports_total(self, obj):
        return obj._shop_total
