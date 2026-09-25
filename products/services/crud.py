from __future__ import annotations

from django.core.exceptions import ValidationError

from products.models import FlashSaleProduct, Product, ProductMedia, StockMovement


def create_product(
    *,
    owner,
    name: str,
    price,
    stock: int,
    description: str = "",
    unit: str = "piece",
    characteristics: dict = None,
    display_order: int = 0,
    description_audio=None,
) -> Product:
    """Cree un produit dans le catalogue permanent d'un vendeur.

    Ne rattache plus a une vente : voir `attach_product_to_sale` pour ca.
    """
    if stock < 0:
        raise ValidationError("Le stock ne peut pas être négatif.")
    if float(price) <= 0:
        raise ValidationError("Le prix doit être supérieur à 0.")

    product = Product.objects.create(
        owner=owner,
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
        notes="Stock initial à la création du produit",
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


def attach_product_to_sale(
    *,
    flash_sale,
    product: Product,
    promo_price=None,
    display_order: int = 0,
    is_active: bool = True,
) -> FlashSaleProduct:
    """Cree ou met a jour le lien produit <-> vente (upsert).

    Point d'entree unique reutilise par la vue classique d'ajout de produit
    et par l'endpoint bulk de la page Publication rapide, pour ne pas
    dupliquer cette logique.
    """
    fsp, _created = FlashSaleProduct.objects.update_or_create(
        flash_sale=flash_sale,
        product=product,
        defaults={
            "promo_price": promo_price,
            "display_order": display_order,
            "is_active": is_active,
        },
    )
    return fsp


def adjust_stock(*, product: Product, new_stock_available: int, notes: str = "") -> Product:
    """Corrige le stock disponible d'un produit catalogue (ex: depuis la
    grille Publication rapide) en gardant une trace dans StockMovement,
    plutot que d'ecraser silencieusement `stock_available`.
    """
    if new_stock_available < 0:
        raise ValidationError("Le stock ne peut pas être négatif.")
    delta = new_stock_available - product.stock_available
    if delta == 0:
        return product
    product.stock_available = new_stock_available
    product.save(update_fields=["stock_available", "updated_at"])
    StockMovement.objects.create(
        product=product,
        quantity_change=delta,
        movement_type=StockMovement.MovementType.CORRECTION,
        notes=notes or "Ajustement stock (Publication rapide)",
    )
    return product


def products_for_sale(flash_sale, *, only_active: bool = True) -> list[Product]:
    """Produits d'une vente, ordonnes/filtres selon la config DE CETTE VENTE
    (FlashSaleProduct.display_order/is_active), avec le prix effectif de la
    vente (promo_price si defini) applique sur l'attribut `.price` en
    memoire (jamais persiste en base).

    Retourne une liste de `Product` (pas un queryset ni des FlashSaleProduct)
    pour que les templates/serializers existants, qui font deja
    `product.name`, `product.media.all`, `product.price`, etc., continuent
    de fonctionner sans changement.
    """
    qs = (
        FlashSaleProduct.objects.filter(flash_sale=flash_sale)
        .select_related("product")
        .prefetch_related("product__media")
        .order_by("display_order", "-created_at")
    )
    if only_active:
        qs = qs.filter(is_active=True, product__is_active=True)

    products = []
    for link in qs:
        product = link.product
        product.price = link.effective_price
        product.display_order = link.display_order
        products.append(product)
    return products
