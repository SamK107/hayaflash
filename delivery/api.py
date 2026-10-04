from __future__ import annotations

from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from delivery.services.delivery import advance_delivery, list_seller_deliveries


def _validation_response(exc: ValidationError) -> tuple[dict, int]:
    detail = getattr(exc, "message_dict", None)
    if not detail:
        msgs = list(getattr(exc, "messages", [str(exc)]))
        detail = {"detail": msgs}
    return detail, status.HTTP_400_BAD_REQUEST


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_v1_delivery_list(request) -> Response:
    raw_fs = request.query_params.get("flash_sale_id")
    if not raw_fs:
        return Response(
            {"detail": "Le paramètre flash_sale_id est obligatoire."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        flash_sale_id = int(raw_fs)
    except (TypeError, ValueError):
        return Response(
            {"detail": "flash_sale_id doit être un nombre entier."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    status_filter = request.query_params.get("status") or None
    try:
        payload = list_seller_deliveries(
            user=request.user,
            flash_sale_id=flash_sale_id,
            status=status_filter,
        )
    except PermissionDenied:
        return Response(
            {"detail": "Vente flash introuvable ou inaccessible."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def api_v1_delivery_advance(request, delivery_id: UUID) -> Response:
    body = request.data
    if not isinstance(body, dict):
        return Response(
            {"detail": "Un objet JSON est requis."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    action = body.get("action")
    if not isinstance(action, str) or not action.strip():
        return Response(
            {"detail": "Le champ « action » est obligatoire."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        delivery = advance_delivery(
            user=request.user,
            delivery_id=delivery_id,
            action=action.strip(),
            payload=body,
        )
    except PermissionDenied:
        return Response(
            {"detail": "Livraison introuvable ou inaccessible."},
            status=status.HTTP_403_FORBIDDEN,
        )
    except ValidationError as exc:
        payload, code = _validation_response(exc)
        return Response(payload, status=code)

    order = delivery.order
    return Response(
        {
            "delivery_id": str(delivery.pk),
            "status": delivery.status,
            "order_status": order.status,
            "cod_collected": delivery.cod_collected,
            "updated_at": delivery.updated_at.isoformat(),
        },
        status=status.HTTP_200_OK,
    )
