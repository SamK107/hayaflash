from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F

from flash_sales.models import FlashSale
from flash_sales.services.ordering import assert_flash_sale_accepts_orders
from orders.models import Order, OrderItem, OrderStatus
from orders.services.dashboard import invalidate_seller_kpi_cache
from products.models import Product


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError({field: "Must be a non-empty string."})
    stripped = value.strip()
    if not stripped:
        raise ValidationError({field: "Must be a non-empty string."})
    return stripped


def _validate_create_order_payload(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValidationError("Payload must be a dictionary.")

    for key in (
        "flash_sale_id",
        "customer_name",
        "customer_phone",
        "client_request_id",
        "items",
        "delivery",
    ):
        if key not in data:
            raise ValidationError({key: "This field is required."})

    if not isinstance(data["delivery"], dict):
        raise ValidationError({"delivery": "Must be a JSON object."})

    if not isinstance(data["flash_sale_id"], int) or data["flash_sale_id"] < 1:
        raise ValidationError({"flash_sale_id": "Must be a positive integer."})

    _require_str(data["customer_name"], "customer_name")
    _require_str(data["customer_phone"], "customer_phone")
    _require_str(data["client_request_id"], "client_request_id")

    items = data["items"]
    if not isinstance(items, list) or not items:
        raise ValidationError({"items": "Must be a non-empty list of line items."})

    for i, row in enumerate(items):
        if not isinstance(row, dict):
            raise ValidationError({"items": f"Line {i} must be an object."})
        if "product_id" not in row or "quantity" not in row:
            raise ValidationError(
                {"items": f"Line {i} must include product_id and quantity."}
            )
        pid = row["product_id"]
        qty = row["quantity"]
        if not isinstance(pid, int) or pid < 1:
            raise ValidationError({"items": f"Line {i}: invalid product_id."})
        if not isinstance(qty, int) or qty < 1:
            raise ValidationError({"items": f"Line {i}: quantity must be >= 1."})


def _aggregate_quantities(items: Iterable[dict[str, Any]]) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for row in items:
        totals[int(row["product_id"])] += int(row["quantity"])
    return dict(totals)


def _create_order_transactional(data: dict[str, Any]) -> Order:
    """
    Runs under transaction.atomic() (see create_order).

    Concurrency: select_for_update() on the idempotency row, flash sale, and
    each product line; stock is decremented with stock_available__gte guard to avoid
    oversell when requests run in parallel.
    """
    flash_sale_id = int(data["flash_sale_id"])
    client_request_id = _require_str(data["client_request_id"], "client_request_id")

    existing = (
        Order.objects.select_for_update()
        .filter(client_request_id=client_request_id)
        .first()
    )
    if existing is not None:
        return existing

    items = data["items"]
    assert isinstance(items, list)
    totals_by_product = _aggregate_quantities(items)

    flash_sale = FlashSale.objects.select_for_update().get(pk=flash_sale_id)
    assert_flash_sale_accepts_orders(flash_sale)

    locked: dict[int, Product] = {}
    for product_id in sorted(totals_by_product):
        product = (
            Product.objects.select_for_update()
            .filter(pk=product_id, flash_sale_id=flash_sale.id)
            .first()
        )
        if product is None:
            raise ValidationError(
                {"items": f"Product {product_id} was not found for this flash sale."}
            )
        need = totals_by_product[product_id]
        if product.stock_available < need:
            raise ValidationError(
                {
                    "items": (
                        f"Insufficient stock for product {product_id} "
                        f"(requested {need}, available {product.stock_available})."
                    )
                }
            )
        locked[product_id] = product

    order = Order.service_objects.create(
        flash_sale=flash_sale,
        customer_name=_require_str(data["customer_name"], "customer_name"),
        customer_phone=_require_str(data["customer_phone"], "customer_phone"),
        status=OrderStatus.PENDING,
        client_request_id=client_request_id,
    )

    for row in items:
        pid = int(row["product_id"])
        qty = int(row["quantity"])
        product = locked[pid]
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            price_snapshot=Decimal(product.price),
            quantity=qty,
        )

    for product_id, need in totals_by_product.items():
        updated = Product.objects.filter(
            pk=product_id,
            stock_available__gte=need,
        ).update(stock_available=F("stock_available") - need)
        if updated != 1:
            raise ValidationError(
                {
                    "items": (
                        f"Stock for product {product_id} changed while placing the order; "
                        "please retry."
                    )
                }
            )

    _record_stock_movements(order=order, totals_by_product=totals_by_product)

    total_amount = _compute_order_total(order)
    order.total_amount = total_amount
    order.save(update_fields=["total_amount", "updated_at"])
    _create_delivery_for_order(order=order, delivery_data=data["delivery"])

    return order


def _record_stock_movements(*, order: Order, totals_by_product: dict[int, int]) -> None:
    """Cree les mouvements de stock RESERVATION pour chaque ligne."""
    from products.models import StockMovement

    movements = [
        StockMovement(
            product_id=product_id,
            order=order,
            quantity_change=-quantity,
            movement_type=StockMovement.MovementType.RESERVATION,
        )
        for product_id, quantity in totals_by_product.items()
    ]
    StockMovement.objects.bulk_create(movements)


def _compute_order_total(order: Order):
    from delivery.services.delivery import compute_order_total
    return compute_order_total(order)


def _create_delivery_for_order(*, order: Order, delivery_data: dict):
    from delivery.services.delivery import create_delivery_for_order
    return create_delivery_for_order(order=order, delivery_data=delivery_data)


def _invalidate_seller_kpi_for_order(order: Order) -> None:
    if not order.flash_sale_id:
        return
    fs = FlashSale.objects.select_related("owner__user").get(pk=order.flash_sale_id)
    invalidate_seller_kpi_cache(fs.owner.user)
    if fs.public_slug and fs.owner.public_slug:
        from analytics.services.cache import invalidate_for_order
        invalidate_for_order(
            flash_sale_id=fs.pk,
            seller_id=fs.owner_id,
            seller_slug=fs.owner.public_slug,
            flash_slug=fs.public_slug,
        )


def create_order(data: dict[str, Any]) -> Order:
    """
    Create an order and line items, or return an existing order for the same
    client_request_id (idempotent retries).
    """
    _validate_create_order_payload(data)
    try:
        with transaction.atomic():
            order = _create_order_transactional(data)
    except IntegrityError:
        try:
            order = Order.objects.get(client_request_id=data["client_request_id"])
        except Order.DoesNotExist:
            raise
    _invalidate_seller_kpi_for_order(order)
    # Notification async (hors transaction, best-effort)
    try:
        from notifications.tasks import send_order_confirmation
        send_order_confirmation.delay(order.pk)
    except Exception:
        pass  # Ne jamais bloquer une commande pour une notif
    return order
