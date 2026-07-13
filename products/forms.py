from django import forms

from .models import Product


class ProductForm(forms.ModelForm):
    image = forms.ImageField(required=False, label="Photo principale")

    class Meta:
        model = Product
        fields = [
            "name",
            "description",
            "price",
            "stock_initial",
            "unit",
            "display_order",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Ex: Sac a main cuir rouge",
                    "class": "hf-input",
                }
            ),
            "description": forms.Textarea(attrs={"rows": 2, "class": "hf-input"}),
            "price": forms.NumberInput(
                attrs={"placeholder": "5000", "min": 0, "class": "hf-input"}
            ),
            "stock_initial": forms.NumberInput(
                attrs={"placeholder": "10", "min": 0, "class": "hf-input"}
            ),
            "unit": forms.TextInput(
                attrs={"placeholder": "piece", "class": "hf-input"}
            ),
            "display_order": forms.NumberInput(attrs={"min": 0, "class": "hf-input"}),
        }
        labels = {
            "name": "Nom du produit *",
            "description": "Description",
            "price": "Prix (FCFA) *",
            "stock_initial": "Quantite disponible *",
            "unit": "Unite",
            "display_order": "Ordre d'affichage",
        }
