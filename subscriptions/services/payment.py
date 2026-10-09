"""
Orchestration des paiements d'abonnement HayaFlash.
Gere : initiation, activation, annulation.

Règles critiques:
  - notif_token est généré et stocké AVANT redirection (sécurité webhook)
  - Webhooks font un lookup par notif_token UNIQUEMENT (pas par order_id)
  - order_id limité à 24 caractères (contrainte Orange Money)
  - Montant calcule COTE SERVEUR (services/plans.py) : prix officiel du plan,
    ou tarif special actif du vendeur. Jamais un montant venu du formulaire.
"""

from __future__ import annotations

import secrets
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
    SellerPriceOverride,
    Subscription,
    SubscriptionPayment,
)
from subscriptions.services.plans import (
    get_duration_days,
    get_price_quote,
    is_plan_active,
)

logger = logging.getLogger(__name__)


class PaymentNotAllowed(ValueError):
    """Initiation refusee pour une raison metier (message affichable)."""


def _generate_order_id(plan: str, max_length: int = 24) -> str:
    """
    Génère un order_id respectant la limite de 24 caractères.
    Format: HF-{plan[0]}-{random} (ex: HF-M-a1b2c3d4e5f6)
    """
    # Construire un identifiant court
    plan_char = plan[0].upper()  # M ou P
    # Utiliser un hash court du timestamp + UUID pour l'unicité
    short_id = uuid.uuid4().hex[:8].upper()
    base = f"HF-{plan_char}-{short_id}"
    # Vérifier la longueur
    if len(base) > max_length:
        raise ValueError(
            f"Generated order_id exceeds {max_length} chars: {len(base)} chars"
        )
    return base


