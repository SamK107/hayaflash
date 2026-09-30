from __future__ import annotations

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.rules import SaleRuleError, enforce_creation_rules
from products.models import FlashSaleProduct


class FlashSaleProductInline(admin.TabularInline):
    model = FlashSaleProduct
    extra = 0
    fields = ("product", "promo_price", "display_order", "is_active")
    autocomplete_fields = ("product",)
    show_change_link = True


class FlashSaleAdminForm(forms.ModelForm):
    """Applique les regles metier (quota mensuel, 3 ventes/jour, duree 2 h) a
    l'admin, via la MEME fonction que tous les autres chemins (F-46).

    Verifie a la creation, et a la modification uniquement quand un champ
    controle change (vendeur, dates) ou que la vente est forcee a LIVE : corriger
    un titre ou une zone reste possible meme si le vendeur est deja hors quota.
    """

    class Meta:
        model = FlashSale
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        owner = cleaned.get("owner")
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        if not (owner and start and end):
            return cleaned  # erreurs de champ deja signalees

        pk = self.instance.pk
        if pk is None:
            quota = True
        else:
            changed = set(self.changed_data)
            owner_changed = "owner" in changed
            went_live = (
                "status" in changed and cleaned.get("status") == FlashSaleStatus.LIVE
            )
            if not (owner_changed or went_live or {"start_time", "end_time"} & changed):
                return cleaned
            # Vente deja comptee dans le quota de son vendeur, sauf changement
            # de vendeur ; a LIVE, memes regles qu'a l'ouverture (open_sale).
            quota = owner_changed or went_live
        try:
            enforce_creation_rules(owner, start, end, exclude_pk=pk, quota=quota)
        except SaleRuleError as exc:
            raise ValidationError(exc.messages) from exc
        return cleaned


@admin.register(FlashSale)
class FlashSaleAdmin(admin.ModelAdmin):
    form = FlashSaleAdminForm
    list_display = (
        "title",
        "owner",
        "status",
        "start_time",
        "end_time",
        "delivery_zone",
        "is_live_display",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "title",
        "owner__business_name",
        "owner__seller_code",
        "public_slug",
    )
    date_hierarchy = "start_time"
    readonly_fields = ("public_slug", "created_at", "updated_at")
    inlines = (FlashSaleProductInline,)

    fieldsets = (
        (
            "Informations",
            {
                "fields": ("title", "description", "cover_image", "public_slug"),
            },
        ),
        (
            "Planification",
            {
                "fields": ("owner", "start_time", "end_time", "status"),
            },
        ),
        (
            "Parametres",
            {
                "fields": ("delivery_zone", "max_orders"),
            },
        ),
        (
            "Dates",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Fenetre active", boolean=True)
    def is_live_display(self, obj):
        return obj.is_live()
