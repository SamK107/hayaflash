from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from flash_sales.models import FlashSale

from .forms import ProductForm
from .models import FlashSaleProduct
from .services.crud import (
    add_product_image,
    attach_product_to_sale,
    create_product,
    update_product,
)


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
        audio = request.FILES.get("description_audio") or None
        try:
            product = create_product(
                owner=seller, stock=stock, description_audio=audio, **data
            )
            attach_product_to_sale(
                flash_sale=sale,
                product=product,
                display_order=product.display_order,
            )
            if image:
                add_product_image(product=product, image_file=image, order=0)
            messages.success(request, "Produit ajouté.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "products/product_form.html", {"form": form, "sale": sale})


@login_required
def product_edit_view(request, sale_pk: int, pk: int):
    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=sale_pk, owner=seller)
    # L'appartenance du produit a CETTE vente passe desormais par le lien
    # FlashSaleProduct (le catalogue est partageable entre ventes) ; on
    # verifie aussi que le produit appartient bien au vendeur (defense en
    # profondeur, au cas ou un lien orphelin existerait).
    fsp = get_object_or_404(
        FlashSaleProduct.objects.select_related("product"),
        flash_sale=sale,
        product_id=pk,
        product__owner=seller,
    )
    product = fsp.product
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        image = data.pop("image", None)
        data.pop("stock_initial", None)
        audio = request.FILES.get("description_audio") or None
        try:
            if audio:
                data["description_audio"] = audio
            update_product(product=product, **data)
            if image:
                add_product_image(product=product, image_file=image)
            messages.success(request, "Produit mis à jour.")
            return redirect("flash_sales:detail", pk=sale.pk)
        except Exception as e:
            messages.error(request, str(e))

    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "sale": sale,
            "product": product,
        },
    )


@login_required
def quick_publish_view(request, flash_sale_pk: int):
    """Page "Publication rapide" : grille editable pour gerer 20+ produits
    en une fois (catalogue reutilisable + upload d'images groupe). Les
    mutations elles-memes passent par l'API DRF (products/api.py), cette
    vue ne fait que rendre le shell HTML/Alpine avec les URLs d'API.
    """
    from django.urls import reverse

    seller = _get_seller(request)
    sale = get_object_or_404(FlashSale, pk=flash_sale_pk, owner=seller)

    return render(
        request,
        "products/quick_publish.html",
        {
            "flash_sale": sale,
            "api_catalog_url": reverse(
                "flashsaleproduct-catalog", kwargs={"flash_sale_pk": sale.pk}
            ),
            "api_bulk_update_url": reverse(
                "flashsaleproduct-bulk-update", kwargs={"flash_sale_pk": sale.pk}
            ),
            "api_bulk_upload_url": reverse(
                "flashsaleproduct-bulk-upload-images",
                kwargs={"flash_sale_pk": sale.pk},
            ),
            "api_assign_image_url": reverse(
                "flashsaleproduct-assign-image", kwargs={"flash_sale_pk": sale.pk}
            ),
            "api_duplicate_url": reverse(
                "flashsaleproduct-duplicate-from", kwargs={"flash_sale_pk": sale.pk}
            ),
            "api_archive_product_url": reverse(
                "flashsaleproduct-archive-product", kwargs={"flash_sale_pk": sale.pk}
            ),
            "api_delete_product_url": reverse(
                "flashsaleproduct-delete-product", kwargs={"flash_sale_pk": sale.pk}
            ),
            "previous_sales": FlashSale.objects.filter(owner=seller)
            .exclude(pk=sale.pk)
            .order_by("-start_time")[:10],
        },
    )


@staff_member_required
def admin_quick_publish_view(request, seller_id: int, flash_sale_pk: int):
    """Meme page que quick_publish_view, mais pour le support client : un
    staff Django agit pour le compte d'un vendeur (selectionne par
    seller_id), utile en phase de test / accompagnement. Les appels API
    portent ?seller_id=<id> pour que SellerOwnershipMixin resolve le bon
    vendeur (voir products/mixins.py)."""
    from django.urls import reverse

    from accounts.models import SellerProfile

    seller = get_object_or_404(SellerProfile, pk=seller_id)
    sale = get_object_or_404(FlashSale, pk=flash_sale_pk, owner=seller)

    qs = f"?seller_id={seller.pk}"

    return render(
        request,
        "products/quick_publish.html",
        {
            "flash_sale": sale,
            "is_admin": True,
            "impersonated_seller": seller,
            "api_catalog_url": reverse(
                "flashsaleproduct-catalog", kwargs={"flash_sale_pk": sale.pk}
            )
            + qs,
            "api_bulk_update_url": reverse(
                "flashsaleproduct-bulk-update", kwargs={"flash_sale_pk": sale.pk}
            )
            + qs,
            "api_bulk_upload_url": reverse(
                "flashsaleproduct-bulk-upload-images",
                kwargs={"flash_sale_pk": sale.pk},
            )
            + qs,
            "api_assign_image_url": reverse(
                "flashsaleproduct-assign-image", kwargs={"flash_sale_pk": sale.pk}
            )
            + qs,
            "api_duplicate_url": reverse(
                "flashsaleproduct-duplicate-from", kwargs={"flash_sale_pk": sale.pk}
            )
            + qs,
            "api_archive_product_url": reverse(
                "flashsaleproduct-archive-product", kwargs={"flash_sale_pk": sale.pk}
            )
            + qs,
            "api_delete_product_url": reverse(
                "flashsaleproduct-delete-product", kwargs={"flash_sale_pk": sale.pk}
            )
            + qs,
            "previous_sales": FlashSale.objects.filter(owner=seller)
            .exclude(pk=sale.pk)
            .order_by("-start_time")[:10],
        },
    )
