# Workflow P2 — Interface Vendeur (CRUD)
> Phase 2 · Durée estimée : ~2 semaines  
> Prérequis : P0 + P1 terminées

---

## Objectif

Implémenter toute l'interface vendeur : créer/modifier des ventes flash, ajouter/modifier des produits, dashboard vendeur amélioré. Un vendeur doit pouvoir créer une vente complète en < 60 secondes.

---

## Étape 2.1 — Flash Sales : Services CRUD

**Nouveau fichier** : `flash_sales/services/crud.py`

```python
"""Services CRUD pour les ventes flash (vendeur authentifié)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from flash_sales.models import FlashSale, FlashSaleStatus


def create_flash_sale(
    *,
    owner,  # SellerProfile
    title: str,
    description: str = "",
    start_time,
    end_time,
    delivery_zone: str = "",
    cover_image=None,
    max_orders: int | None = None,
) -> FlashSale:
    """Crée une nouvelle vente flash pour un vendeur."""
    if end_time <= start_time:
        raise ValidationError("La date de fin doit être après la date de début.")
    if start_time < timezone.now():
        raise ValidationError("La date de début ne peut pas être dans le passé.")

    sale = FlashSale(
        owner=owner,
        title=title.strip(),
        description=description.strip(),
        start_time=start_time,
        end_time=end_time,
        delivery_zone=delivery_zone.strip(),
        max_orders=max_orders,
        status=FlashSaleStatus.SCHEDULED,
    )
    if cover_image:
        sale.cover_image = cover_image
    sale.full_clean()
    sale.save()
    return sale


def update_flash_sale(
    *,
    sale: FlashSale,
    seller,  # SellerProfile — vérification ownership
    **kwargs,
) -> FlashSale:
    """Met à jour une vente (seulement si scheduled)."""
    if sale.owner != seller:
        raise PermissionDenied("Cette vente ne vous appartient pas.")
    if sale.status not in (FlashSaleStatus.SCHEDULED,):
        raise ValidationError("Une vente en cours ou terminée ne peut plus être modifiée.")

    allowed = {"title", "description", "start_time", "end_time", "delivery_zone", "cover_image", "max_orders"}
    for key, value in kwargs.items():
        if key in allowed:
            setattr(sale, key, value)

    sale.full_clean()
    sale.save()
    return sale


def can_seller_create_sale(seller) -> tuple[bool, str]:
    """Vérifie les quotas d'abonnement."""
    # V1 : pas de limite en dev — le module subscriptions l'implémentera
    return True, ""
```

---

## Étape 2.2 — Flash Sales : Forms

**Nouveau fichier** : `flash_sales/forms.py`

```python
from django import forms
from django.utils import timezone

from .models import FlashSale


class FlashSaleForm(forms.ModelForm):
    class Meta:
        model  = FlashSale
        fields = ["title", "description", "start_time", "end_time", "delivery_zone", "cover_image", "max_orders"]
        widgets = {
            "title":         forms.TextInput(attrs={"placeholder": "Ex: Vente Flash Sacs — Vendredi soir", "class": "hf-input"}),
            "description":   forms.Textarea(attrs={"rows": 3, "placeholder": "Décrivez votre vente...", "class": "hf-input"}),
            "start_time":    forms.DateTimeLocalInput(attrs={"class": "hf-input"}),
            "end_time":      forms.DateTimeLocalInput(attrs={"class": "hf-input"}),
            "delivery_zone": forms.TextInput(attrs={"placeholder": "Ex: Bamako, ACI 2000", "class": "hf-input"}),
            "max_orders":    forms.NumberInput(attrs={"placeholder": "Laisser vide = illimité", "min": 1, "class": "hf-input"}),
        }
        labels = {
            "title":         "Titre de la vente *",
            "description":   "Description",
            "start_time":    "Début *",
            "end_time":      "Fin *",
            "delivery_zone": "Zone de livraison",
            "cover_image":   "Image de couverture",
            "max_orders":    "Plafond de commandes",
        }

    def clean(self):
        cleaned = super().clean()
        start  = cleaned.get("start_time")
        end    = cleaned.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "La fin doit être après le début.")
        return cleaned
```

---

## Étape 2.3 — Flash Sales : Views

**Fichier** : `flash_sales/views.py`

