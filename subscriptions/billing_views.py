"""
Views publiques stables — /billing/return/, /billing/cancel/, /billing/webhook/orange/
Ces URLs sont enregistrees chez Orange Money et ne changent jamais.
Elles deleguent a la logique existante dans views.py / services/.
"""
from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PaymentStatus, SubscriptionPayment

logger = logging.getLogger(__name__)


def billing_return_view(request):
    """
    Orange Money redirige ici apres que le client a finalise (ou quitte) la page de paiement.
    Orange passe order_id en query param : /billing/return/?order_id=HF-PRO-XXXX
    Si le paiement est deja confirme (webhook arrive avant) -> succes direct.
    Sinon -> page d'attente avec auto-refresh.
    """
    order_id = (request.GET.get("order_id") or "").strip()

    if not order_id:
        # Pas d'order_id : probablement acces direct a l'URL, rediriger vers abonnement
        return redirect("subscriptions:subscription")

    try:
        payment = SubscriptionPayment.objects.select_related("seller").get(order_id=order_id)
    except SubscriptionPayment.DoesNotExist:
        logger.warning("billing_return: order_id inconnu: %s", order_id)
        return redirect("subscriptions:subscription")

    if payment.status == PaymentStatus.SUCCESS:
        messages.success(
            request,
            f"Paiement confirme ! Votre plan {payment.get_plan_display()} est actif."
        )
        return redirect("subscriptions:subscription")

    # Paiement pending — le webhook arrive en asynchrone
    return render(request, "subscriptions/payment_pending.html", {"payment": payment})


def billing_cancel_view(request):
    """
    Orange Money redirige ici quand le client annule sur la page de paiement.
    """
    order_id = (request.GET.get("order_id") or "").strip()

    if order_id:
        try:
            payment = SubscriptionPayment.objects.get(order_id=order_id)
            if payment.status == PaymentStatus.PENDING:
                payment.status = PaymentStatus.CANCELLED
                payment.save()
        except SubscriptionPayment.DoesNotExist:
            pass

    messages.warning(request, "Paiement annule.")
    return redirect("subscriptions:subscription")


@csrf_exempt
@require_POST
def billing_callback_view(request):
    """
    Webhook Orange Money — /billing/webhook/orange/
    Recu de facon asynchrone quand le paiement est confirme ou echoue.
    Identique a payment_callback_view mais sur une URL stable independante du prefixe /seller/.
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
            logger.warning("billing_callback: pas d'order_id dans: %s", data)
            return HttpResponse("OK")

        try:
            payment = SubscriptionPayment.objects.get(order_id=order_id)
        except SubscriptionPayment.DoesNotExist:
            logger.warning("billing_callback: order_id inconnu: %s", order_id)
            return HttpResponse("OK")

        payment.raw_callback = data
        payment.txn_id       = result.get("txn_id", "")

        if result["success"]:
            from .services.payment import activate_subscription_from_payment
            activate_subscription_from_payment(payment)
            logger.info("Subscription activated — order_id=%s", order_id)
        else:
            if payment.status == PaymentStatus.PENDING:
                payment.status = PaymentStatus.FAILED
                payment.save()
            logger.info("Payment failed — order_id=%s", order_id)

    except Exception:
        logger.exception("billing_callback: erreur de traitement")

    return HttpResponse("OK")
