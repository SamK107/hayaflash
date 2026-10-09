"""Django admin du programme partenaires.

Commissions et versements sont en LECTURE SEULE : toute modification passe par les
actions des pages équipe (validation, versement, annulation, libération), qui
laissent une trace d'audit.
"""

from __future__ import annotations

from django.contrib import admin

from partners.models import (
    AcceptanceInvalidation,
    CommissionEntry,
    OutboundMessage,
    Partner,
    PartnerAcceptance,
    PartnerAccessLink,
    PartnerClick,
    Payout,
    Referral,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind", "status", "phase", "is_founder", "contract_start", "contract_end", "commission_percent")
    list_filter = ("status", "phase", "kind", "is_founder")
    search_fields = ("name", "code", "phone")
    readonly_fields = ("contract_end", "trial_end", "created_at")
    fields = (
        "name", "phone", "code", "kind", "status", "phase", "shop_name", "cite_shop_consent", "is_founder",
        "trial_start", "trial_end", "contract_start", "contract_end", "commission_percent", "notes", "created_at",
    )

    def get_readonly_fields(self, request, obj=None):
        # Le pourcentage est figé à la création : modifiable seulement à l'ajout.
        base = super().get_readonly_fields(request, obj)
        return base + ("commission_percent",) if obj else base


@admin.register(PartnerClick)
class PartnerClickAdmin(ReadOnlyAdmin):
    list_display = ("partner", "created_at", "ip_hash")
    list_filter = ("partner",)


@admin.register(Referral)
class ReferralAdmin(ReadOnlyAdmin):
    list_display = ("partner", "seller", "source", "attributed_at", "first_paid_at", "commission_ends_at", "flagged")
    list_filter = ("partner", "flagged", "source")
    search_fields = ("seller__user__phone", "seller__business_name")


@admin.register(CommissionEntry)
class CommissionEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "referral", "gross_fcfa", "net_fcfa", "percent", "commission_fcfa", "status")
    list_filter = ("status", "referral__partner")


@admin.register(Payout)
class PayoutAdmin(ReadOnlyAdmin):
    list_display = ("partner", "period", "total_fcfa", "status", "orange_reference", "paid_at")
    list_filter = ("status", "partner")


@admin.register(PartnerAcceptance)
class PartnerAcceptanceAdmin(ReadOnlyAdmin):
    """Preuves d'acceptation : lecture seule, ni modification ni suppression."""

    list_display = ("accepted_at", "partner", "doc_type", "doc_version", "signer_name", "method")
    list_filter = ("doc_type", "doc_version", "method")
    search_fields = ("partner__name", "signer_name")


@admin.register(OutboundMessage)
class OutboundMessageAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "partner", "phone_e164", "template_key")
    list_filter = ("template_key",)


@admin.register(PartnerAccessLink)
class PartnerAccessLinkAdmin(ReadOnlyAdmin):
    """Liens privés : on ne voit jamais le jeton (seule son empreinte existe)."""

    list_display = ("partner", "purpose", "created_at", "expires_at", "revoked_at", "last_viewed_at")
    list_filter = ("purpose",)
    exclude = ("token_hash",)


@admin.register(AcceptanceInvalidation)
class AcceptanceInvalidationAdmin(ReadOnlyAdmin):
    """Invalidations : lecture seule ; elles se créent depuis la page Documents de l'équipe."""

    list_display = ("created_at", "acceptance", "invalidated_by")
