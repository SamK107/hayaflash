"""
Orchestration des paiements d'abonnement HayaFlash.
Gere : initiation, activation, annulation.
"""

from __future__ import annotations

import uuid
import logging
from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from subscriptions.models import (
    Plan,
    PaymentProvider,
    PaymentStatus,
    Subscription,
    SubscriptionPayment,
    PLAN_PRICES,
)

logger = logging.getLogger(__name__)

SUBSCRIPTION_DURATION_DAYS = 31  # ~1 mois


def _absolute_url(request, path: str) -> str:
    """Construit une URL publique utilisable par Orange Money (pas de localhost)."""
    from django.conf import settings

    base = getattr(settings, "ORANGE_MONEY_BASE_URL", "").strip().rstrip("/")
    if base:
        return base + path
    return request.build_absolute_uri(path)


def _om_urls(request, payment: "SubscriptionPayment") -> tuple[str, str, str]:
    """
    Retourne (return_url, cancel_url, notif_url) pour Orange Money.
    Priorite : URLs specifiques .env > BASE_URL + path Django > request.build_absolute_uri.
    """
    from django.conf import settings

    return_cfg = getattr(settings, "ORANGE_MONEY_RETURN_URL", "").strip()
    cancel_cfg = getattr(settings, "ORANGE_MONEY_CANCEL_URL", "").strip()
    notify_cfg = getattr(settings, "ORANGE_MONEY_NOTIFY_URL", "").strip()

    if return_cfg and cancel_cfg and notify_cfg:
        # URLs prod configurees explicitement — on ajoute order_id en query param
        # pour que la page de retour puisse retrouver le paiement
        sep_r = "&" if "?" in return_cfg else "?"
        sep_c = "&" if "?" in cancel_cfg else "?"
        return (
            f"{return_cfg}{sep_r}order_id={payment.order_id}",
            f"{cancel_cfg}{sep_c}order_id={payment.order_id}",
            notify_cfg,
        )

    # Fallback : URLs Django locales (dev avec ngrok ou prod sans config explicite)
    return_url = _absolute_url(
        request, reverse("subscriptions:payment_return", args=[payment.pk])
    )
    cancel_url = _absolute_url(
        request, reverse("subscriptions:payment_cancel", args=[payment.pk])
    )
    notif_url = _absolute_url(request, reverse("subscriptions:payment_callback"))
    return return_url, cancel_url, notif_url


def create_orange_payment(
    *, seller, plan: str, phone: str, request
) -> SubscriptionPayment:
    """
    Cree un SubscriptionPayment et lance l'initiation Orange Money.
    Retourne le payment (avec payment_url rempli).
    """
    from subscriptions.services.orange_money import initiate_payment, OrangeMoneyError

    if plan not in (Plan.MEDIUM, Plan.PRO):
        raise ValueError(f"Plan invalide : {plan}")

    amount = PLAN_PRICES[plan]
    order_id = f"HF-{plan.upper()}-{uuid.uuid4().hex[:12].upper()}"

    payment = SubscriptionPayment.objects.create(
        seller=seller,
        plan=plan,
        provider=PaymentProvider.ORANGE,
        amount=amount,
        phone=phone,
        order_id=order_id,
        status=PaymentStatus.PENDING,
    )

    return_url, cancel_url, notif_url = _om_urls(request, payment)

    try:
        result = initiate_payment(
            amount=amount,
            order_id=order_id,
            return_url=return_url,
            cancel_url=cancel_url,
            notif_url=notif_url,
            reference=f"HayaFlash {plan.capitalize()} {seller.business_name or str(seller.pk)}",
        )
        payment.payment_url = result["payment_url"]
        payment.pay_token = result["pay_token"]
        payment.raw_response = result["raw"]
        payment.save()
    except OrangeMoneyError as exc:
        payment.status = PaymentStatus.FAILED
        payment.raw_response = {"error": str(exc)}
        payment.save()
        raise

    return payment


@transaction.atomic
def activate_subscription_from_payment(payment: SubscriptionPayment) -> Subscription:
    """
    Active ou prolonge l'abonnement du vendeur apres paiement confirme.
    Idempotent : si deja success, retourne sans modifier.
    """
    if payment.status == PaymentStatus.SUCCESS:
        return payment.seller.subscription

    payment.status = PaymentStatus.SUCCESS
    payment.paid_at = timezone.now()
    payment.save()

    sub, _ = Subscription.objects.get_or_create(seller=payment.seller)

    now = timezone.now()
    # Si le plan actuel est superieur ou egal, prolonger a partir de l'expiration
    if sub.plan == payment.plan and sub.expires_at and sub.expires_at > now:
        new_expires = sub.expires_at + timedelta(days=SUBSCRIPTION_DURATION_DAYS)
    else:
        new_expires = now + timedelta(days=SUBSCRIPTION_DURATION_DAYS)

    sub.plan = payment.plan
    sub.expires_at = new_expires
    sub.save()

    logger.info(
        "Subscription activated — seller=%s plan=%s expires=%s payment=%s",
        payment.seller_id,
        payment.plan,
        new_expires,
        payment.pk,
    )
    return sub


def cancel_payment(payment: SubscriptionPayment) -> None:
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.CANCELLED
        payment.save()
