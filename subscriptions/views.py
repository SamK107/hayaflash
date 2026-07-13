"""Views abonnements et paiements HayaFlash."""
from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from flash_sales.models import FlashSale
from .models import (
    Plan, PaymentProvider, PaymentStatus,
    SubscriptionPayment,
    PLAN_PRICES, PLAN_FEATURES,
)
from .services.limits import get_or_create_subscription, FREE_MONTHLY_SALES_LIMIT

logger = logging.getLogger(__name__)


def _get_seller(request):
    return request.user.seller_profile


# ── Page abonnement principal ──────────────────────────────────────────────────

@login_required
def subscription_view(request):
    seller = _get_seller(request)
    sub    = get_or_create_subscription(seller)

    now         = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sales_this_month = FlashSale.objects.filter(
        owner=seller, created_at__gte=month_start,
    ).count()

    recent_payments = SubscriptionPayment.objects.filter(
        seller=seller
    ).order_by("-created_at")[:5]

    return render(request, "subscriptions/subscription.html", {
        "sub":              sub,
        "sales_this_month": sales_this_month,
        "free_limit":       FREE_MONTHLY_SALES_LIMIT,
        "plans":            _plan_cards(sub),
        "recent_payments":  recent_payments,
    })


def _plan_cards(current_sub) -> list[dict]:
    return [
        {
            "plan":       Plan.MEDIUM,
            "label":      "Medium",
            "price":      PLAN_PRICES[Plan.MEDIUM],
            "features":   PLAN_FEATURES[Plan.MEDIUM],
            "is_current": current_sub.plan == Plan.MEDIUM and not current_sub.is_expired,
            "highlight":  False,
        },
        {
            "plan":       Plan.PRO,
            "label":      "Pro",
            "price":      PLAN_PRICES[Plan.PRO],
            "features":   PLAN_FEATURES[Plan.PRO],
            "is_current": current_sub.plan == Plan.PRO and not current_sub.is_expired,
            "highlight":  True,
        },
    ]


# ── Checkout ───────────────────────────────────────────────────────────────────

@login_required
def checkout_view(request, plan: str):
    """Affiche le formulaire de paiement pour un plan donne."""
    if plan not in (Plan.MEDIUM, Plan.PRO):
        return redirect("subscriptions:subscription")

    seller  = _get_seller(request)
    sub     = get_or_create_subscription(seller)
    amount  = PLAN_PRICES[plan]
    expires = sub.expires_at

    if request.method == "POST":
        provider = request.POST.get("provider", PaymentProvider.ORANGE)
        phone    = (request.POST.get("phone") or "").strip()

        if not phone:
            messages.error(request, "Le numero de telephone est obligatoire.")
            return render(request, "subscriptions/checkout.html", {
                "plan": plan, "amount": amount, "expires": expires,
            })

        if provider == PaymentProvider.ORANGE:
            try:
                from .services.payment import create_orange_payment
                payment = create_orange_payment(
                    seller=seller, plan=plan, phone=phone, request=request,
                )
                return redirect(payment.payment_url)
            except Exception as exc:
                logger.exception("Orange Money initiation failed: %s", exc)
                from django.conf import settings as _s
                detail = str(exc) if _s.DEBUG else ""
                messages.error(
                    request,
                    f"Le paiement Orange Money n'a pas pu etre initie.{' — ' + detail if detail else ''}"
                )
        else:
            # Moov / Wave : pas encore disponible
            messages.info(
                request,
                f"Le paiement via {provider.capitalize()} sera disponible prochainement. "
                "Utilisez Orange Money pour le moment.",
            )

    return render(request, "subscriptions/checkout.html", {
        "plan":    plan,
        "amount":  amount,
        "expires": expires,
        "features": PLAN_FEATURES.get(plan, []),
    })


# ── Retour apres paiement ──────────────────────────────────────────────────────

@login_required
def payment_return_view(request, payment_id):
    """Orange Money redirige ici apres que le client a paye (ou essaye)."""
    seller  = _get_seller(request)
    payment = get_object_or_404(SubscriptionPayment, pk=payment_id, seller=seller)

    if payment.status == PaymentStatus.SUCCESS:
        messages.success(
            request,
            f"Paiement confirme ! Votre plan {payment.get_plan_display()} est actif."
        )
        return redirect("subscriptions:subscription")

    # Paiement en attente — Orange Money confirme via webhook asynchrone
    return render(request, "subscriptions/payment_pending.html", {
        "payment": payment,
    })


@login_required
def payment_cancel_view(request, payment_id):
    """Le client a annule sur la page Orange Money."""
    seller  = _get_seller(request)
    payment = get_object_or_404(SubscriptionPayment, pk=payment_id, seller=seller)
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.CANCELLED
        payment.save()
    messages.warning(request, "Paiement annule.")
    return redirect("subscriptions:subscription")