def _generate_notif_token() -> str:
    """Génère un token aléatoire de 64 hex chars pour les webhooks."""
    return secrets.token_hex(32)


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
    Crée un SubscriptionPayment et lance l'initiation Orange Money.
    Retourne le payment (avec payment_url rempli).

    Règle critique: notif_token est généré et stocké AVANT la redirection
    vers Orange Money pour assurer que les webhooks ultérieurs peuvent
    faire un lookup sécurisé par notif_token.
    """
    from subscriptions.services.orange_money import initiate_payment, OrangeMoneyError

    if plan not in (Plan.MEDIUM, Plan.PRO):
        raise ValueError(f"Plan invalide : {plan}")
    if not is_plan_active(plan):
        raise PaymentNotAllowed("Ce plan n'est pas proposé pour le moment.")

    # Montant decide ici, cote serveur : prix officiel ou tarif special actif.
    amount, override = get_price_quote(plan, seller)
    if override is not None:
        sub = Subscription.objects.filter(seller=seller).first()
        if sub is not None and sub.is_paid:
            # Un tarif special ne prolonge jamais un abonnement payant actif.
            raise PaymentNotAllowed(
                "Tarif spécial non applicable : vous avez déjà un abonnement payant "
                "actif. Utilisez un compte vendeur de test, ou contactez le support."
            )
    # Générer un order_id ≤ 24 caractères (contrainte Orange Money)
    order_id = _generate_order_id(plan, max_length=24)
    # Générer un notif_token avant la création du paiement
    # IMPORTANT: Stocker ce token AVANT redirection pour la sécurité du webhook
    notif_token = _generate_notif_token()

    payment = SubscriptionPayment.objects.create(
        seller=seller,
        plan=plan,
        provider=PaymentProvider.ORANGE,
        amount=amount,
        phone=phone,
        order_id=order_id,
        notif_token=notif_token,  # Stocké avant redirection (sécurité)
        status=PaymentStatus.PENDING,
        price_override=override,
        is_special_price=override is not None,
    )
    # Reference courte et fixe : Orange Money rejette une reference trop longue
    # (HTTP 400 code 24 "reference ... bad syntax", constate le 27/09 avec
    # 38 caracteres). Le vendeur est identifie par order_id / notif_token,
    # inutile de mettre le nom de boutique ici.
    reference = f"HayaFlash {plan.capitalize()}"
    if override is not None:
        # Reperable dans les releves Orange Money.
        reference = f"{reference} SPECIAL"

    return_url, cancel_url, notif_url = _om_urls(request, payment)

    try:
        result = initiate_payment(
            amount=amount,
            order_id=order_id,
            notif_token=notif_token,  # Envoyé à Orange Money
            return_url=return_url,
            cancel_url=cancel_url,
            notif_url=notif_url,
            reference=reference,
        )
        payment.payment_url = result["payment_url"]
        payment.raw_response = result["raw"]
        # Orange Money genere SON PROPRE notif_token et le renvoie dans la
        # reponse d'initiation ; c'est celui-la (et non le notre) qu'il
        # renvoie dans le webhook. Sans cette ligne, le webhook tombe sur
        # « notif_token inconnu » et l'abonnement n'est jamais active
        # (constate au test reel du 27/09, paiement HF-M-D4F26BC7).
        # Le token reste secret (echange serveur a serveur en TLS).
        orange_token = (result.get("raw") or {}).get("notif_token")
        if orange_token:
            payment.notif_token = str(orange_token).strip()
        payment.save()

        logger.info(
            "Orange Money payment initiated — order_id=%s plan=%s seller=%s "
            "amount=%s special=%s",
            order_id,
            plan,
            seller.id,
            amount,
            override.pk if override is not None else "-",
        )
    except OrangeMoneyError as exc:
        payment.status = PaymentStatus.FAILED
        payment.raw_response = {"error": str(exc)}
        payment.save()
        logger.error(
            "Orange Money initiation failed — order_id=%s error=%s",
            order_id,
            str(exc),
        )
        raise

    return payment


def _record_partner_commission(payment: SubscriptionPayment) -> None:
    """Commission du partenaire parrain (programme partenaires), sans jamais gener.

    Point d'accroche unique : activate_subscription_from_payment est appele par le
    webhook, le retour navigateur et la tache de verification (via
    sync_orange_payment_status). Un point de sauvegarde isole la creation : une
    panne (meme SQL) ne fait ni echouer ni annuler l'activation. Le journal ne
    contient jamais de numero (empreinte seulement).
    """
    try:
        from partners.services.commissions import record_for_payment

        with transaction.atomic():
            record_for_payment(payment)
    except Exception as exc:
        from core.services.rate_limit import phone_fingerprint

        logger.error(
            "Commission partenaire non enregistree (%s) paiement=%s %s",
            type(exc).__name__,
            payment.pk,
            phone_fingerprint(payment.phone),
        )


@transaction.atomic
def activate_subscription_from_payment(payment: SubscriptionPayment) -> Subscription:
    """
    Active ou prolonge l'abonnement du vendeur apres paiement confirme.
    Idempotent : si deja success, retourne sans modifier.

    Tarif special : duree = override.duration_days si defini (sinon duree du
    plan), uses_count +1 ici seulement (paiement reussi), sous
    select_for_update. Un paiement special ne prolonge jamais un abonnement
    payant deja actif (refuse a l'initiation ; ici, par securite, la date de
    fin n'est jamais repoussee au-dela de l'existant).
    """
    # Verrou sur la ligne du paiement : le webhook et la verification active
    # (retour navigateur, tache Celery) peuvent arriver en meme temps. Sans
    # verrou, les deux verraient « pending » et prolongeraient l'abonnement
    # deux fois. Le second attend ici, puis voit SUCCESS et sort.
    locked = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
    if locked.status == PaymentStatus.SUCCESS:
        payment.status = PaymentStatus.SUCCESS
        return Subscription.objects.get(seller_id=payment.seller_id)

    payment.status = PaymentStatus.SUCCESS
    payment.paid_at = timezone.now()
    payment.save()

    duration_days = get_duration_days(payment.plan)
    override = None
    if payment.price_override_id:
        override = SellerPriceOverride.objects.select_for_update().get(
            pk=payment.price_override_id
        )
        if override.uses_count >= override.max_uses:
            # Deux paiements inities en parallele sur un tarif max_uses=1 : le
            # second a quand meme ete paye, on l'active mais on le signale.
            logger.error(
                "Tarif special %s deja epuise (%s/%s) — paiement %s active quand meme",
                override.pk,
                override.uses_count,
                override.max_uses,
                payment.pk,
            )
        override.uses_count += 1
        override.save(update_fields=["uses_count", "updated_at"])
        if override.duration_days:
            duration_days = override.duration_days

    sub, _ = Subscription.objects.select_for_update().get_or_create(
        seller=payment.seller
    )

    now = timezone.now()
    if override is not None and sub.is_paid:
        # Refuse a l'initiation ; ne peut arriver que par une course (abonnement
        # paye entre l'initiation et le webhook). On ne touche ni au plan ni a
        # l'echeance de l'abonnement officiel.
        logger.error(
            "Paiement special %s sur abonnement payant actif : abonnement inchangé",
            payment.pk,
        )
        _record_partner_commission(payment)
        return sub
    if override is not None:
        new_expires = now + timedelta(days=duration_days)
    elif sub.plan == payment.plan and sub.expires_at and sub.expires_at > now:
        # Meme plan encore actif : on prolonge a partir de l'expiration.
        new_expires = sub.expires_at + timedelta(days=duration_days)
    else:
        new_expires = now + timedelta(days=duration_days)

    sub.plan = payment.plan
    sub.expires_at = new_expires
    sub.save()

    logger.info(
        "Subscription activated — seller=%s plan=%s expires=%s payment=%s special=%s",
        payment.seller_id,
        payment.plan,
        new_expires,
        payment.pk,
        payment.price_override_id or "-",
    )
    _record_partner_commission(payment)
    return sub


# ── Verification active aupres d'Orange Money (transactionstatus) ────────────

# Statuts Orange definitifs d'echec -> statut local.
_ORANGE_FINAL_FAILURES = {
    "FAILED": PaymentStatus.FAILED,
    "EXPIRED": PaymentStatus.EXPIRED,
}


def sync_orange_payment_status(payment: SubscriptionPayment, *, source: str) -> str:
    """Demande a Orange l'etat d'un paiement en attente et l'applique.

    Complement du webhook, meme activation idempotente
    (activate_subscription_from_payment, verrouillee). Appelee au retour
    navigateur (/billing/return/) et par la tache Celery
    subscriptions.check_pending_orange_payments.

    Retourne le statut Orange (SUCCESS, PENDING, ...) ou "" si la
    verification n'a pas pu avoir lieu (paiement non concerne, pas de
    pay_token, erreur reseau). Ne leve jamais : un echec ici ne doit ni
    bloquer la page de retour ni arreter la tache.
    """
    if payment.status != PaymentStatus.PENDING or payment.provider != PaymentProvider.ORANGE:
        return ""
    pay_token = (payment.raw_response or {}).get("pay_token")
    if not pay_token:
        logger.warning(
            "Verification Orange impossible : pas de pay_token — order_id=%s",
            payment.order_id,
        )
        return ""

    from core.models import audit
    from subscriptions.services.orange_money import (
        callback_amount_mismatch,
        get_transaction_status,
    )

    try:
        result = get_transaction_status(
            order_id=payment.order_id, amount=payment.amount, pay_token=pay_token
        )
    except Exception as exc:  # OrangeMoneyError, reseau, JSON, token OAuth...
        logger.warning(
            "Verification Orange echouee — order_id=%s source=%s : %s",
            payment.order_id,
            source,
            exc,
        )
        return ""

    status = result["status"]
    if status == "SUCCESS":
        if callback_amount_mismatch(result, payment.amount):
            logger.error(
                "Verification Orange : montant incoherent — order_id=%s attendu=%s recu=%r",
                payment.order_id,
                payment.amount,
                result.get("amount"),
            )
            return "AMOUNT_MISMATCH"
        with transaction.atomic():
            if result.get("txn_id") and not payment.txn_id:
                payment.txn_id = result["txn_id"]
            activate_subscription_from_payment(payment)
        audit(
            "subscription_payment.confirmed_by_status_check",
            entity_type="SellerProfile",
            entity_id=payment.seller_id,
            order_id=payment.order_id,
            txn_id=payment.txn_id,
            source=source,
        )
        logger.info(
            "Paiement confirme par verification active — order_id=%s source=%s",
            payment.order_id,
            source,
        )
    elif status in _ORANGE_FINAL_FAILURES:
        with transaction.atomic():
            locked = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
            if locked.status == PaymentStatus.PENDING:
                locked.status = _ORANGE_FINAL_FAILURES[status]
                locked.save(update_fields=["status", "updated_at"])
                payment.status = locked.status
        logger.info(
            "Paiement %s selon Orange — order_id=%s source=%s",
            status,
            payment.order_id,
            source,
        )
    return status


def cancel_payment(payment: SubscriptionPayment) -> None:
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.CANCELLED
        payment.save()
