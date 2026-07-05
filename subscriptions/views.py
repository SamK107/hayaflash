from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from flash_sales.models import FlashSale
from .services.limits import get_or_create_subscription, FREE_MONTHLY_SALES_LIMIT


@login_required
def subscription_view(request):
    seller = request.user.seller_profile
    sub = get_or_create_subscription(seller)

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sales_this_month = FlashSale.objects.filter(
        owner=seller,
        created_at__gte=month_start,
    ).count()

    return render(request, "subscriptions/subscription.html", {
        "sub": sub,
        "sales_this_month": sales_this_month,
        "free_limit": FREE_MONTHLY_SALES_LIMIT,
    })
