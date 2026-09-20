"""API REST publique pour les ventes flash."""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from .models import FlashSale, FlashSaleStatus
from .serializers import FlashSalePublicSerializer, FlashSaleDetailSerializer


@api_view(["GET"])
@permission_classes([AllowAny])
def flash_sale_list_api(request: Request) -> Response:
    """GET /api/v1/flash-sales/ — ventes scheduled + live.

    Public par design (calendrier des ventes, cf. docs/PROJECT_SPEC.md) : sans
    cet override, DEFAULT_PERMISSION_CLASSES=IsAuthenticated (config/settings/
    base.py) le fait 403 pour tout appelant anonyme — trouve en auditant
    l'ensemble des routes du projet (meme classe de bug que /health/,
    corrige separement dans config/api_urls.py).
    """
    sales = (
        FlashSale.objects.filter(
            status__in=[FlashSaleStatus.SCHEDULED, FlashSaleStatus.LIVE]
        )
        .select_related("owner")
        .order_by("start_time")
    )
    serializer = FlashSalePublicSerializer(
        sales, many=True, context={"request": request}
    )
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def flash_sale_detail_api(request: Request, slug: str) -> Response:
    """GET /api/v1/flash-sales/<slug>/ — detail + produits. Public, voir ci-dessus."""
    try:
        sale = FlashSale.objects.get(public_slug=slug)
    except FlashSale.DoesNotExist:
        return Response(
            {"error": "not_found", "detail": "Vente introuvable."}, status=404
        )

    serializer = FlashSaleDetailSerializer(sale, context={"request": request})
    return Response(serializer.data)