```python
"""Views FBV pour la gestion des ventes flash (vendeur authentifié)."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import FlashSaleForm
from .models import FlashSale, FlashSaleStatus
from .services.crud import can_seller_create_sale, create_flash_sale, update_flash_sale


def _get_seller(request):
    """Raccourci : retourne le SellerProfile lié au user."""
    return request.user.sellerprofile


@login_required
def flash_sale_list_view(request):
    seller = _get_seller(request)
    sales  = FlashSale.objects.filter(owner=seller).select_related("owner")
    # Groupage par statut pour les onglets
    ctx = {
        "sales_scheduled": sales.filter(status=FlashSaleStatus.SCHEDULED),
        "sales_live":      sales.filter(status=FlashSaleStatus.LIVE),
        "sales_closed":    sales.filter(status__in=[FlashSaleStatus.CLOSED, FlashSaleStatus.EXECUTING]),
        "sales_done":      sales.filter(status__in=[FlashSaleStatus.COMPLETED, FlashSaleStatus.CANCELLED]),
    }
    return render(request, "flash_sales/list.html", ctx)


@login_required
def flash_sale_create_view(request):
    seller = _get_seller(request)
    can_create, reason = can_seller_create_sale(seller)
    if not can_create:
        messages.error(request, reason)
        return redirect("flash_sales:list")

    form = FlashSaleForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            sale = create_flash_sale(owner=seller, **form.cleaned_data)
            messages.success(request, f"Vente « {sale.title} » créée avec succès !")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "flash_sales/create.html", {"form": form})


@login_required
def flash_sale_detail_view(request, pk: int):
    seller = _get_seller(request)
    sale   = get_object_or_404(FlashSale, pk=pk, owner=seller)
    products = sale.products.prefetch_related("media").order_by("display_order")
    return render(request, "flash_sales/detail.html", {
        "sale": sale,
        "products": products,
    })


@login_required
def flash_sale_edit_view(request, pk: int):
    seller = _get_seller(request)
    sale   = get_object_or_404(FlashSale, pk=pk, owner=seller)
    form   = FlashSaleForm(request.POST or None, request.FILES or None, instance=sale)

    if request.method == "POST" and form.is_valid():
        try:
            update_flash_sale(sale=sale, seller=seller, **form.cleaned_data)
            messages.success(request, "Vente mise à jour.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "flash_sales/create.html", {"form": form, "sale": sale})


@login_required
def flash_sale_open_view(request, pk: int):
    if request.method != "POST":
        return redirect("flash_sales:detail", pk=pk)
    seller = _get_seller(request)
    sale   = get_object_or_404(FlashSale, pk=pk, owner=seller)
    try:
        sale.open_sale()
        messages.success(request, "Vente ouverte ! Les commandes sont acceptées.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("flash_sales:detail", pk=pk)


@login_required
def flash_sale_close_view(request, pk: int):
    if request.method != "POST":
        return redirect("flash_sales:detail", pk=pk)
    seller = _get_seller(request)
    sale   = get_object_or_404(FlashSale, pk=pk, owner=seller)
    try:
        sale.close_sale()
        messages.success(request, "Vente fermée. Vous pouvez traiter les commandes.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("flash_sales:detail", pk=pk)
```

---

## Étape 2.4 — Flash Sales : URLs

**Fichier** : `flash_sales/urls.py`

```python
from django.urls import path
from . import views

app_name = "flash_sales"

urlpatterns = [
    path("",                       views.flash_sale_list_view,   name="list"),
    path("create/",                views.flash_sale_create_view, name="create"),
    path("<int:pk>/",              views.flash_sale_detail_view, name="detail"),
    path("<int:pk>/edit/",         views.flash_sale_edit_view,   name="edit"),
    path("<int:pk>/open/",         views.flash_sale_open_view,   name="open"),
    path("<int:pk>/close/",        views.flash_sale_close_view,  name="close"),
]
```

Ajouter dans `config/urls.py` :
```python
path("seller/flash-sales/", include("flash_sales.urls")),
```

---

## Étape 2.5 — Products : Services CRUD

**Nouveau fichier** : `products/services/crud.py`

```python
from __future__ import annotations
from django.core.exceptions import ValidationError
from products.models import Product, ProductMedia, StockMovement


def create_product(
    *,
    flash_sale,
    name: str,
    price: float,
    stock: int,
    description: str = "",
    unit: str = "pièce",
    characteristics: dict = None,
    display_order: int = 0,
) -> Product:
    if stock < 0:
        raise ValidationError("Le stock ne peut pas être négatif.")
    if price <= 0:
        raise ValidationError("Le prix doit être supérieur à 0.")

    product = Product.objects.create(
        flash_sale=flash_sale,
        name=name.strip(),
        description=description.strip(),
        price=price,
        stock_initial=stock,
        stock_available=stock,
        unit=unit,
        characteristics=characteristics or {},
        display_order=display_order,
    )
    # Log stock initial
    StockMovement.objects.create(
        product=product,
        quantity_change=stock,
        movement_type=StockMovement.MovementType.INITIAL,
        notes="Stock initial à la création du produit",
    )
    return product


def update_product(*, product: Product, **kwargs) -> Product:
    allowed = {"name", "description", "price", "unit", "characteristics", "display_order", "is_active"}
    for key, value in kwargs.items():
        if key in allowed:
            setattr(product, key, value)
    product.full_clean()
    product.save()
    return product


def add_product_image(*, product: Product, image_file, order: int = 0) -> ProductMedia:
    return ProductMedia.objects.create(
        product=product,
        media_type=ProductMedia.MediaType.IMAGE,
        file=image_file,
        order=order,
    )
```

---

## Étape 2.6 — Products : Forms + Views + URLs

**Nouveau fichier** : `products/forms.py`

