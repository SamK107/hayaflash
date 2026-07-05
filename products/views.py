from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from flash_sales.models import FlashSale

from .forms import ProductForm
from .models import Product
from .services.crud import add_product_image, create_product, update_product


def _get_seller(request):
    return request.user.seller_profile


@login_required
def product_create_view(request, sale_pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=sale_pk, owner=seller)
    form = ProductForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        image = data.pop("image", None)
        stock = data.pop("stock_initial")
        try:
            product = create_product(flash_sale=sale, stock=stock, **data)
            if image:
                add_product_image(product=product, image_file=image, order=0)
            messages.success(request, f"Produit ajoute.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "products/product_form.html", {"form": form, "sale": sale})


@login_required
def product_edit_view(request, sale_pk: int, pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=sale_pk, owner=seller)
    product = get_object_or_404(Product, pk=pk, flash_sale=sale)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        image = data.pop("image", None)
        data.pop("stock_initial", None)
        try:
            update_product(product=product, **data)
            if image:
                add_product_image(product=product, image_file=image)
            messages.success(request, "Produit mis a jour.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "products/product_form.html", {
        "form": form, "sale": sale, "product": product,
    })
