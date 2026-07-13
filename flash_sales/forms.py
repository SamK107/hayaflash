from __future__ import annotations

from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import FlashSale, FlashSaleStatus

MAX_DURATION_MINUTES = 120  # 2 heures — maximum autorise par l'app
MAX_DAILY_OTHER = 3         # max 3 ventes par jour

DURATION_CHOICES = [
    ("60",     "1 heure"),
    ("120",    "2 heures (maximum)"),
    ("custom", "Duree personnalisee (max 2h)"),
]


class FlashSaleForm(forms.ModelForm):
    # Champs virtuels — pas dans le modele
    duration_preset = forms.ChoiceField(
        choices=DURATION_CHOICES,
        label="Duree de la vente *",
        initial="60",
        widget=forms.Select(attrs={"class": "hf-input", "x-model": "durationPreset"}),
    )
    custom_duration_minutes = forms.IntegerField(
        required=False,
        min_value=15,
        max_value=MAX_DURATION_MINUTES,
        label="Duree personnalisee (minutes)",
        widget=forms.NumberInput(attrs={
            "class": "hf-input",
            "placeholder": "Ex: 90 pour 1h30 (max 120)",
            "min": 15,
            "max": MAX_DURATION_MINUTES,
            "x-show": "durationPreset === 'custom'",
            "x-cloak": "",
        }),
    )

    class Meta:
        model = FlashSale
        fields = ["title", "description", "teasers", "start_time", "delivery_zone", "cover_image", "max_orders"]
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "Ex: Vente Flash Sacs - Vendredi soir",
                "class": "hf-input",
            }),
            "description": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Decrivez votre vente : produits, conditions, zone...",
                "class": "hf-input",
            }),
            "teasers": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "8 sacs de luxe\n15 montres dorées\n5 parfums\nBazin satin à prix cassé",
                "class": "hf-input",
                "style": "resize:vertical",
            }),
            "start_time": forms.DateTimeInput(attrs={
                "class": "hf-input",
                "type": "datetime-local",
            }),
            "delivery_zone": forms.TextInput(attrs={
                "placeholder": "Ex: Bamako, ACI 2000",
                "class": "hf-input",
            }),
            "max_orders": forms.NumberInput(attrs={
                "placeholder": "Laisser vide = illimite",
                "min": 1,
                "class": "hf-input",
            }),
        }
        labels = {
            "title": "Titre de la vente *",
            "description": "Description",
            "start_time": "Date et heure de debut *",
            "delivery_zone": "Zone de livraison",
            "cover_image": "Image de couverture",
            "max_orders": "Plafond de commandes",
            "teasers": "Teasers (page d'attente, optionnel)",
        }

    def __init__(self, *args, seller=None, existing_sale_pk=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._seller = seller
        self._existing_sale_pk = existing_sale_pk

        # Pre-remplir les champs virtuels si edition
        instance = kwargs.get("instance")
        if instance and instance.pk and instance.start_time and instance.end_time:
            delta_minutes = int((instance.end_time - instance.start_time).total_seconds() / 60)
            preset_values = {60: "60", 120: "120"}
            if delta_minutes in preset_values:
                self.initial["duration_preset"] = preset_values[delta_minutes]
            else:
                self.initial["duration_preset"] = "custom"
                self.initial["custom_duration_minutes"] = delta_minutes

        # Forcer timezone-aware sur le widget datetime-local
        if instance and instance.start_time:
            local_start = timezone.localtime(instance.start_time)
            self.initial["start_time"] = local_start.strftime("%Y-%m-%dT%H:%M")

    def _compute_duration_minutes(self) -> int | None:
        preset = self.cleaned_data.get("duration_preset")
        if preset == "custom":
            return self.cleaned_data.get("custom_duration_minutes")
        try:
            return int(preset)
        except (TypeError, ValueError):
            return None

    def clean_start_time(self):
        start = self.cleaned_data.get("start_time")
        if start and start < timezone.now() - timedelta(minutes=5):
            raise forms.ValidationError("La date de debut ne peut pas etre dans le passe.")
        return start

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_time")
        preset = cleaned.get("duration_preset")

        if not start or not preset:
            return cleaned

        # Validation duree personnalisee obligatoire
        if preset == "custom":
            custom_min = cleaned.get("custom_duration_minutes")
            if not custom_min:
                self.add_error("custom_duration_minutes", "Precisez la duree en minutes.")
                return cleaned
            duration_minutes = custom_min
        else:
            duration_minutes = int(preset)

        # Plafond absolu
        if duration_minutes > MAX_DURATION_MINUTES:
            self.add_error("duration_preset",
                f"La duree maximale autorisee est de 2 heures ({MAX_DURATION_MINUTES} min).")
            return cleaned

        end_time = start + timedelta(minutes=duration_minutes)
        cleaned["end_time"] = end_time
        cleaned["duration_minutes"] = duration_minutes
        # Mettre à jour l'instance dès maintenant pour que _post_clean()
        # voie le bon end_time et n'échoue pas sur FlashSale.clean()
        self.instance.end_time = end_time

        # Validation des regles journalieres
        if self._seller:
            day = start.date()
            qs = FlashSale.objects.filter(
                owner=self._seller,
                start_time__date=day,
                status__in=[
                    FlashSaleStatus.SCHEDULED,
                    FlashSaleStatus.LIVE,
                    FlashSaleStatus.CLOSED,
                    FlashSaleStatus.EXECUTING,
                ],
            )
            if self._existing_sale_pk:
                qs = qs.exclude(pk=self._existing_sale_pk)

            sales_that_day = list(qs)

            if len(sales_that_day) >= MAX_DAILY_OTHER:
                self.add_error("start_time",
                    f"Vous avez deja {MAX_DAILY_OTHER} ventes ce jour-la. "
                    "Maximum 3 ventes flash par jour.")

        return cleaned
