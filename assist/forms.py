"""Formulaires de la saisie assistee."""

from __future__ import annotations

from django import forms

from flash_sales.forms import FlashSaleForm

WHATSAPP_REF_HELP = (
    "Date et heure du message WhatsApp de la vendeuse (photos, prix, stocks). "
    "Garde ce message : il sert de preuve."
)


class AssistSaleForm(FlashSaleForm):
    """Meme formulaire (et memes regles) que l'interface vendeur, plus la
    reference obligatoire de la demande WhatsApp."""

    whatsapp_ref = forms.CharField(
        max_length=120,
        label="Référence de la demande WhatsApp *",
        help_text=WHATSAPP_REF_HELP,
        widget=forms.TextInput(
            attrs={"class": "hf-input", "placeholder": "Ex : WhatsApp 22/10 18h05"}
        ),
    )

    class Meta(FlashSaleForm.Meta):
        # Les apercus (teasers) et la description vocale restent dans le compte
        # de la vendeuse : create_flash_sale ne les prend pas en charge.
        fields = [f for f in FlashSaleForm.Meta.fields if f != "teasers"]

    def clean_whatsapp_ref(self):
        value = (self.cleaned_data.get("whatsapp_ref") or "").strip()
        if not value:
            raise forms.ValidationError("Indique la référence du message WhatsApp.")
        return value
