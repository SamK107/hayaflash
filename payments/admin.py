from django.contrib import admin

from payments.models import LedgerEntry, PaymentTransaction


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    readonly_fields = ("entry_type", "amount", "account", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "amount",
        "currency",
        "provider",
        "status",
        "provider_reference",
        "created_at",
    )
    list_filter = ("status", "provider", "currency")
    search_fields = ("provider_reference", "client_reference", "payer_phone")
    readonly_fields = (
        "id",
        "order",
        "amount",
        "currency",
        "provider",
        "status",
        "provider_reference",
        "client_reference",
        "payer_phone",
        "created_at",
        "updated_at",
    )
    inlines = [LedgerEntryInline]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "transaction",
        "entry_type",
        "amount",
        "account",
        "created_at",
    )
    list_filter = ("entry_type", "account")
    readonly_fields = ("transaction", "entry_type", "amount", "account", "created_at")

    def has_add_permission(self, request) -> bool:
        return False
