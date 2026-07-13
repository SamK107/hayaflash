from __future__ import annotations

from django.core.exceptions import ValidationError

from products.models import Product, ProductMedia, StockMovement


def create_product(
    *,
    flash_sale,
    name: str,
    price,
    stock: int,
    description: str = "",
    unit: str = "piece",
    characteristics: dict = None,
    display_order: int = 0,
    description_audio=None,
) -> Product:
    if stock < 0:
        raise ValidationError("Le stock ne peut pas etre negatif.")
    if float(price) <= 0:
        raise ValidationError("Le prix doit etre superieur a 0.")

    product = Product.objects.create(
        flash_sale=flash_sale,
        name=name.strip(),
        description=description.strip() if description else "",
        price=price,
        stock_initial=stock,
        stock_available=stock,
        unit=unit,
        characteristics=characteristics or {},
        display_order=display_order,
    )
    if description_audio:
        product.description_audio = description_audio
        product.save(update_fields=["description_audio"])

    StockMovement.objects.create(
        product=product,
        quantity_change=stock,
        movement_type=StockMovement.MovementType.INITIAL,
        notes="Stock initial a la creation du produit",
    )
    return product


def update_product(*, product: Product, **kwargs) -> Product:
    allowed = {
        "name",
        "description",
        "price",
        "unit",
        "characteristics",
        "display_order",
        "is_active",
        "description_audio",
    }
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
