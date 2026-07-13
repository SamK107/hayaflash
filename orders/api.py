from __future__ import annotations

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from delivery.services.delivery import delivery_public_snapshot
from orders.models import Order
from orders.services.client_order import submit_public_order_api
from analytics.services.public_pages import build_referral_loop_context


def _flatten_validation_messages(payload: dict) -> str:
    parts: list[str] = []
    for v in payload.values():
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        else:
            parts.append(str(v))
    return " ".join(parts)


def _validation_response(exc: ValidationError) -> tuple[dict, int]:
    detail = getattr(exc, "message_dict", None)
    if not detail:
        msgs = list(getattr(exc, "messages", [str(exc)]))
        detail = {"detail": msgs}
    flat = _flatten_validation_messages(detail)
    if "Too many order attempts" in flat:
        return detail, status.HTTP_429_TOO_MANY_REQUESTS
    return detail, status.HTTP_400_BAD_REQUEST


def _order_response_body(*, order: Order, referral: dict, created_new: bool) -> dict:
    body: dict = {
        "id": order.pk,
        "status": order.status,
        "client_request_id": order.client_request_id,
        "total_amount": str(order.total_amount),
        "referral": referral,
    }
    if hasattr(order, "delivery"):
        body["delivery"] = delivery_public_snapshot(order.delivery)
    elif order.pk:
        from delivery.models import Delivery

        delivery = Delivery.objects.filter(order_id=order.pk).first()
        if delivery is not None:
            body["delivery"] = delivery_public_snapshot(delivery)
    if not created_new:
        body["already_exists"] = True
    return body


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_v1_orders_create(request) -> Response:
    """
    Public order creation: validates input and always calls ``create_order``.
    Idempotent via ``client_request_id`` (see ``orders.services.create_order``).
    """
    body = request.data
    if not isinstance(body, dict):
        return Response(
            {"detail": "JSON object required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        order, created_new = submit_public_order_api(request, body)
    except ValidationError as exc:
        payload, code = _validation_response(exc)
        return Response(payload, status=code)

    product_id = body.get("product_id")
    try:
        product_id_int = int(product_id) if product_id is not None else None
    except (TypeError, ValueError):
        product_id_int = None

    referral = (
        build_referral_loop_context(
            request,
            flash_sale_id=order.flash_sale_id,
            product_id=product_id_int,
            order_id=order.pk,
        )
        if order.flash_sale_id and product_id_int
        else {"available": False}
    )

    response_body = _order_response_body(
        order=order,
        referral=referral,
        created_new=created_new,
    )
    http_status = status.HTTP_201_CREATED if created_new else status.HTTP_200_OK
    return Response(response_body, status=http_status)
