# Workflow P5 — Notifications + Subscriptions
> Phase 5 · Durée estimée : ~1 semaine  
> Prérequis : P0 à P4

---

## Objectif

Implémenter les notifications (SMS, WhatsApp) et le système d'abonnement avec enforcement du plan Free (limite 3 ventes/mois).

---

## Étape 5.1 — Modèle Notification

**Fichier** : `notifications/models.py`

```python
from django.db import models


class Notification(models.Model):
    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS      = "sms",      "SMS"
        EMAIL    = "email",    "Email"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        SENT    = "sent",    "Envoyée"
        FAILED  = "failed",  "Échouée"

    recipient_phone = models.CharField(max_length=20)
    channel         = models.CharField(max_length=20, choices=Channel.choices)
    message         = models.TextField()
    status          = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_message   = models.TextField(blank=True)
    sent_at         = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["status", "channel"])]

    def __str__(self) -> str:
        return f"[{self.channel}] → {self.recipient_phone} ({self.status})"
```

---

## Étape 5.2 — Services Notifications

**Nouveau fichier** : `notifications/services/whatsapp.py`

```python
"""Service WhatsApp — lien wa.me en V1, WhatsApp Business API en V1.1."""
import logging
import urllib.parse

logger = logging.getLogger(__name__)


def build_whatsapp_order_message(order) -> str:
    """Construit le message de confirmation commande pour WhatsApp."""
    items_text = "\n".join(
        f"  • {item.product_name_snapshot} x{item.quantity} — {int(item.price_snapshot * item.quantity):,} FCFA"
        for item in order.items.all()
    )
    return (
        f"✅ *Commande confirmée !*\n\n"
        f"Bonjour {order.customer_name} 👋\n\n"
        f"Votre commande a bien été enregistrée :\n"
        f"{items_text}\n\n"
        f"💰 Total : *{int(order.total_amount):,} FCFA*\n\n"
        f"Vous serez livré(e) à l'adresse indiquée. Paiement à la livraison.\n\n"
        f"_Commande via HayaFlash_"
    )


def build_whatsapp_share_url(phone: str, message: str) -> str:
    """Retourne un lien wa.me pour envoyer un message WhatsApp."""
    encoded = urllib.parse.quote(message)
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    return f"https://wa.me/{clean_phone}?text={encoded}"
```

**Nouveau fichier** : `notifications/services/sms.py`

```python
"""Service SMS — Orange SMS Gateway Mali."""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(phone: str, message: str) -> bool:
    """Envoie un SMS via la gateway Orange Mali."""
    api_key  = getattr(settings, "ORANGE_SMS_API_KEY", "")
    base_url = getattr(settings, "ORANGE_SMS_BASE_URL", "")

    if not api_key:
        logger.warning("SMS non configuré (ORANGE_SMS_API_KEY manquant) — SMS non envoyé à %s", phone)
        return False

    try:
        resp = requests.post(
            f"{base_url}/sms/send",
            json={"recipient": phone, "message": message},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("SMS envoyé à %s", phone)
        return True
    except Exception as exc:
        logger.error("Erreur envoi SMS à %s : %s", phone, exc)
        return False
```

**Nouveau fichier** : `notifications/services/dispatcher.py`

```python
"""Dispatcher central de notifications."""
import logging
from django.utils import timezone
from notifications.models import Notification

logger = logging.getLogger(__name__)


def send_notification(*, recipient_phone: str, message: str, channel: str = "sms") -> Notification:
    """Crée et envoie une notification."""
    notif = Notification.objects.create(
        recipient_phone=recipient_phone,
        channel=channel,
        message=message,
    )
    try:
        if channel == Notification.Channel.SMS:
            from .sms import send_sms
            success = send_sms(recipient_phone, message)
        elif channel == Notification.Channel.WHATSAPP:
            # WhatsApp Business API — V1.1
            # En V1 : log uniquement
            logger.info("WhatsApp message (non envoyé en V1) → %s", recipient_phone)
            success = True
        else:
            success = False

        notif.status   = Notification.Status.SENT if success else Notification.Status.FAILED
        notif.sent_at  = timezone.now() if success else None
        notif.save(update_fields=["status", "sent_at", "updated_at"])
    except Exception as exc:
        notif.status        = Notification.Status.FAILED
        notif.error_message = str(exc)
        notif.save(update_fields=["status", "error_message", "updated_at"])

    return notif
```

---

## Étape 5.3 — Celery Task : Confirmation Commande

**Nouveau fichier** : `notifications/tasks.py`

