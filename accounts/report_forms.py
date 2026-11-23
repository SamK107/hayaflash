"""Formulaire public de signalement d'une boutique (accounts/report_views.py)."""

from __future__ import annotations

from django import forms

from accounts.models import ShopReport

MESSAGE_MAX_LENGTH = 500
CONTACT_MAX_LENGTH = 120


class ShopReportForm(forms.Form):
    reason = forms.ChoiceField(
        choices=ShopReport.Reason.choices,
        label="Motif",
        widget=forms.RadioSelect,
    )
    message = forms.CharField(
        max_length=MESSAGE_MAX_LENGTH,
        required=False,
        label="Ce qui s'est passé (facultatif)",
        widget=forms.Textarea(attrs={"rows": 4, "class": "hf-input"}),
    )
    contact = forms.CharField(
        max_length=CONTACT_MAX_LENGTH,
        required=False,
        label="Ton contact, si tu veux qu'on te réponde (facultatif)",
        widget=forms.TextInput(attrs={"class": "hf-input", "autocomplete": "off"}),
    )
