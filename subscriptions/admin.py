from __future__ import annotations

from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import F
from django.utils import timezone
from django.utils.html import format_html

from core.models import audit

from .models import (
    Plan,
    PlanConfig,
    SellerPriceOverride,
    Subscription,
    SubscriptionPayment,
)


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
        # format_html : l'ancien `allow_tags` n'existe plus depuis Django 2.0, la
        # chaine brute etait echappee et le HTML s'affichait en texte.
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:9999px;font-size:.75rem;font-weight:700;">{}</span>',
            color,
            label,
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("seller__user")


# -- SubscriptionPaymentAdmin -------------------------------------------------

@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display  = ["seller", "plan", "amount", "is_special_price", "provider", "status", "created_at"]
    list_filter   = ["status", "plan", "provider", "is_special_price"]
    search_fields = ["seller__business_name", "seller__user__phone", "order_id"]
    readonly_fields = [
        "id",
        "order_id",
        "notif_token",
        "txn_id",
        "raw_response",
        "raw_callback",
        "price_override",
        "is_special_price",
        "created_at",
        "updated_at",
        "paid_at",
    ]
    ordering = ["-created_at"]


# -- PlanConfig : tarifs, quotas, durees (sans redeploiement) -----------------

PLAN_CONFIG_AUDITED_FIELDS = (
    "price",
    "monthly_sales_limit",
    "duration_days",
    "features",
    "is_active",
)


@admin.register(PlanConfig)
class PlanConfigAdmin(admin.ModelAdmin):
    """3 lignes fixes (une par plan) : edition seulement, pas d'ajout ni de suppression."""

    list_display = [
        "plan",
        "price",
        "monthly_sales_limit_display",
        "duration_days",
        "is_active",
        "updated_at",
        "updated_by",
    ]
    readonly_fields = ["plan", "updated_at", "updated_by"]
    fieldsets = [
        (
            None,
            {
                "description": (
                    "Attention : un changement s'applique aux NOUVEAUX paiements uniquement : "
                    "les paiements existants gardent leur montant, les abonnements en "
                    "cours leur échéance. Quota et fonctionnalités s'appliquent tout "
                    "de suite (cache de 60 s). Montants en FCFA entiers."
                ),
                "fields": [
                    "plan",
                    "price",
                    "monthly_sales_limit",
                    "duration_days",
                    "features",
                    "is_active",
                    "updated_at",
                    "updated_by",
                ],
            },
        )
    ]

    @admin.display(description="Ventes / mois", ordering="monthly_sales_limit")
    def monthly_sales_limit_display(self, obj):
        return "Illimité" if obj.monthly_sales_limit is None else obj.monthly_sales_limit

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = {}
        if obj.pk:
            old = PlanConfig.objects.get(pk=obj.pk)
            before = {f: getattr(old, f) for f in PLAN_CONFIG_AUDITED_FIELDS}
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        after = {f: getattr(obj, f) for f in PLAN_CONFIG_AUDITED_FIELDS}
        audit(
            "plan_config.updated",
            entity_type="PlanConfig",
            entity_id=obj.pk,
            request=request,
            plan=obj.plan,
            changes={
                f: {"avant": before.get(f), "apres": after[f]}
                for f in PLAN_CONFIG_AUDITED_FIELDS
                if before.get(f) != after[f]
            },
        )


# -- SellerPriceOverride : tarif special pour UN vendeur ----------------------

OVERRIDE_AUDITED_FIELDS = (
    "seller_id",
    "plan",
    "price",
    "duration_days",
    "reason",
    "reason_detail",
    "starts_at",
    "expires_at",
    "max_uses",
    "is_active",
)


def _override_snapshot(obj) -> dict:
    snap = {}
    for f in OVERRIDE_AUDITED_FIELDS:
        value = getattr(obj, f)
        snap[f] = value.isoformat() if hasattr(value, "isoformat") else value
    return snap


class OverrideStatusFilter(admin.SimpleListFilter):
    title = "statut"
    parameter_name = "statut"

    def lookups(self, request, model_admin):
        return [
            ("actif", "Actif"),
            ("expire", "Expiré"),
            ("epuise", "Épuisé"),
            ("desactive", "Désactivé"),
        ]

    def queryset(self, request, queryset):
        now = timezone.now()
        value = self.value()
        if value == "desactive":
            return queryset.filter(is_active=False)
        if value == "epuise":
            return queryset.filter(is_active=True, uses_count__gte=F("max_uses"))
        if value == "expire":
            return queryset.filter(is_active=True, expires_at__lte=now).exclude(
                uses_count__gte=F("max_uses")
            )
        if value == "actif":
            return queryset.filter(
                is_active=True,
                starts_at__lte=now,
                expires_at__gt=now,
                uses_count__lt=F("max_uses"),
            )
        return queryset


@admin.action(description="Désactiver maintenant")
def deactivate_overrides(modeladmin, request, queryset):
    count = 0
    for override in queryset.filter(is_active=True):
        override.is_active = False
        override.save(update_fields=["is_active", "updated_at"])
        audit(
            "price_override.deactivated",
            entity_type="SellerPriceOverride",
            entity_id=override.pk,
            request=request,
            seller_id=override.seller_id,
            plan=override.plan,
            price=override.price,
        )
        count += 1
    messages.success(request, f"{count} tarif(s) spécial(aux) désactivé(s).")


@admin.register(SellerPriceOverride)
class SellerPriceOverrideAdmin(admin.ModelAdmin):
    list_display = [
        "seller",
        "plan",
        "price",
        "reason",
        "status",
        "uses_display",
        "expires_at",
        "created_by",
    ]
    list_filter = [OverrideStatusFilter, "plan", "reason"]
    search_fields = ["seller__business_name", "seller__seller_code", "seller__user__phone"]
    autocomplete_fields = ["seller"]
    readonly_fields = ["uses_count", "created_by", "created_at", "updated_at"]
    actions = [deactivate_overrides]
    fieldsets = [
        (
            None,
            {
                "description": (
                    "Tarif réservé à CE vendeur, sans effet sur les autres. Entre 100 FCFA "
                    "et le prix officiel, 30 jours maximum. Le montant est appliqué côté "
                    "serveur au paiement ; « Utilisations » n'augmente qu'au paiement "
                    "réussi. Impossible si le vendeur a déjà un abonnement payant actif "
                    "(utiliser un compte vendeur de test)."
                ),
                "fields": [
                    "seller",
                    "plan",
                    "price",
                    "duration_days",
                    ("reason", "reason_detail"),
                    ("starts_at", "expires_at"),
                    ("max_uses", "uses_count"),
                    "is_active",
                    ("created_by", "created_at", "updated_at"),
                ],
            },
        )
    ]

    @admin.display(description="Statut")
    def status(self, obj):
        return obj.status_label

    @admin.display(description="Utilisations")
    def uses_display(self, obj):
        return f"{obj.uses_count}/{obj.max_uses}"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("seller", "created_by")

    def save_model(self, request, obj, form, change):
        before = {}
        if change and obj.pk:
            before = _override_snapshot(SellerPriceOverride.objects.get(pk=obj.pk))
        else:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        after = _override_snapshot(obj)
        audit(
            "price_override.updated" if change else "price_override.created",
            entity_type="SellerPriceOverride",
            entity_id=obj.pk,
            request=request,
            changes={
                f: {"avant": before.get(f), "apres": after[f]}
                for f in OVERRIDE_AUDITED_FIELDS
                if before.get(f) != after[f]
            },
        )