# ── Webhook Orange Money ───────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def payment_callback_view(request):
    """
    Callback asynchrone Orange Money.
    Orange poste ici quand le paiement est confirme ou echoue.
    """
    try:
        raw_body = request.body
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            from urllib.parse import parse_qs
            data = {k: v[0] for k, v in parse_qs(raw_body.decode()).items()}

        from .services.orange_money import verify_callback
        result = verify_callback(data)

        order_id = result.get("order_id") or ""
        if not order_id:
            logger.warning("Orange callback sans order_id: %s", data)
            return HttpResponse("OK")

        try:
            payment = SubscriptionPayment.objects.get(order_id=order_id)
        except SubscriptionPayment.DoesNotExist:
            logger.warning("Orange callback — order_id inconnu: %s", order_id)
            return HttpResponse("OK")

        payment.raw_callback = data
        payment.txn_id       = result.get("txn_id", "")

        if result["success"]:
            from .services.payment import activate_subscription_from_payment
            activate_subscription_from_payment(payment)
            logger.info("Subscription activated via callback — order_id=%s", order_id)
        else:
            if payment.status == PaymentStatus.PENDING:
                payment.status = PaymentStatus.FAILED
                payment.save()

    except Exception:
        logger.exception("Orange Money callback processing error")

    return HttpResponse("OK")


# ── Diagnostic (DEBUG seulement) ───────────────────────────────────────────────

@login_required
def om_debug_view(request):
    """Verifie la configuration Orange Money. Accessible uniquement en DEBUG."""
    from django.conf import settings as _s
    if not _s.DEBUG:
        from django.http import Http404
        raise Http404

    base_url = getattr(_s, "ORANGE_MONEY_BASE_URL", "") or ""
    result = {
        "CLIENT_ID":      bool(_s.ORANGE_MONEY_CLIENT_ID),
        "CLIENT_SECRET":  bool(_s.ORANGE_MONEY_CLIENT_SECRET),
        "MERCHANT_KEY":   bool(_s.ORANGE_MONEY_MERCHANT_KEY),
        "CLIENT_ID_val":  (_s.ORANGE_MONEY_CLIENT_ID[:6] + "...") if _s.ORANGE_MONEY_CLIENT_ID else "VIDE",
        "MERCHANT_val":   (_s.ORANGE_MONEY_MERCHANT_KEY[:6] + "...") if _s.ORANGE_MONEY_MERCHANT_KEY else "VIDE",
        "BASE_URL":       base_url or "NON CONFIGURE — ajoutez ORANGE_MONEY_BASE_URL dans .env",
        "BASE_URL_ok":    bool(base_url and base_url.startswith("https://")),
    }

    if not result["BASE_URL_ok"]:
        result["BASE_URL_warning"] = (
            "Orange Money exige une URL HTTPS publique (pas localhost). "
            "En dev, utilisez ngrok : ngrok http 8002, puis ORANGE_MONEY_BASE_URL=https://xxxx.ngrok-free.app"
        )

    if _s.ORANGE_MONEY_CLIENT_ID and _s.ORANGE_MONEY_CLIENT_SECRET:
        try:
            from .services.orange_money import _get_access_token, OM_PAYMENT_URL, OM_CURRENCY
            import requests as _req
            token = _get_access_token()
            result["token_ok"]     = True
            result["token_prefix"] = token[:12] + "..."

            # Tester l'appel webpayment seulement si BASE_URL est configure
            if result["BASE_URL_ok"]:
                test_payload = {
                    "merchant_key": _s.ORANGE_MONEY_MERCHANT_KEY,
                    "currency":     OM_CURRENCY,
                    "order_id":     "HF-DEBUG-TEST-001",
                    "amount":       1,
                    "return_url":   base_url + "/",
                    "cancel_url":   base_url + "/",
                    "notif_url":    base_url + "/seller/abonnement/callback/",
                    "lang":         "fr",
                    "reference":    "HayaFlash-Debug",
                }
                resp = _req.post(
                    OM_PAYMENT_URL,
                    json=test_payload,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    timeout=15,
                )
                result["webpayment_status"]   = resp.status_code
                result["webpayment_response"] = resp.json() if resp.headers.get("content-type","").startswith("application/json") else resp.text[:500]
            else:
                result["webpayment_skipped"] = "Test webpayment ignore car BASE_URL non configure."

        except Exception as exc:
            result["token_ok"]    = False
            result["token_error"] = str(exc)
    else:
        result["token_ok"]    = False
        result["token_error"] = "Credentials manquants dans .env"

    return JsonResponse(result, json_dumps_params={"indent": 2, "ensure_ascii": False})
