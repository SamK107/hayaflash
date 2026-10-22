"""Logique de la saisie assistee : lecture et validation des blocs produits,
puis creation via les services existants (aucune regle metier dupliquee)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from core.models import audit
from products.models import FlashSaleProduct
from products.services.crud import add_product_image, attach_product_to_sale, create_product

MAX_PRODUCTS_PER_BATCH = 20
DEFAULT_UNIT = "pièce"


@dataclass
class ProductRow:
    index: int
    name: str = ""
    price: int | None = None
    promo_price: int | None = None
    stock: int | None = None
    unit: str = DEFAULT_UNIT
    errors: list[str] = field(default_factory=list)


def _to_int(raw: str) -> int | None:
    raw = (raw or "").replace(" ", "").replace(" ", "").replace("\xa0", "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError
    if value != value.to_integral_value():
        raise ValueError  # FCFA entiers, jamais de centimes
    return int(value)


def parse_rows(post, files) -> tuple[list[ProductRow], list, list[str]]:
    """Retourne (lignes, photos, erreurs globales)."""
    errors: list[str] = []
    photos = files.getlist("photos")
    try:
        count = int(post.get("count") or 0)
    except ValueError:
        count = 0
    if count < 1:
        errors.append("Ajoute au moins un produit (sélectionne ses photos).")
        return [], photos, errors
    if count > MAX_PRODUCTS_PER_BATCH:
        errors.append(f"{MAX_PRODUCTS_PER_BATCH} produits maximum par envoi.")
        return [], photos, errors
    if len(photos) != count:
        errors.append(
            "Le nombre de photos ne correspond pas au nombre de produits : "
            "resélectionne les photos."
        )

    rows: list[ProductRow] = []
    for i in range(count):
        row = ProductRow(index=i + 1)
        row.name = (post.get(f"name_{i}") or "").strip()[:255]
        row.unit = (post.get(f"unit_{i}") or "").strip()[:50] or DEFAULT_UNIT
        if not row.name:
            row.errors.append("nom manquant")
        values = {}
        for attr, label in (("price", "prix"), ("promo_price", "prix promo"), ("stock", "stock")):
            try:
                values[attr] = _to_int(post.get(f"{attr}_{i}", ""))
            except ValueError:
                row.errors.append(f"{label} invalide (nombre entier attendu)")
                values[attr] = "invalid"
        price, promo, stock = values["price"], values["promo_price"], values["stock"]
        if price is None:
            row.errors.append("prix manquant")
        elif price != "invalid" and price <= 0:
            row.errors.append("le prix doit être supérieur à 0")
        if stock is None:
            row.errors.append("stock manquant")
        elif stock != "invalid" and stock < 0:
            row.errors.append("le stock ne peut pas être négatif")
        if row.errors:
            rows.append(row)
            continue
        row.price, row.promo_price, row.stock = price, promo, stock
        if row.promo_price is not None:
            if row.promo_price <= 0:
                row.errors.append("le prix promo doit être supérieur à 0")
            elif row.promo_price >= row.price:
                row.errors.append("le prix promo doit être inférieur au prix")
        rows.append(row)
    return rows, photos, errors


def row_errors(rows: list[ProductRow]) -> list[str]:
    return [f"Produit {r.index} : {', '.join(r.errors)}." for r in rows if r.errors]


def create_products(*, request, seller, sale, rows: list[ProductRow], photos, whatsapp_ref: str):
    """Tout ou rien : une seule erreur annule l'ensemble du lot."""
    start_order = (
        FlashSaleProduct.objects.filter(flash_sale=sale).aggregate(m=Max("display_order"))["m"]
        or 0
    )
    created = []
    with transaction.atomic():
        for offset, (row, photo) in enumerate(zip(rows, photos), start=1):
            product = create_product(
                owner=seller,
                name=row.name,
                price=row.price,
                stock=row.stock,
                unit=row.unit,
            )
            try:
                add_product_image(product=product, image_file=photo, order=0)
            except ValidationError as exc:
                raise ValidationError(
                    f"Produit {row.index} : photo refusée ({' '.join(exc.messages)})"
                )
            attach_product_to_sale(
                flash_sale=sale,
                product=product,
                promo_price=row.promo_price,
                display_order=start_order + offset,
            )
            audit(
                "assist.product_created",
                entity_type="Product",
                entity_id=product.pk,
                actor=request.user,
                request=request,
                is_admin_action=True,
                acting_for_seller_id=seller.pk,
                flash_sale_id=sale.pk,
                whatsapp_ref=whatsapp_ref,
            )
            created.append(product)
    return created
