"""Views abonnements et paiements HayaFlash."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.access import seller_required

from .models import (
    Plan,
    PaymentProvider,
    PaymentStatus,
    SubscriptionPayment,
)
from .services.limits import get_or_create_subscription, get_sale_quota
from .services.plans import (
    get_features,
    get_official_price,
    get_price_quote,
    is_plan_active,
    plan_offers,
)

logger = logging.getLogger(__name__)


def _get_seller(request):
    return request.user.seller_profile


# ── Page abonnement principal ──────────────────────────────────────────────────


@seller_required
def subscription_view(request):
    seller = _get_seller(request)
    sub = get_or_create_subscription(seller)
    # Meme comptage et meme limite que le blocage reel (limits.py) : plan
    # effectif du vendeur, ventes annulees exclues.
    quota = get_sale_quota(seller)

    recent_payments = SubscriptionPayment.objects.filter(seller=seller).order_by(
        "-created_at"
    )[:5]

    return render(
        request,
        "subscriptions/subscription.html",
        {
            "sub": sub,
            "quota": quota,
            "plans": plan_offers(sub),
            "recent_payments": recent_payments,
        },
    )


# ── Checkout ───────────────────────────────────────────────────────────────────


@seller_required
def checkout_view(request, plan: str):
    """Affiche le formulaire de paiement pour un plan donne.

    Le montant affiche vient du serveur (prix officiel ou tarif special du
    vendeur) ; le formulaire ne transmet aucun montant, et un champ amount
    force dans le POST est ignore (create_orange_payment recalcule).
    """
    if plan not in (Plan.MEDIUM, Plan.PRO) or not is_plan_active(plan):
        return redirect("subscriptions:subscription")

    seller = _get_seller(request)
    sub = get_or_create_subscription(seller)
    amount, override = get_price_quote(plan, seller)
    expires = sub.expires_at
    base_ctx = {
        "plan": plan,
        "amount": amount,
        "official_amount": get_official_price(plan),
        "override": override,
        "special_blocked": override is not None and sub.is_paid,
        "expires": expires,
        "features": get_features(plan),
    }

    if request.method == "POST":
        provider = request.POST.get("provider", PaymentProvider.ORANGE)
        phone = (request.POST.get("phone") or "").strip()

        if not phone:
            messages.error(request, "Le numéro de téléphone est obligatoire.")
            return render(request, "subscriptions/checkout.html", base_ctx)

        if provider == PaymentProvider.ORANGE:
            from .services.payment import PaymentNotAllowed, create_orange_payment

            try:
                payment = create_orange_payment(
                    seller=seller,
                    plan=plan,
                    phone=phone,
                    request=request,
                )
                return redirect(payment.payment_url)
            except PaymentNotAllowed as exc:
                messages.error(request, str(exc))
            except Exception as exc:
                logger.exception("Orange Money initiation failed: %s", exc)
                from django.conf import settings as _s

                detail = str(exc) if _s.DEBUG else ""
                messages.error(
                    request,
                    f"Le paiement Orange Money n'a pas pu être initié.{' — ' + detail if detail else ''}",
                )
        else:
            # Moov / Wave : pas encore disponible
            messages.info(
                request,
                f"Le paiement via {provider.capitalize()} sera disponible prochainement. "
                "Utilisez Orange Money pour le moment.",
            )

    return render(request, "subscriptions/checkout.html", base_ctx)


# ── Retour apres paiement ──────────────────────────────────────────────────────


@seller_required
def payment_return_view(request, payment_id):
    """Orange Money redirige ici apres que le client a paye (ou essaye)."""
    seller = _get_seller(request)
    payment = get_object_or_404(SubscriptionPayment, pk=payment_id, seller=seller)

    if payment.status == PaymentStatus.PENDING:
        # Verification active (meme logique que /billing/return/).
        from .services.payment import sync_orange_payment_status

        sync_orange_payment_status(payment, source="payment_return")

    if payment.status == PaymentStatus.SUCCESS:
        messages.success(
            request,
            f"Paiement confirmé ! Votre plan {payment.get_plan_display()} est actif.",
        )
        return redirect("subscriptions:subscription")

    # Paiement en attente — Orange Money confirme via webhook asynchrone
    return render(
        request,
        "subscriptions/payment_pending.html",
        {
            "payment": payment,
        },
    )


@seller_required
def payment_cancel_view(request, payment_id):
    """Le client a annule sur la page Orange Money."""
    seller = _get_seller(request)
    payment = get_object_or_404(SubscriptionPayment, pk=payment_id, seller=seller)
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.CANCELLED
        payment.save()
    messages.warning(request, "Paiement annulé.")
    return redirect("subscriptions:subscription")


# ── Webhook Orange Money ───────────────────────────────────────────────────────


@csrf_exempt
@require_POST
def payment_callback_view(request):
    """
    Callback asynchrone Orange Money — /seller/abonnement/callback/
    Orange poste ici quand le paiement est confirmé ou échoue.

    IMPORTANT: Cette URL est historique (ancien chemin /seller/...). Elle reste la route
    utilisée quand ORANGE_ML_RETURN_URL / _CANCEL_URL / _NOTIFY_URL ne sont pas toutes
    définies (voir subscriptions/services/payment.py:_om_urls). Le traitement est le même
    que pour /billing/webhook/orange/ (une seule implémentation), y compris la trace
    dans WebhookLog (F-166).
    """
    from .billing_views import process_orange_webhook

    return process_orange_webhook(request, source="webhook_legacy")


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
        "CLIENT_ID": bool(_s.ORANGE_MONEY_CLIENT_ID),
        "CLIENT_SECRET": bool(_s.ORANGE_MONEY_CLIENT_SECRET),
        "MERCHANT_KEY": bool(_s.ORANGE_MONEY_MERCHANT_KEY),
        "CLIENT_ID_val": (_s.ORANGE_MONEY_CLIENT_ID[:6] + "...")
        if _s.ORANGE_MONEY_CLIENT_ID
        else "VIDE",
        "MERCHANT_val": (_s.ORANGE_MONEY_MERCHANT_KEY[:6] + "...")
        if _s.ORANGE_MONEY_MERCHANT_KEY
        else "VIDE",
        "BASE_URL": base_url
        or "NON CONFIGURE — ajoutez ORANGE_MONEY_BASE_URL dans .env",
        "BASE_URL_ok": bool(base_url and base_url.startswith("https://")),
    }

    if not result["BASE_URL_ok"]:
        result["BASE_URL_warning"] = (
            "Orange Money exige une URL HTTPS publique (pas localhost). "
            "En dev, utilisez ngrok : ngrok http 8002, puis ORANGE_MONEY_BASE_URL=https://xxxx.ngrok-free.app"
        )

    if _s.ORANGE_MONEY_CLIENT_ID and _s.ORANGE_MONEY_CLIENT_SECRET:
        try:
            from .services.orange_money import (
                _get_access_token,
                OM_PAYMENT_URL,
                OM_CURRENCY,
            )
            import requests as _req

            token = _get_access_token()
            result["token_ok"] = True
            result["token_prefix"] = token[:12] + "..."

            # Tester l'appel webpayment seulement si BASE_URL est configure
            if result["BASE_URL_ok"]:
                test_payload = {
                    "merchant_key": _s.ORANGE_MONEY_MERCHANT_KEY,
                    "currency": OM_CURRENCY,
                    "order_id": "HF-DEBUG-TEST-001",
                    "amount": 1,
                    "return_url": base_url + "/",
                    "cancel_url": base_url + "/",
                    "notif_url": base_url + "/seller/abonnement/callback/",
                    "lang": "fr",
                    "reference": "HayaFlash-Debug",
                }
                resp = _req.post(
                    OM_PAYMENT_URL,
                    json=test_payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    timeout=15,
                )
                result["webpayment_status"] = resp.status_code
                result["webpayment_response"] = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else resp.text[:500]
                )
            else:
                result["webpayment_skipped"] = (
                    "Test webpayment ignore car BASE_URL non configure."
                )

        except Exception as exc:
            result["token_ok"] = False
            result["token_error"] = str(exc)
    else:
        result["token_ok"] = False
        result["token_error"] = "Credentials manquants dans .env"

    return JsonResponse(result, json_dumps_params={"indent": 2, "ensure_ascii": False})
