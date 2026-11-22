from django import forms
from django.contrib import admin, messages

from partners.models import Partner
from partners.services.distributor_attribution import (
    DistributorAttributionError,
    attribute_distributor,
    existing_partner_referral,
)

from . import models


class WholesaleProductImageInline(admin.TabularInline):
    model = models.WholesaleProductImage
    extra = 0


class DistributorAdminForm(forms.ModelForm):
    """Ajoute la saisie de « Apporté par » : enregistrée via le service, une seule fois (D9)."""

    apporte_par = forms.ModelChoiceField(
        queryset=Partner.objects.order_by("name"),
        required=False,
        label="Apporté par (partenaire)",
        help_text="Saisie unique : une fois enregistré, le rattachement ne se modifie pas.",
    )

    class Meta:
        model = models.Distributor
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ref = existing_partner_referral(self.instance)
        if ref is not None:
            self.fields["apporte_par"].initial = ref.partner
            self.fields["apporte_par"].disabled = True


class ApporteParFilter(admin.SimpleListFilter):
    title = "apporté par"
    parameter_name = "apporte_par"

    def lookups(self, request, model_admin):
        options = [(str(p.pk), p.name) for p in Partner.objects.order_by("name")]
        return [("none", "Aucun partenaire")] + options

    def queryset(self, request, queryset):
        value = self.value()
        if value == "none":
            return queryset.filter(partner_referral__isnull=True)
        if value:
            return queryset.filter(partner_referral__partner_id=value)
        return queryset


@admin.register(models.Distributor)
class DistributorAdmin(admin.ModelAdmin):
    form = DistributorAdminForm
    list_display = ("business_name", "user", "apporte_par_display", "is_active", "is_suspended", "pilot_until", "created_at")
    list_filter = ("is_active", "is_suspended", ApporteParFilter)
    search_fields = ("business_name", "user__phone", "contact_phone")
    raw_id_fields = ("user", "created_by")
    fieldsets = (
        (None, {"fields": ("user", "business_name", "contact_phone", "orange_money_number")}),
        ("Partenaire", {"fields": ("apporte_par",)}),
        ("État", {"fields": ("is_active", "is_suspended", "suspended_reason")}),
        ("Commission", {"fields": (
            "commission_rate", "commission_min", "commission_max", "pilot_until",
        )}),
        ("Plafonds et délais", {"fields": (
            "credit_ceiling", "reseller_credit_ceiling", "payout_delay_days", "auto_confirm_hours",
        )}),
        ("Seuils d'alerte (fiabilité)", {"classes": ("collapse",), "fields": (
            "alert_not_delivered_percent", "alert_conflicts", "alert_contested",
        )}),
    )

    @admin.display(description="Apporté par")
    def apporte_par_display(self, obj):
        ref = existing_partner_referral(obj)
        return ref.partner.name if ref is not None else "-"

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        partner = form.cleaned_data.get("apporte_par")
        if partner is not None and existing_partner_referral(obj) is None:
            try:
                attribute_distributor(partner=partner, distributor=obj, actor=request.user)
            except DistributorAttributionError as exc:
                messages.error(request, f"Rattachement non enregistré : {exc}")


@admin.register(models.ResellerInvite)
class ResellerInviteAdmin(admin.ModelAdmin):
    list_display = ("display_name", "phone", "distributor", "status", "seller", "invited_at")
    list_filter = ("status", "distributor")
    search_fields = ("display_name", "phone")
    raw_id_fields = ("seller",)


@admin.register(models.WholesaleProduct)
class WholesaleProductAdmin(admin.ModelAdmin):
    list_display = ("name", "distributor", "wholesale_price", "min_retail_price", "stock_total", "is_active")
    list_filter = ("is_active", "category", "distributor")
    search_fields = ("name",)
    inlines = [WholesaleProductImageInline]


class AllocationMovementInline(admin.TabularInline):
    model = models.AllocationMovement
    extra = 0
    can_delete = False
    readonly_fields = ("quantity_change", "reason", "created_by", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.ImportedProduct)
class ImportedProductAdmin(admin.ModelAdmin):
    list_display = ("wholesale_product", "invite", "product", "allocated_qty", "created_at")
    raw_id_fields = ("product",)
    inlines = [AllocationMovementInline]


@admin.register(models.DistribSettlement)
class DistribSettlementAdmin(admin.ModelAdmin):
    list_display = (
        "pk", "distributor", "invite", "order", "status", "sale_amount",
        "reseller_margin", "commission_amount", "conflict_flag",
    )
    list_filter = ("status", "confirmation_source", "conflict_flag", "distributor")
    raw_id_fields = ("order", "order_item", "imported_product", "statement", "payout")
    readonly_fields = ("receipt_token", "receipt_code")


@admin.register(models.DistribStatement)
class DistribStatementAdmin(admin.ModelAdmin):
    list_display = ("pk", "distributor", "invite", "period_start", "period_end", "amount", "status")
    list_filter = ("status", "distributor")


@admin.register(models.ResellerPayout)
class ResellerPayoutAdmin(admin.ModelAdmin):
    list_display = ("pk", "distributor", "invite", "statement", "attempt", "amount", "status", "paid_at")
    list_filter = ("status", "distributor")


@admin.register(models.DistribPayment)
class DistribPaymentAdmin(admin.ModelAdmin):
    list_display = ("distributor", "amount", "paid_at", "reference")
    list_filter = ("distributor",)

    def save_model(self, request, obj, form, change):
        if obj.recorded_by_id is None:
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(models.DistribCorrection)
class DistribCorrectionAdmin(admin.ModelAdmin):
    list_display = ("settlement", "old_status", "new_status", "reason", "author", "created_at")
    readonly_fields = ("settlement", "old_status", "new_status", "reason", "author", "created_at")

    def has_add_permission(self, request):
        return False
