from django.contrib import admin

from . import models


class WholesaleProductImageInline(admin.TabularInline):
    model = models.WholesaleProductImage
    extra = 0


@admin.register(models.Distributor)
class DistributorAdmin(admin.ModelAdmin):
    list_display = ("business_name", "user", "is_active", "is_suspended", "pilot_until", "created_at")
    list_filter = ("is_active", "is_suspended")
    search_fields = ("business_name", "user__phone", "contact_phone")
    raw_id_fields = ("user", "created_by")
    fieldsets = (
        (None, {"fields": ("user", "business_name", "contact_phone", "orange_money_number")}),
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

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


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
