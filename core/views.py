from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.generic import TemplateView


def home(request):
    return render(request, "core/home.html")


class LoginPageView(TemplateView):
    template_name = "accounts/login.html"


class RegisterPageView(TemplateView):
    template_name = "accounts/register.html"


@login_required
def seller_home_view(request):
    from flash_sales.models import FlashSale, FlashSaleStatus
    from orders.models import Order

    seller = request.user.seller_profile

    active_sales = FlashSale.objects.filter(
        owner=seller,
        status__in=[FlashSaleStatus.SCHEDULED, FlashSaleStatus.LIVE],
    ).order_by("start_time")[:5]

    recent_sales = FlashSale.objects.filter(
        owner=seller,
        status__in=[FlashSaleStatus.COMPLETED, FlashSaleStatus.CLOSED, FlashSaleStatus.EXECUTING],
    ).order_by("-start_time")[:3]

    total_orders = Order.objects.filter(flash_sale__owner=seller).count()

    return render(request, "seller/home.html", {
        "active_sales": active_sales,
        "recent_sales": recent_sales,
        "total_orders": total_orders,
    })
