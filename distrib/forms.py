"""Formulaires du module Distrib (textes en francais, FCFA entiers)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from core.choices import SaleCategory

from .services.phones import CALLING_CODE_CHOICES, DEFAULT_CALLING_CODE, build_e164

_INPUT = {"class": "hf-input"}


class PhoneFieldsMixin:
    """Selecteur d'indicatif + numero national -> `cleaned_data["phone_e164"]`."""

    def _clean_phone(self, code_key="calling_code", number_key="phone", out_key="phone_e164", required=True):
        code = self.cleaned_data.get(code_key, "")
        number = self.cleaned_data.get(number_key, "")
        if not number and not required:
            self.cleaned_data[out_key] = ""
            return
        phone, error = build_e164(code, number)
        if error:
            self.add_error(number_key, error)
        else:
            self.cleaned_data[out_key] = phone


class DistributorCreateForm(PhoneFieldsMixin, forms.Form):
    business_name = forms.CharField(
        label="Nom commercial", max_length=160, widget=forms.TextInput(attrs=_INPUT)
    )
    display_name = forms.CharField(
        label="Nom de la personne de contact", max_length=150, widget=forms.TextInput(attrs=_INPUT)
    )
    calling_code = forms.ChoiceField(
        label="Indicatif", choices=CALLING_CODE_CHOICES, initial=DEFAULT_CALLING_CODE,
        widget=forms.Select(attrs=_INPUT),
    )
    phone = forms.CharField(
        label="Téléphone de connexion", max_length=30,
        widget=forms.TextInput(attrs={**_INPUT, "inputmode": "tel", "placeholder": "70 00 00 00"}),
    )
    orange_money_number = forms.CharField(
        label="Numéro Orange Money (même pays)", max_length=30, required=False,
        widget=forms.TextInput(attrs={**_INPUT, "inputmode": "tel", "placeholder": "facultatif"}),
    )
    commission_rate = forms.DecimalField(
        label="Taux de commission (%)", min_value=Decimal("0"), max_value=Decimal("100"),
        max_digits=5, decimal_places=2, initial=Decimal("6"),
        widget=forms.NumberInput(attrs={**_INPUT, "step": "0.5"}),
    )
    pilot_until = forms.DateField(
        label="Commission offerte jusqu'au", required=False,
        widget=forms.DateInput(attrs=_INPUT, format="%Y-%m-%d"),
        help_text="Période d'essai : avant cette date, aucune commission n'est facturable.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pilot_until"].widget.input_type = "date"
        self.fields["pilot_until"].initial = timezone.localdate() + timedelta(days=60)

    def clean(self):
        cleaned = super().clean()
        if not self.errors:
            self._clean_phone()
        if not self.errors and cleaned.get("orange_money_number"):
            phone, error = build_e164(cleaned["calling_code"], cleaned["orange_money_number"])
            if error:
                self.add_error("orange_money_number", error)
            else:
                cleaned["orange_money_e164"] = phone
        return cleaned


class ResellerInviteForm(PhoneFieldsMixin, forms.Form):
    display_name = forms.CharField(
        label="Nom du revendeur", max_length=120,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "Ex. Awa, boutique Awa"}),
    )
    calling_code = forms.ChoiceField(
        label="Indicatif", choices=CALLING_CODE_CHOICES, initial=DEFAULT_CALLING_CODE,
        widget=forms.Select(attrs=_INPUT),
    )
    phone = forms.CharField(
        label="Téléphone", max_length=30,
        widget=forms.TextInput(attrs={**_INPUT, "inputmode": "tel", "placeholder": "70 00 00 00"}),
    )

    def clean(self):
        cleaned = super().clean()
        if not self.errors:
            self._clean_phone()
        return cleaned


class WholesaleProductForm(forms.Form):
    """Montants en FCFA entiers : `IntegerField`, jamais de decimales."""

    name = forms.CharField(label="Nom du produit", max_length=255, widget=forms.TextInput(attrs=_INPUT))
    description = forms.CharField(
        label="Description", required=False, widget=forms.Textarea(attrs={**_INPUT, "rows": 3})
    )
    category = forms.ChoiceField(
        label="Catégorie", required=False,
        choices=[("", "—")] + list(SaleCategory.choices), widget=forms.Select(attrs=_INPUT),
    )
    wholesale_price = forms.IntegerField(
        label="Prix de gros (FCFA)", min_value=1,
        widget=forms.NumberInput(attrs={**_INPUT, "inputmode": "numeric"}),
    )
    min_retail_price = forms.IntegerField(
        label="Prix de vente minimum (FCFA)", min_value=1,
        widget=forms.NumberInput(attrs={**_INPUT, "inputmode": "numeric"}),
        help_text="Le revendeur ne pourra pas vendre en dessous.",
    )
    stock_total = forms.IntegerField(
        label="Stock total", min_value=0,
        widget=forms.NumberInput(attrs={**_INPUT, "inputmode": "numeric"}),
    )
    is_active = forms.BooleanField(label="Visible par les revendeurs", required=False, initial=True)
    image = forms.ImageField(label="Photo (facultative)", required=False)

    @classmethod
    def from_instance(cls, wp):
        return cls(
            initial={
                "name": wp.name, "description": wp.description, "category": wp.category,
                "wholesale_price": int(wp.wholesale_price), "min_retail_price": int(wp.min_retail_price),
                "stock_total": wp.stock_total, "is_active": wp.is_active,
            }
        )


class WholesaleImageForm(forms.Form):
    image = forms.ImageField(label="Ajouter une photo")


class ReceiptLookupForm(PhoneFieldsMixin, forms.Form):
    """Acces 2 (§15.3) : numero (indicatif choisi) + code de commande a 4 chiffres."""

    calling_code = forms.ChoiceField(
        label="Indicatif", choices=CALLING_CODE_CHOICES, initial=DEFAULT_CALLING_CODE,
        widget=forms.Select(attrs=_INPUT),
    )
    phone = forms.CharField(
        label="Téléphone de la commande", max_length=30,
        widget=forms.TextInput(attrs={**_INPUT, "inputmode": "tel", "placeholder": "70 00 00 00"}),
    )
    code = forms.RegexField(
        regex=r"^\s*\d{4}\s*$", label="Code de commande (4 chiffres)", max_length=8,
        error_messages={"invalid": "Le code a 4 chiffres."},
        widget=forms.TextInput(attrs={**_INPUT, "inputmode": "numeric", "maxlength": "4", "autocomplete": "off"}),
    )

    def clean(self):
        cleaned = super().clean()
        if not self.errors:
            self._clean_phone()
            if "code" in cleaned:
                cleaned["code"] = cleaned["code"].strip()
        return cleaned
