from django import forms

from .models import FlashSale


class FlashSaleForm(forms.ModelForm):
    class Meta:
        model = FlashSale
        fields = ["title", "description", "start_time", "end_time", "delivery_zone", "cover_image", "max_orders"]
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "Ex: Vente Flash Sacs - Vendredi soir",
                "class": "hf-input",
            }),
            "description": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Decrivez votre vente...",
                "class": "hf-input",
            }),
            "start_time": forms.DateTimeInput(attrs={"class": "hf-input", "type": "datetime-local"}),
            "end_time": forms.DateTimeInput(attrs={"class": "hf-input", "type": "datetime-local"}),
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
            "start_time": "Debut *",
            "end_time": "Fin *",
            "delivery_zone": "Zone de livraison",
            "cover_image": "Image de couverture",
            "max_orders": "Plafond de commandes",
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "La fin doit etre apres le debut.")
        return cleaned
