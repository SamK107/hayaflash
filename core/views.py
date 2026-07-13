from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render

from accounts.models import SellerProfile
from accounts.services.users import get_user_by_phone


# ── helpers ────────────────────────────────────────────────────────────────


def _normalize(raw: str) -> str:
    """Normalize phone: strip spaces, ensure leading +."""
    phone = raw.strip().replace(" ", "").replace("-", "")
    if phone and not phone.startswith("+"):
        # assume Mali (+223) if no country code and starts with 0 or 7/6/9
        if phone.startswith("0"):
            phone = "+223" + phone[1:]
        else:
            phone = "+223" + phone
    return phone


def _phone_errors(
    phone: str, password: str, password2: str, business_name: str
) -> list[str]:
    errs = []
    if not phone:
        errs.append("Le numero de telephone est obligatoire.")
    if not business_name.strip():
        errs.append("Le nom de votre boutique est obligatoire.")
    if len(password) < 6:
        errs.append("Le mot de passe doit contenir au moins 6 caracteres.")
    if password != password2:
        errs.append("Les deux mots de passe ne correspondent pas.")
    return errs


# ── views ──────────────────────────────────────────────────────────────────


def home(request):
    # La page marketing est accessible à tous (vendeur connecté ou simple visiteur).
    # Le template adapte la navbar selon l'état d'authentification.
    return render(request, "core/home.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("seller_home")

    error = None

    if request.method == "POST":
        raw_phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")

        if not raw_phone or not password:
            error = "Veuillez renseigner votre telephone et votre mot de passe."
        else:
            phone = _normalize(raw_phone)
            user = authenticate(request, username=phone, password=password)
            if user is not None:
                login(request, user)
                next_url = request.GET.get("next") or "seller_home"
                return redirect(next_url)
            else:
                error = "Numero de telephone ou mot de passe incorrect."

    return render(request, "accounts/login.html", {"error": error})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("seller_home")

    errors = []
    form_data = {}

    if request.method == "POST":
        raw_phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        business_name = request.POST.get("business_name", "").strip()

        form_data = {
            "phone": raw_phone,
            "business_name": business_name,
        }

        phone = _normalize(raw_phone)
        errors = _phone_errors(phone, password, password2, business_name)

        if not errors:
            # verifier unicite du numero
            if get_user_by_phone(phone):
                errors.append(
                    "Ce numero est deja utilise. Connectez-vous ou utilisez un autre numero."
                )

        if not errors:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            try:
                user = User.objects.create_user(
                    phone=phone,
                    password=password,
                    display_name=business_name,
                )
                SellerProfile.objects.create(
                    user=user,
                    business_name=business_name,
                )
                login(request, user, backend="accounts.backends.PhoneAuthBackend")
                messages.success(
                    request, f"Bienvenue ! Votre boutique '{business_name}' est prete."
                )
                return redirect("seller_home")
            except Exception as exc:
                errors.append(f"Erreur lors de la creation du compte : {exc}")

    return render(
        request,
        "accounts/register.html",
        {
            "errors": errors,
            "form_data": form_data,
        },
    )


def logout_view(request):
    if request.method == "POST":
        logout(request)
    return redirect("login")


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
        status__in=[
            FlashSaleStatus.COMPLETED,
            FlashSaleStatus.CLOSED,
            FlashSaleStatus.EXECUTING,
        ],
    ).order_by("-start_time")[:3]

    total_orders = Order.objects.filter(flash_sale__owner=seller).count()

    return render(
        request,
        "seller/home.html",
        {
            "active_sales": active_sales,
            "recent_sales": recent_sales,
            "total_orders": total_orders,
        },
    )


@staff_member_required
def platform_admin_dashboard(request):
    """KPIs globaux de la plateforme — staff only."""
    from datetime import timedelta

    from django.db.models import Count, Sum
    from django.utils import timezone

    from flash_sales.models import FlashSale, FlashSaleStatus
    from orders.models import Order
    from subscriptions.models import PaymentStatus, Subscription, SubscriptionPayment

    now = timezone.now()
    month_start = now - timedelta(days=30)

    context = {
        "total_sellers": SellerProfile.objects.filter(is_active=True).count(),
        "subs_by_plan": (
            Subscription.objects.values("plan")
            .annotate(count=Count("id"))
            .order_by("plan")
        ),
        "live_sales": FlashSale.objects.filter(status=FlashSaleStatus.LIVE).count(),
        "total_orders_month": Order.service_objects.filter(
            created_at__gte=month_start
        ).count(),
        "mrr": (
            SubscriptionPayment.objects.filter(
                status=PaymentStatus.SUCCESS,
                paid_at__gte=month_start,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        ),
        "total_revenue": (
            SubscriptionPayment.objects.filter(
                status=PaymentStatus.SUCCESS,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        ),
        "recent_payments": (
            SubscriptionPayment.objects.select_related("seller__user").order_by(
                "-created_at"
            )[:20]
        ),
    }
    return render(request, "core/platform_admin.html", context)
