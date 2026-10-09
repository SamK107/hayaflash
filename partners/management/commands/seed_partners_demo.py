"""Données de démonstration du programme partenaires (développement local uniquement).

Refuse de s'exécuter hors dev (ENVIRONMENT != dev ou DEBUG faux). Idempotent.
``--reset`` ne supprime que les données démo : partenaires dont le code commence par
« DEMO » et vendeurs dont le téléphone est dans la plage fictive +22370000900 à
+22370000999.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from partners.models import (
    CommissionEntry,
    OutboundMessage,
    Partner,
    PartnerAccessLink,
    PartnerAcceptance,
    PartnerClick,
    Payout,
    Referral,
)
from partners.services.access_links import hash_token
from partners.services.acceptance import accept_document
from partners.services.commissions import record_for_payment
from partners.services.payouts import build_payout, mark_paid, validate_month
from subscriptions.models import (
    PaymentProvider,
    PaymentStatus,
    Subscription,
    SubscriptionPayment,
)

DEMO_PREFIX = "DEMO"
# Jeton de démonstration CONNU (développement local seulement) : lettre d'essai du prospect.
DEMO_TOKEN = "demo-lien-essai-hayaflash-0001"
DEMO_PHONE_RANGE = [f"+223700009{n:02d}" for n in range(100)]
PARTNERS = [
    # code, nom, téléphone, type, fondateur, statut
    ("DEMOAWA", "Awa Diarra (démo)", "+22370000901", "creator", True, "active"),
    ("DEMOMOU", "Moussa Keita (démo)", "+22370000902", "seller_pilot", True, "active"),
    ("DEMOFAN", "Fanta Traoré (démo)", "+22370000903", "creator", False, "paused"),
]
# Partenaires du bloc H : un prospect (n'a rien accepté) et un partenaire en essai (lettre acceptée).
PROSPECT = ("DEMOPRO", "Aminata Coulibaly (démo, prospect)", "+22370000904")
TRIAL = ("DEMOESS", "Boubacar Sidibé (démo, essai)", "+22370000905")
# (partenaire, n° du vendeur, boutique, plan, montant, mois en arrière du paiement, actif, signalé)
SELLERS = [
    ("DEMOAWA", 1, "Boutique Bamako Style", "medium", 2000, 2, True, False),
    ("DEMOAWA", 2, "Chez Kadi", "pro", 5000, 1, True, False),
    ("DEMOAWA", 3, "Mode Ségou", "medium", 2000, 0, True, False),
    ("DEMOAWA", 4, "Test signalé", "medium", 2000, 0, False, True),
    ("DEMOMOU", 5, "Atelier Kati", "medium", 2000, 1, True, False),
    ("DEMOMOU", 6, "Pas encore payant", "", 0, 0, False, False),
    ("DEMOFAN", 7, "Épicerie Sikasso", "pro", 5000, 0, False, False),
]


class Command(BaseCommand):
    help = "Crée (ou réinitialise avec --reset) des données de démonstration du programme partenaires."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Supprime les données démo, puis les recrée.")

    def handle(self, *args, **options):
        if getattr(settings, "ENVIRONMENT", "") != "dev" or not settings.DEBUG:
            raise CommandError(
                "Commande réservée au développement local (ENVIRONMENT=dev et DEBUG actif). "
                "Elle ne s'exécute jamais en test, en staging ou en production."
            )
        with transaction.atomic():
            if options["reset"]:
                self._reset()
            self._seed()
        self.stdout.write(self.style.SUCCESS("Données démo du programme partenaires prêtes."))

    # -- suppression limitée aux données démo ---------------------------------
    def _reset(self):
        User = get_user_model()
        partners = Partner.objects.filter(code__startswith=DEMO_PREFIX)
        users = User.objects.filter(phone__in=DEMO_PHONE_RANGE)
        sellers = SellerProfile.objects.filter(user__in=users)
        # Preuves et journal sont immuables par conception : seules les données démo sont
        # supprimées ici, en contournant le gestionnaire protégé (jamais pour un vrai partenaire).
        PartnerAcceptance._base_manager.filter(partner__in=partners).delete()
        OutboundMessage._base_manager.filter(partner__in=partners).delete()
        PartnerAccessLink.objects.filter(partner__in=partners).delete()
        CommissionEntry.objects.filter(referral__partner__in=partners).delete()
        Payout.objects.filter(partner__in=partners).delete()
        Referral.objects.filter(partner__in=partners).delete()
        PartnerClick.objects.filter(partner__in=partners).delete()
        Order.service_objects.filter(flash_sale__owner__in=sellers).delete()
        FlashSale.objects.filter(owner__in=sellers).delete()
        SubscriptionPayment.objects.filter(seller__in=sellers).delete()
        Subscription.objects.filter(seller__in=sellers).delete()
        sellers.delete()
        users.delete()
        partners.delete()

    def _seed(self):
        User = get_user_model()
        now = timezone.now()
        partners = {}
        for code, name, phone, kind, founder, status in PARTNERS:
            partner, _ = Partner.objects.get_or_create(
                code=code,
                defaults=dict(
                    name=name, phone=phone, kind=kind, is_founder=founder, status=status,
                    contract_start=timezone.localdate() - timedelta(days=75),
                ),
            )
            partners[code] = partner
            if not partner.acceptances.filter(doc_type="program_terms").exists():
                # Conditions acceptées il y a 100 jours (avant tous les paiements démo).
                accept_document(
                    partner, "program_terms", signer_name=name.split(" (")[0],
                    method="written_manual", manual_reference="Démo : message WhatsApp",
                    accepted_at=now - timedelta(days=100),
                )
            if not partner.clicks.exists():
                for i in range(12 if code == "DEMOAWA" else 5):
                    PartnerClick.objects.create(partner=partner, ip_hash=f"demo{i:012d}")

        for code, n, shop, plan, amount, months_ago, active, flagged in SELLERS:
            phone = f"+223700009{10 + n}"
            user, created = User.objects.get_or_create(
                phone=phone, defaults=dict(display_name=f"Vendeur démo {n}")
            )
            if created:
                user.set_unusable_password()
                user.save()
            seller, _ = SellerProfile.objects.get_or_create(user=user, defaults=dict(business_name=shop))
            referral, _ = Referral.objects.get_or_create(
                seller=seller,
                defaults=dict(
                    partner=partners[code],
                    source="link",
                    signup_ip_hash="demo-ip-flag" if flagged else f"demo{n:012d}",
                    flagged=flagged,
                    flag_reason="Démo : signalé" if flagged else "",
                ),
            )
            if active:
                self._ensure_activity(seller, now)
            if plan:
                payment, _ = SubscriptionPayment.objects.get_or_create(
                    order_id=f"HF-DEMO-{n:04d}",
                    defaults=dict(
                        seller=seller, plan=plan, provider=PaymentProvider.ORANGE, amount=amount,
                        phone=phone, status=PaymentStatus.SUCCESS,
                        notif_token=f"demo-token-{n:040d}",
                        paid_at=now - timedelta(days=30 * months_ago + 2),
                    ),
                )
                record_for_payment(payment)

        self._seed_documents(now)

        # Le mois précédent : validation, versement préparé, payé pour le premier partenaire.
        previous = (timezone.localtime(now).replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        awa = partners["DEMOAWA"]
        periods = sorted(
            {
                timezone.localtime(e.payment.paid_at).strftime("%Y-%m")
                for e in CommissionEntry.objects.filter(referral__partner=awa).select_related("payment")
            }
        )
        for period in periods:
            if period <= previous:
                validate_month(awa, period)
        payout = build_payout(awa, previous) if not Payout.objects.filter(partner=awa, period=previous).exists() else None
        if payout is not None:
            mark_paid(payout, "OM-DEMO-001")

    def _seed_documents(self, now):
        code, name, phone = PROSPECT
        prospect, _ = Partner.objects.get_or_create(
            code=code, defaults=dict(name=name, phone=phone, status="prospect", phase="none", kind="creator")
        )
        PartnerAccessLink.objects.get_or_create(
            token_hash=hash_token(DEMO_TOKEN),
            defaults=dict(partner=prospect, purpose="accept", expires_at=now + timedelta(days=365)),
        )
        code, name, phone = TRIAL
        trial, _ = Partner.objects.get_or_create(
            code=code, defaults=dict(name=name, phone=phone, status="prospect", phase="none", kind="seller_pilot")
        )
        if not trial.acceptances.filter(doc_type="trial_letter").exists():
            accept_document(
                trial, "trial_letter", signer_name=name.split(" (")[0],
                ip_hash="demo", accepted_at=now - timedelta(days=5),
                optional_consents={"cite_shop": True},
            )
        if not OutboundMessage.objects.filter(partner=prospect).exists():
            OutboundMessage.objects.create(
                partner=prospect, phone_e164=prospect.phone, template_key="envoi_lettre_essai",
                body_text="Voici la lettre d'essai à lire et accepter : (jeton non conservé)",
            )
        self.stdout.write(f"Lien de démonstration (lettre d'essai du prospect) : /partenaires/d/{DEMO_TOKEN}/")

    @staticmethod
    def _ensure_activity(seller, now):
        if FlashSale.objects.filter(owner=seller).exists():
            return
        sale = FlashSale.objects.create(
            owner=seller, title="Vente démo", status=FlashSaleStatus.CLOSED,
            start_time=now - timedelta(days=10), end_time=now - timedelta(days=9),
        )
        order = Order.service_objects.create(
            flash_sale=sale, customer_name="Cliente démo", customer_phone="+22370000999"
        )
        Order.service_objects.filter(pk=order.pk).update(created_at=now - timedelta(days=10))
