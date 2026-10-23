"""Saisie assistee : l'equipe cree une vente et ses produits POUR un vendeur,
sans se connecter a son compte. Reserve au staff. Aucune vue ici ne lit ni ne
modifie mot de passe, telephone ou paiement, et aucun message n'est envoye au
nom du vendeur. Spec : docs/specs/SPEC_00_SAISIE_ASSISTEE.md
"""

from __future__ import annotations

from urllib.parse import quote

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import audit
from flash_sales.models import FlashSale
from flash_sales.services.crud import create_flash_sale
from flash_sales.services.ordering import ORDERABLE_STATUSES
from products.models import FlashSaleProduct
from products.services.crud import products_for_sale

from . import services
from .forms import AssistSaleForm


def _seller(seller_id: int) -> SellerProfile:
    return get_object_or_404(SellerProfile.objects.select_related("user"), pk=seller_id)


def _open_sales(seller):
    return FlashSale.objects.filter(
        owner=seller, status__in=ORDERABLE_STATUSES, end_time__gt=timezone.now()
    ).order_by("start_time")


def _is_open(sale: FlashSale) -> bool:
    return sale.status in ORDERABLE_STATUSES and sale.end_time > timezone.now()


def _shop_name(seller) -> str:
    return seller.business_name or seller.user.display_name or seller.seller_code


def _errors_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)
    return str(exc)


@staff_member_required
def assist_start(request, seller_id: int):
    seller = _seller(seller_id)
    form = AssistSaleForm(request.POST or None, request.FILES or None, seller=seller)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            sale = create_flash_sale(
                owner=seller,
                title=data["title"],
                description=data.get("description", ""),
                start_time=data["start_time"],
                end_time=data["end_time"],
                delivery_zone=data.get("delivery_zone", ""),
                category=data.get("category", ""),
                cover_image=data.get("cover_image"),
                max_orders=data.get("max_orders"),
            )
        except Exception as exc:  # regles metier (quota, creneau...) : meme message que le vendeur
            form.add_error(None, _errors_text(exc))
        else:
            audit(
                "assist.flash_sale_created",
                entity_type="FlashSale",
                entity_id=sale.pk,
                actor=request.user,
                request=request,
                is_admin_action=True,
                acting_for_seller_id=seller.pk,
                whatsapp_ref=data["whatsapp_ref"],
            )
            messages.success(request, "Vente créée. Ajoute maintenant les produits.")
            return redirect("assist:products", seller_id=seller.pk, sale_pk=sale.pk)
    return render(
        request,
        "assist/start.html",
        {
            "seller": seller,
            "shop_name": _shop_name(seller),
            "form": form,
            "open_sales": _open_sales(seller),
        },
    )


@staff_member_required
def assist_products(request, seller_id: int, sale_pk: int):
    seller = _seller(seller_id)
    sale = get_object_or_404(FlashSale, pk=sale_pk, owner=seller)
    if not _is_open(sale):
        messages.warning(
            request,
            f"La vente « {sale.title} » est terminée ou annulée : on ne peut plus y "
            "ajouter de produits. Crée une nouvelle vente pour cette boutique.",
        )
        return redirect("assist:start", seller_id=seller.pk)
    errors: list[str] = []
    if request.method == "POST":
        whatsapp_ref = (request.POST.get("whatsapp_ref") or "").strip()[:120]
        rows, photos, errors = services.parse_rows(request.POST, request.FILES)
        if not whatsapp_ref:
            errors.insert(0, "Indique la référence du message WhatsApp.")
        errors += services.row_errors(rows)
        if not errors:
            try:
                created = services.create_products(
                    request=request,
                    seller=seller,
                    sale=sale,
                    rows=rows,
                    photos=photos,
                    whatsapp_ref=whatsapp_ref,
                )
            except ValidationError as exc:
                errors.append(_errors_text(exc))
            else:
                messages.success(request, f"{len(created)} produit(s) ajouté(s) à la vente.")
                return redirect("assist:done", seller_id=seller.pk, sale_pk=sale.pk)
    return render(
        request,
        "assist/products.html",
        {
            "seller": seller,
            "shop_name": _shop_name(seller),
            "sale": sale,
            "existing": products_for_sale(sale, only_active=False),
            "errors": errors,
            "max_products": services.MAX_PRODUCTS_PER_BATCH,
        },
        status=400 if errors and request.method == "POST" else 200,
    )


@staff_member_required
def assist_done(request, seller_id: int, sale_pk: int):
    seller = _seller(seller_id)
    sale = get_object_or_404(FlashSale, pk=sale_pk, owner=seller)
    public_url = request.build_absolute_uri(f"/f/{sale.public_slug}/")
    digits = "".join(c for c in (seller.user.phone or "") if c.isdigit())
    wa_url = ""
    if digits:
        start = timezone.localtime(sale.start_time)
        text = (
            f"Bonjour, l'équipe HayaFlash a préparé ta vente « {sale.title} » "
            f"({start:%d/%m} à {start:%H}h{start:%M}). Connecte-toi à HayaFlash et "
            "ouvre-la dans ton tableau de bord : vérifie les produits, prix et stocks, "
            "modifie si nécessaire, puis partage-la avec le bouton WhatsApp ou montre "
            "le QR code pendant ton live."
        )
        wa_url = f"https://wa.me/{digits}?text={quote(text)}"
    lines = (
        FlashSaleProduct.objects.filter(flash_sale=sale)
        .select_related("product")
        .order_by("display_order", "created_at")
    )
    return render(
        request,
        "assist/done.html",
        {
            "seller": seller,
            "shop_name": _shop_name(seller),
            "sale": sale,
            "lines": lines,
            "sale_open": _is_open(sale),
            "public_url": public_url,
            "wa_url": wa_url,
        },
    )
