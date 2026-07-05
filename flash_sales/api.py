"""API REST publique pour les ventes flash."""
from __future__ import annotations

from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .models import FlashSale, FlashSaleStatus
from .serializers import FlashSalePublicSerializer, FlashSaleDetailSerializer


@api_view(["GET"])
def flash_sale_list_api(request: Request) -> Response:
    """GET /api/v1/flash-sales/ — ventes scheduled + live."""
    sales = FlashSale.objects.filter(
        status__in=[FlashSaleStatus.SCHEDULED, FlashSaleStatus.LIVE]
    ).select_related("owner").order_by("start_time")
    serializer = FlashSalePublicSerializer(sales, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
def flash_sale_detail_api(request: Request, slug: str) -> Response:
    """GET /api/v1/flash-sales/<slug>/ — detail + produits."""
    try:
        sale = FlashSale.objects.prefetch_related(
            "products__media"
        ).get(public_slug=slug)
    except FlashSale.DoesNotExist:
        return Response({"error": "not_found", "detail": "Vente introuvable."}, status=404)

    serializer = FlashSaleDetailSerializer(sale, context={"request": request})
    return Response(serializer.data)