```python
from django import forms
from .models import Product

class ProductForm(forms.ModelForm):
    image = forms.ImageField(required=False, label="Photo principale")

    class Meta:
        model  = Product
        fields = ["name", "description", "price", "stock_initial", "unit", "display_order"]
        widgets = {
            "name":          forms.TextInput(attrs={"placeholder": "Ex: Sac à main cuir rouge", "class": "hf-input"}),
            "description":   forms.Textarea(attrs={"rows": 2, "class": "hf-input"}),
            "price":         forms.NumberInput(attrs={"placeholder": "5000", "min": 0, "class": "hf-input"}),
            "stock_initial": forms.NumberInput(attrs={"placeholder": "10", "min": 0, "class": "hf-input"}),
            "unit":          forms.TextInput(attrs={"placeholder": "pièce", "class": "hf-input"}),
            "display_order": forms.NumberInput(attrs={"min": 0, "class": "hf-input"}),
        }
        labels = {
            "name":          "Nom du produit *",
            "description":   "Description",
            "price":         "Prix (FCFA) *",
            "stock_initial": "Quantité disponible *",
            "unit":          "Unité",
            "display_order": "Ordre d'affichage",
        }
```

**Fichier** : `products/views.py`

```python
from __future__ import annotations
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from flash_sales.models import FlashSale
from .forms import ProductForm
from .models import Product
from .services.crud import add_product_image, create_product, update_product


def _get_seller(request):
    return request.user.sellerprofile


@login_required
def product_create_view(request, sale_pk: int):
    seller = _get_seller(request)
    sale   = get_object_or_404(FlashSale, pk=sale_pk, owner=seller)
    form   = ProductForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        data   = form.cleaned_data
        image  = data.pop("image", None)
        try:
            product = create_product(flash_sale=sale, stock=data.pop("stock_initial"), **data)
            if image:
                add_product_image(product=product, image_file=image, order=0)
            messages.success(request, f"Produit « {product.name} » ajouté.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "products/product_form.html", {"form": form, "sale": sale})


@login_required
def product_edit_view(request, sale_pk: int, pk: int):
    seller  = _get_seller(request)
    sale    = get_object_or_404(FlashSale, pk=sale_pk, owner=seller)
    product = get_object_or_404(Product, pk=pk, flash_sale=sale)
    form    = ProductForm(request.POST or None, request.FILES or None, instance=product)

    if request.method == "POST" and form.is_valid():
        data  = form.cleaned_data
        image = data.pop("image", None)
        try:
            update_product(product=product, **data)
            if image:
                add_product_image(product=product, image_file=image)
            messages.success(request, "Produit mis à jour.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "products/product_form.html", {"form": form, "sale": sale, "product": product})
```

**Fichier** : `products/urls.py`

```python
from django.urls import path
from . import views

app_name = "products"

urlpatterns = [
    path("<int:sale_pk>/products/create/",       views.product_create_view, name="create"),
    path("<int:sale_pk>/products/<int:pk>/edit/", views.product_edit_view,  name="edit"),
]
```

Ajouter dans `config/urls.py` :
```python
path("seller/flash-sales/", include("products.urls")),
```

---

## Étape 2.7 — Templates vendeur (Tailwind)

### `templates/flash_sales/list.html`
Page principale vendeur : onglets par statut, bouton "Créer une vente", KPI sommaire.

### `templates/flash_sales/create.html`
Formulaire création/édition : champs clairs, validation inline, preview cover_image.

### `templates/flash_sales/detail.html`
Page détail vente : informations, liste produits avec stock, actions (Ouvrir/Fermer), lien vers dashboard LIVE.

### `templates/products/product_form.html`
Formulaire produit : upload image avec preview, champs clairs.

### `templates/seller/home.html` (nouveau)
Landing page vendeur : ses ventes actives, KPI globaux (total commandes ce mois, revenus estimés), bouton "Créer une vente".

---

## Étape 2.8 — URL racine vendeur

**Ajouter dans `config/urls.py`** :
```python
path("seller/", include("core.seller_urls")),
```

**Nouveau fichier** : `core/seller_urls.py`
```python
from django.urls import path
from . import views

urlpatterns = [
    path("", views.seller_home_view, name="seller_home"),
]
```

**Ajouter dans `core/views.py`** :
```python
@login_required
def seller_home_view(request):
    seller = request.user.sellerprofile
    # Ventes actives + récentes
    from flash_sales.models import FlashSale, FlashSaleStatus
    active_sales = FlashSale.objects.filter(
        owner=seller,
        status__in=[FlashSaleStatus.SCHEDULED, FlashSaleStatus.LIVE]
    ).order_by("start_time")[:5]
    return render(request, "seller/home.html", {"active_sales": active_sales})
```

---

## Checklist Finale P2

- [ ] Vendeur connecté peut naviguer vers `/seller/`
- [ ] Vendeur peut créer une vente flash en < 60 secondes
- [ ] Vendeur peut modifier une vente programmée
- [ ] Vendeur peut ajouter un produit avec image
- [ ] Vendeur peut modifier le stock d'un produit
- [ ] Page détail vente affiche les produits avec stock
- [ ] Toutes les pages fonctionnent sur mobile (375px)
- [ ] Messages d'erreur clairs en cas de formulaire invalide
- [ ] `pytest --ds=config.settings.test` passe
