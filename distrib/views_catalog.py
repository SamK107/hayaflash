"""Catalogue de gros du grossiste (`/distrib/catalogue/`). Cloisonnement : toute requete est
filtree sur `request.distributor`."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .access import distributor_required
from .forms import WholesaleImageForm, WholesaleProductForm
from .models import WholesaleProduct, WholesaleProductImage
from .services import catalog


def _text(exc: ValidationError) -> str:
    return " ".join(exc.messages)


def _product(request, pk: int) -> WholesaleProduct:
    return get_object_or_404(WholesaleProduct, pk=pk, distributor=request.distributor)


@distributor_required
def catalog_list(request):
    products = list(request.distributor.wholesale_products.prefetch_related("images"))
    rows = [
        {"product": p, "allocated": catalog.allocated_total(p), "available": catalog.available_qty(p)}
        for p in products
    ]
    return render(request, "distrib/catalog_list.html", {"distributor": request.distributor, "rows": rows})


@distributor_required
def catalog_create(request):
    form = WholesaleProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                product = catalog.create_wholesale_product(
                    distributor=request.distributor,
                    name=data["name"],
                    description=data["description"],
                    category=data["category"],
                    wholesale_price=data["wholesale_price"],
                    min_retail_price=data["min_retail_price"],
                    stock_total=data["stock_total"],
                    is_active=data["is_active"],
                )
                if data.get("image"):
                    catalog.add_wholesale_image(wholesale_product=product, image_file=data["image"])
        except ValidationError as exc:
            form.add_error(None, _text(exc))
        else:
            messages.success(request, "Produit ajouté au catalogue.")
            return redirect("distrib:catalog_edit", pk=product.pk)
    return render(
        request, "distrib/catalog_form.html", {"distributor": request.distributor, "form": form, "product": None}
    )


@distributor_required
def catalog_edit(request, pk: int):
    product = _product(request, pk)
    if request.method == "POST":
        form = WholesaleProductForm(request.POST)
        form.fields.pop("image")
        if form.is_valid():
            data = form.cleaned_data
            try:
                catalog.update_wholesale_product(
                    wholesale_product=product,
                    name=data["name"],
                    description=data["description"],
                    category=data["category"],
                    wholesale_price=data["wholesale_price"],
                    min_retail_price=data["min_retail_price"],
                    stock_total=data["stock_total"],
                    is_active=data["is_active"],
                )
            except ValidationError as exc:
                form.add_error(None, _text(exc))
            else:
                messages.success(request, "Produit mis à jour.")
                return redirect("distrib:catalog_edit", pk=product.pk)
    else:
        form = WholesaleProductForm.from_instance(product)
        form.fields.pop("image")
    return render(
        request,
        "distrib/catalog_form.html",
        {
            "distributor": request.distributor,
            "form": form,
            "product": product,
            "image_form": WholesaleImageForm(),
            "images": product.images.all(),
            "allocated": catalog.allocated_total(product),
            "available": catalog.available_qty(product),
        },
    )


@distributor_required
@require_POST
def catalog_image_add(request, pk: int):
    product = _product(request, pk)
    form = WholesaleImageForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    else:
        try:
            catalog.add_wholesale_image(wholesale_product=product, image_file=form.cleaned_data["image"])
        except ValidationError as exc:
            messages.error(request, _text(exc))
        else:
            messages.success(request, "Photo ajoutée.")
    return redirect("distrib:catalog_edit", pk=product.pk)


@distributor_required
@require_POST
def catalog_image_delete(request, pk: int, image_pk: int):
    product = _product(request, pk)
    image = get_object_or_404(WholesaleProductImage, pk=image_pk, wholesale_product=product)
    catalog.delete_wholesale_image(image=image)
    messages.success(request, "Photo supprimée.")
    return redirect("distrib:catalog_edit", pk=product.pk)