```python
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(name="notifications.send_order_confirmation", ignore_result=True)
def send_order_confirmation(order_id: int) -> None:
    """Envoie une confirmation SMS/WhatsApp après création de commande."""
    from orders.models import Order
    from notifications.services.dispatcher import send_notification

    try:
        order = Order.service_objects.select_related("flash_sale").prefetch_related("items__product").get(pk=order_id)
    except Order.DoesNotExist:
        logger.warning("Order %s introuvable pour notification", order_id)
        return

    message = (
        f"✅ HayaFlash — Commande #{order.pk} enregistrée !\n"
        f"Total : {int(order.total_amount):,} FCFA\n"
        f"Paiement à la livraison. Merci {order.customer_name} !"
    )
    send_notification(
        recipient_phone=order.customer_phone,
        message=message,
        channel="sms",
    )


@shared_task(name="notifications.send_sale_reminder", ignore_result=True)
def send_sale_reminder(flash_sale_id: int, phone: str) -> None:
    """Rappel SMS 1h avant l'ouverture d'une vente."""
    from flash_sales.models import FlashSale
    from notifications.services.dispatcher import send_notification

    try:
        sale = FlashSale.objects.get(pk=flash_sale_id)
    except FlashSale.DoesNotExist:
        return

    message = (
        f"⚡ HayaFlash — Rappel !\n"
        f"La vente « {sale.title} » commence dans 1 heure !\n"
        f"Lien : https://hayaflash.com/f/{sale.public_slug}/"
    )
    send_notification(recipient_phone=phone, message=message, channel="sms")
```

**Intégrer dans `orders/services/create_order.py`** après le commit :

```python
# Notification async (hors transaction)
from notifications.tasks import send_order_confirmation
send_order_confirmation.delay(order.pk)
```

---

## Étape 5.4 — Modèle Subscription

**Fichier** : `subscriptions/models.py`

```python
from django.db import models
from django.utils import timezone


class Plan(models.TextChoices):
    FREE = "free", "Gratuit"
    PRO  = "pro",  "Pro"


class Subscription(models.Model):
    seller     = models.OneToOneField(
        "accounts.SellerProfile", on_delete=models.CASCADE,
        related_name="subscription"
    )
    plan       = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    expires_at = models.DateTimeField(null=True, blank=True,
        help_text="Null = gratuit perpétuel ou Pro actif"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_pro(self) -> bool:
        if self.plan == Plan.FREE:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def __str__(self) -> str:
        return f"{self.seller.business_name} — {self.plan}"
```

---

## Étape 5.5 — Service de Limites

**Nouveau fichier** : `subscriptions/services/limits.py`

```python
"""Vérification des limites par plan."""
from __future__ import annotations

from django.utils import timezone


FREE_MONTHLY_SALES_LIMIT = 3


def get_or_create_subscription(seller):
    from subscriptions.models import Subscription, Plan
    sub, _ = Subscription.objects.get_or_create(
        seller=seller,
        defaults={"plan": Plan.FREE}
    )
    return sub


def can_create_flash_sale(seller) -> tuple[bool, str]:
    """
    Retourne (True, "") si le vendeur peut créer une vente,
    (False, message_erreur) sinon.
    """
    sub = get_or_create_subscription(seller)
    if sub.is_pro:
        return True, ""

    # Compter les ventes de ce mois-ci
    from flash_sales.models import FlashSale
    now        = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = FlashSale.objects.filter(
        owner=seller,
        created_at__gte=month_start,
    ).count()

    if count >= FREE_MONTHLY_SALES_LIMIT:
        return False, (
            f"Vous avez atteint la limite de {FREE_MONTHLY_SALES_LIMIT} ventes par mois "
            f"sur le plan Gratuit. Passez au plan Pro pour des ventes illimitées."
        )
    return True, ""
```

---

## Étape 5.6 — Enforcement dans la view create

Mettre à jour `flash_sales/services/crud.py` → `can_seller_create_sale()` :

```python
def can_seller_create_sale(seller) -> tuple[bool, str]:
    from subscriptions.services.limits import can_create_flash_sale
    return can_create_flash_sale(seller)
```

---

## Étape 5.7 — Page Abonnement Vendeur

**Nouvelle view** : `subscriptions/views.py`

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .services.limits import get_or_create_subscription, FREE_MONTHLY_SALES_LIMIT
from django.utils import timezone
from flash_sales.models import FlashSale

@login_required
def subscription_view(request):
    seller = request.user.sellerprofile
    sub    = get_or_create_subscription(seller)
    now    = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sales_this_month = FlashSale.objects.filter(owner=seller, created_at__gte=month_start).count()

    return render(request, "subscriptions/subscription.html", {
        "sub": sub,
        "sales_this_month": sales_this_month,
        "free_limit": FREE_MONTHLY_SALES_LIMIT,
    })
```

Template : `templates/subscriptions/subscription.html`
- Plan actuel (badge Free/Pro)
- Utilisation ce mois : `X / 3 ventes`
- Barre de progression
- CTA upgrade : "Passer au Plan Pro — 5 000 FCFA/mois"
- Méthode de paiement : Orange Money (lien vers flow Orange Money quand activé)

---

## Checklist Finale P5

- [ ] `python manage.py migrate` — tables Notification + Subscription créées
- [ ] SMS de confirmation envoyé (ou loggué en dev) à la création d'une commande
- [ ] Vendeur Free bloqué à 3 ventes/mois avec message d'upgrade
- [ ] Page `/seller/abonnement/` accessible
- [ ] `send_order_confirmation.delay(order_id)` déclenché dans `create_order()`
- [ ] Admin Notification : liste avec statuts
