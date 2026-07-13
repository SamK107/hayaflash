from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password

from accounts.models import SellerProfile

User = get_user_model()


class SellerProfileForm(forms.ModelForm):
    """Édition du profil public vendeur."""

    display_name = forms.CharField(
        max_length=150,
        label="Nom d'affichage",
        widget=forms.TextInput(
            attrs={"class": "hf-input", "placeholder": "Votre nom ou pseudo"}
        ),
    )

    class Meta:
        model = SellerProfile
        fields = ["avatar", "business_name", "bio", "delivery_zones"]
        widgets = {
            "avatar": forms.FileInput(attrs={"class": "hidden", "accept": "image/*"}),
            "business_name": forms.TextInput(
                attrs={
                    "class": "hf-input",
                    "placeholder": "Ex : Boutique Aminata Mode",
                }
            ),
            "bio": forms.Textarea(
                attrs={
                    "class": "hf-input",
                    "rows": 3,
                    "placeholder": "Décrivez votre boutique en quelques mots…",
                }
            ),
            "delivery_zones": forms.TextInput(
                attrs={
                    "class": "hf-input",
                    "placeholder": "Ex : Bamako, Kati, Koulikoro",
                }
            ),
        }
        labels = {
            "business_name": "Nom commercial",
            "bio": "Description de la boutique",
            "delivery_zones": "Zones de livraison",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        if user is not None:
            self.fields["display_name"].initial = user.display_name

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self._user is not None:
            new_name = self.cleaned_data.get("display_name", "").strip()
            if new_name and new_name != self._user.display_name:
                self._user.display_name = new_name
                if commit:
                    self._user.save(update_fields=["display_name"])
        if commit:
            profile.save()
        return profile


class ChangePasswordForm(forms.Form):
    """Changement de mot de passe depuis la page Paramètres."""

    current_password = forms.CharField(
        label="Mot de passe actuel",
        widget=forms.PasswordInput(
            attrs={"class": "hf-input", "autocomplete": "current-password"}
        ),
    )
    new_password = forms.CharField(
        label="Nouveau mot de passe",
        min_length=8,
        widget=forms.PasswordInput(
            attrs={"class": "hf-input", "autocomplete": "new-password"}
        ),
    )
    confirm_password = forms.CharField(
        label="Confirmer le nouveau mot de passe",
        widget=forms.PasswordInput(
            attrs={"class": "hf-input", "autocomplete": "new-password"}
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def clean_current_password(self):
        pwd = self.cleaned_data["current_password"]
        if self._user and not check_password(pwd, self._user.password):
            raise forms.ValidationError("Mot de passe actuel incorrect.")
        return pwd

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            self.add_error(
                "confirm_password", "Les mots de passe ne correspondent pas."
            )
        return cleaned

    def save(self):
        if self._user:
            self._user.set_password(self.cleaned_data["new_password"])
            self._user.save(update_fields=["password"])
