"""
Views publiques stables — /billing/return/, /billing/cancel/, /billing/webhook/orange/
Ces URLs sont enregistrees chez Orange Money et ne changent jamais.
Elles deleguent a la logique existante dans views.py / services/.

Règles critiques:
  - Webhook utilise notif_token pour lookup (pas order_id) — sécurité
  - Webhook est idempotent — si payment.status == 'success', pas de re-traitement
  - @csrf_exempt UNIQUEMENT sur le webhook, pas sur les autres endpoints
"""

from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PaymentStatus, SubscriptionPayment, WebhookLog

logger = logging.getLogger(__name__)


@login_required
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
        payment = SubscriptionPayment.objects.select_related("seller").get(
            order_id=order_id
        )
    except SubscriptionPayment.DoesNotExist:
        logger.warning("billing_return: order_id inconnu: %s", order_id)
        return redirect("subscriptions:subscription")

    if payment.status == PaymentStatus.SUCCESS:
        messages.success(
            request,
            f"Paiement confirme ! Votre plan {payment.get_plan_display()} est actif.",
        )
        return redirect("subscriptions:subscription")

    # Paiement pending — le webhook arrive en asynchrone
    return render(request, "subscriptions/payment_pending.html", {"payment": payment})


@login_required
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
    Reçu de façon asynchrone quand le paiement est confirmé ou échoue.

    Règles de sécurité:
    1. Lookup par notif_token UNIQUEMENT (pas par order_id)
    2. Idempotent: si payment.status == 'success', pas de re-traitement
    3. @csrf_exempt seulement sur ce webhook, pas sur les autres endpoints
    4. Retourner toujours 200 OK (Orange Money retry si erreur)
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

        # SÉCURITÉ CRITIQUE: Lookup par notif_token UNIQUEMENT (pas order_id)
        notif_token = result.get("notif_token") or ""
        if not notif_token:
            logger.warning(
                "billing_callback: pas de notif_token dans payload: %s", data
            )
            return HttpResponse("OK")

        try:
            payment = SubscriptionPayment.objects.select_related("seller").get(
                notif_token=notif_token
            )
        except SubscriptionPayment.DoesNotExist:
            logger.warning("billing_callback: notif_token inconnu: %s", notif_token)
            return HttpResponse("OK")

        # Log du webhook dans WebhookLog pour audit
        status = result.get("status", "")
        txn_id = result.get("txn_id", "")

        # IDEMPOTENCE: Si déjà success, pas de re-traitement
        # Ceci prévient les re-activations si Orange Money renvoie le webhook 2x
        if payment.status == PaymentStatus.SUCCESS:
            logger.info(
                "Webhook already processed — notif_token=%s (idempotent skip)",
                notif_token[:16] + "...",
            )
            # Logger quand même dans WebhookLog
            WebhookLog.objects.create(
                payment=payment,
                notif_token=notif_token,
                status=status,
                txn_id=txn_id,
                raw_payload=data,
                processed=False,  # Pas de re-traitement
                error_message="Payment already successfully processed (idempotent)",
            )
            return HttpResponse("OK")

        # Traitement du webhook
        with transaction.atomic():
            payment.raw_callback = data
            payment.txn_id = txn_id

            if result["success"]:
                from .services.payment import activate_subscription_from_payment

                activate_subscription_from_payment(payment)
                logger.info(
                    "Subscription activated — notif_token=%s seller=%s",
                    notif_token[:16] + "...",
                    payment.seller_id,
                )
                # Log du succès
                WebhookLog.objects.create(
                    payment=payment,
                    notif_token=notif_token,
                    status=status,
                    txn_id=txn_id,
                    raw_payload=data,
                    processed=True,
                )
            else:
                if payment.status == PaymentStatus.PENDING:
                    payment.status = PaymentStatus.FAILED
                    payment.save()
                logger.warning(
                    "Payment failed — notif_token=%s status=%s",
                    notif_token[:16] + "...",
                    status,
                )
                # Log de l'échec
                WebhookLog.objects.create(
                    payment=payment,
                    notif_token=notif_token,
                    status=status,
                    txn_id=txn_id,
                    raw_payload=data,
                    processed=True,
                )

    except Exception as exc:
        logger.exception("billing_callback: erreur de traitement: %s", str(exc))

    # TOUJOURS retourner 200 OK pour indiquer à Orange Money qu'on a reçu le webhook
    # (même en cas d'erreur). Orange Money retry si on retourne une erreur HTTP.
    return HttpResponse("OK")
