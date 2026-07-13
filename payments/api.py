from __future__ import annotations

from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from payments.services.payments import (
    initiate_payment_for_order,
    payment_public_snapshot,
)
from payments.services.webhooks import WebhookProcessingError, apply_provider_webhook


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
    return detail, status.HTTP_400_BAD_REQUEST


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def initiate_payment_view(request) -> Response:
    body = request.data
    if not isinstance(body, dict):
        return Response(
            {"detail": "JSON object required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        pt, provider_meta = initiate_payment_for_order(
            order_id=body.get("order_id"),
            phone=body.get("phone"),
            provider=body.get("provider"),
            client_reference=body.get("client_reference"),
        )
    except ValidationError as exc:
        payload, code = _validation_response(exc)
        return Response(payload, status=code)

    payload = payment_public_snapshot(pt)
    payload["provider_response"] = provider_meta
    http_status = (
        status.HTTP_200_OK
        if provider_meta.get("idempotent_replay")
        else status.HTTP_201_CREATED
    )
    return Response(payload, status=http_status)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def payment_webhook_view(request) -> Response:
    raw = request.body
    sig = request.headers.get("X-Payment-Signature") or request.META.get(
        "HTTP_X_PAYMENT_SIGNATURE",
    )
    try:
        pt = apply_provider_webhook(raw_body=raw, signature_header=sig)
    except WebhookProcessingError as exc:
        mapping = {
            "signature": status.HTTP_403_FORBIDDEN,
            "misconfigured": status.HTTP_503_SERVICE_UNAVAILABLE,
            "not_found": status.HTTP_404_NOT_FOUND,
        }
        http_status = mapping.get(exc.code, status.HTTP_400_BAD_REQUEST)
        return Response({"detail": str(exc)}, status=http_status)

    return Response(
        {
            "ok": True,
            "payment_id": str(pt.id),
            "status": pt.status,
        },
        status=status.HTTP_200_OK,
    )
