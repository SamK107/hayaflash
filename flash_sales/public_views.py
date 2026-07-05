from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from .models import FlashSale, FlashSaleStatus


def public_flash_sale_calendar(request):
    """Page publique : liste des ventes programmees et en cours."""
    now = timezone.now()
    live_sales = (
        FlashSale.objects.filter(status=FlashSaleStatus.LIVE)
        .select_related("owner")
        .prefetch_related("products__media")
        .order_by("end_time")
    )
    scheduled_sales = (
        FlashSale.objects.filter(
            status=FlashSaleStatus.SCHEDULED,
            start_time__gte=now,
        )
        .select_related("owner")
        .order_by("start_time")[:20]
    )
    return render(request, "flash_sales/public_calendar.html", {
        "live_sales": live_sales,
        "scheduled_sales": scheduled_sales,
    })


def public_flash_sale_detail(request, slug):
    """Page publique d'une vente flash (SEO + partage)."""
    sale = get_object_or_404(FlashSale, public_slug=slug)
    products = sale.products.filter(is_active=True).prefetch_related("media").order_by("display_order")
    return render(request, "flash_sales/public_detail.html", {
        "sale": sale,
        "products": products,
    })
