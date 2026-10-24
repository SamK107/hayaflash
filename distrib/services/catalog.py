"""Catalogue de gros du grossiste (spec §4, §5.3). Montants en FCFA entiers."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from core.validators import validate_file_field
from distrib.models import Distributor, ImportedProduct, WholesaleProduct, WholesaleProductImage

MAX_IMAGES = 5


def allocated_total(wholesale_product: WholesaleProduct) -> int:
    """Somme des quantites actuellement allouees aux revendeurs."""
    total = ImportedProduct.objects.filter(wholesale_product=wholesale_product).aggregate(
        t=Sum("allocated_qty")
    )["t"]
    return int(total or 0)


def available_qty(wholesale_product: WholesaleProduct) -> int:
    """Disponible grossiste = stock total − somme des quantites allouees (jamais negatif)."""
    return max(0, wholesale_product.stock_total - allocated_total(wholesale_product))


def _whole_fcfa(value, label: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValidationError(f"{label} : montant invalide.") from exc
    if amount != amount.to_integral_value():
        raise ValidationError(f"{label} : en FCFA entiers, sans centimes.")
    if amount <= 0:
        raise ValidationError(f"{label} doit être supérieur à 0.")
    return amount


def _clean_fields(*, name, wholesale_price, min_retail_price, stock_total) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Indiquez le nom du produit.")
    wholesale = _whole_fcfa(wholesale_price, "Le prix de gros")
    minimum = _whole_fcfa(min_retail_price, "Le prix de vente minimum")
    if minimum < wholesale:
        raise ValidationError(
            "Le prix de vente minimum ne peut pas être inférieur au prix de gros "
            "(le revendeur n'aurait aucune marge)."
        )
    if int(stock_total) < 0:
        raise ValidationError("Le stock total ne peut pas être négatif.")
    return {
        "name": name,
        "wholesale_price": wholesale,
        "min_retail_price": minimum,
        "stock_total": int(stock_total),
    }


def create_wholesale_product(
    *,
    distributor: Distributor,
    name: str,
    wholesale_price,
    min_retail_price,
    stock_total: int,
    description: str = "",
    category: str = "",
    is_active: bool = True,
) -> WholesaleProduct:
    clean = _clean_fields(
        name=name, wholesale_price=wholesale_price,
        min_retail_price=min_retail_price, stock_total=stock_total,
    )
    return WholesaleProduct.objects.create(
        distributor=distributor,
        description=(description or "").strip(),
        category=category or "",
        is_active=is_active,
        **clean,
    )


def update_wholesale_product(
    *,
    wholesale_product: WholesaleProduct,
    name: str,
    wholesale_price,
    min_retail_price,
    stock_total: int,
    description: str = "",
    category: str = "",
    is_active: bool = True,
) -> WholesaleProduct:
    """Mise a jour. Les prix ne touchent que les FUTURES importations ; le stock total ne peut
    pas passer sous les unites deja allouees (reprise d'abord)."""
    clean = _clean_fields(
        name=name, wholesale_price=wholesale_price,
        min_retail_price=min_retail_price, stock_total=stock_total,
    )
    with transaction.atomic():
        wp = WholesaleProduct.objects.select_for_update().get(pk=wholesale_product.pk)
        allocated = allocated_total(wp)
        if clean["stock_total"] < allocated:
            raise ValidationError(
                f"Le stock total ne peut pas être inférieur aux {allocated} unité(s) déjà "
                "allouée(s). Reprenez d'abord du stock chez les revendeurs."
            )
        for key, value in clean.items():
            setattr(wp, key, value)
        wp.description = (description or "").strip()
        wp.category = category or ""
        wp.is_active = is_active
        wp.save()
    return wp


def add_wholesale_image(*, wholesale_product: WholesaleProduct, image_file) -> WholesaleProductImage:
    if wholesale_product.images.count() >= MAX_IMAGES:
        raise ValidationError("Cinq photos au maximum par produit.")
    image = WholesaleProductImage(
        wholesale_product=wholesale_product,
        image=image_file,
        order=wholesale_product.images.count(),
    )
    validate_file_field(image, "image")  # pas de full_clean ici (F-02)
    image.save()
    return image


def delete_wholesale_image(*, image: WholesaleProductImage) -> None:
    """Supprime la photo du catalogue ; les copies deja importees (fichiers copies) restent."""
    wp = image.wholesale_product
    image.delete()
    for index, remaining in enumerate(wp.images.all()):
        if remaining.order != index:
            remaining.order = index
            remaining.save(update_fields=["order"])
