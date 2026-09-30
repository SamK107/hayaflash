from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services import rate_limit
from core.services.rate_limit import LOGIN_RATE_LIMIT_MESSAGE, REGISTER_RATE_LIMIT_MESSAGE

from .serializers import LoginSerializer, RegisterSerializer, UserSerializer
from .services.auth import login_user, register_user


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if rate_limit.register_ip_limited(request):
            return Response(
                {"detail": [REGISTER_RATE_LIMIT_MESSAGE]},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = register_user(serializer.validated_data, request=request)
        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if rate_limit.login_ip_limited(request):
            return Response(
                {"detail": [LOGIN_RATE_LIMIT_MESSAGE]},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = login_user(request, serializer.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            UserSerializer(request.user).data,
            status=status.HTTP_200_OK,
        )


# ── Vues HTML vendeur ────────────────────────────────────────────────────────


@login_required
def seller_profile_edit(request):
    """GET/POST /seller/profil/ — édition du profil public vendeur."""
    from accounts.forms import SellerProfileForm
    from orders.services.dashboard import get_dashboard_kpis_cached
    from flash_sales.models import FlashSaleStatus
    from flash_sales.services.ordering import live_now_q

    from accounts.access import get_seller_or_none, redirect_without_seller_profile

    profile = get_seller_or_none(request.user)
    if profile is None:
        return redirect_without_seller_profile(request)

    if request.method == "POST":
        form = SellerProfileForm(
            request.POST, request.FILES, instance=profile, user=request.user
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Profil mis à jour avec succès.")
            return redirect("seller_profile")
    else:
        form = SellerProfileForm(instance=profile, user=request.user)

    # Stats pour la carte résumé
    kpis = get_dashboard_kpis_cached(request.user)
    sales_qs = profile.flash_sales.all()
    stats = {
        "total_revenue": kpis.get("total_revenue", 0),
        "total_orders": kpis.get("total_orders", 0),
        "total_quantity": kpis.get("total_quantity", 0),
        "live_count": sales_qs.filter(live_now_q()).count(),
        "total_sales": sales_qs.count(),
        "completed_sales": sales_qs.filter(
            status__in=[FlashSaleStatus.COMPLETED, FlashSaleStatus.CLOSED]
        ).count(),
    }

    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "profile": profile,
            "stats": stats,
        },
    )


@login_required
def seller_settings(request):
    """GET/POST /seller/parametres/ — sécurité, abonnement, danger zone."""
    from accounts.forms import ChangePasswordForm
    from subscriptions.services.limits import (
        get_or_create_subscription,
        get_sale_quota,
    )

    from accounts.access import get_seller_or_none, redirect_without_seller_profile

    profile = get_seller_or_none(request.user)
    if profile is None:
        return redirect_without_seller_profile(request)

    sub = get_or_create_subscription(profile)
    # Meme comptage et meme limite que le blocage reel (plan effectif,
    # ventes annulees exclues, limites lues dans PlanConfig).
    quota = get_sale_quota(profile)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "change_password":
            form = ChangePasswordForm(request.POST, user=request.user)
            if form.is_valid():
                form.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Mot de passe modifié avec succès.")
                return redirect("seller_settings")
            return render(
                request,
                "accounts/settings.html",
                {
                    "pwd_form": form,
                    "sub": sub,
                    "profile": profile,
                    "quota": quota,
                },
            )

    pwd_form = ChangePasswordForm(user=request.user)
    return render(
        request,
        "accounts/settings.html",
        {
            "pwd_form": pwd_form,
            "sub": sub,
            "profile": profile,
            "quota": quota,
        },
    )
