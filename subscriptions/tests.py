"""Tests subscription limits."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from subscriptions.models import (
    PaymentProvider,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionPayment,
)
from subscriptions.services.limits import (
    can_create_flash_sale,
    FREE_MONTHLY_SALES_LIMIT,
)

User = get_user_model()


def _make_seller(phone="+22300000001"):
    user = User.objects.create_user(phone=phone, password="x", display_name="Vendeur")
    return SellerProfile.objects.create(user=user)


def _make_sale(seller, *, months_ago=0, status=FlashSaleStatus.SCHEDULED):
    now = timezone.now()
    sale = FlashSale.objects.create(
        owner=seller,
        title="Vente test",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        status=status,
    )
    if months_ago:
        past = now - timedelta(days=months_ago * 31)
        FlashSale.objects.filter(pk=sale.pk).update(created_at=past)
        sale.created_at = past
    return sale


class FreePlanLimitsTest(TestCase):
    def setUp(self):
        self.seller = _make_seller("+22300000010")
        Subscription.objects.get_or_create(
            seller=self.seller, defaults={"plan": Plan.FREE}
        )

    def test_free_plan_allows_up_to_limit(self):
        for i in range(FREE_MONTHLY_SALES_LIMIT):
            ok, msg = can_create_flash_sale(self.seller)
            self.assertTrue(ok, f"Devrait pouvoir creer la vente {i + 1}")
            _make_sale(self.seller)

    def test_free_plan_blocks_at_limit(self):
        for _ in range(FREE_MONTHLY_SALES_LIMIT):
            _make_sale(self.seller)
        ok, msg = can_create_flash_sale(self.seller)
        self.assertFalse(ok)
        # Le message doit afficher le quota consomme (ex. "3/3 ventes ce mois-ci").
        self.assertIn(f"{FREE_MONTHLY_SALES_LIMIT}/{FREE_MONTHLY_SALES_LIMIT} ventes", msg)

    def test_old_month_sales_do_not_count(self):
        for _ in range(FREE_MONTHLY_SALES_LIMIT):
            _make_sale(self.seller, months_ago=1)
        ok, _ = can_create_flash_sale(self.seller)
        self.assertTrue(ok, "Les ventes du mois precedent ne doivent pas bloquer")


class ProPlanLimitsTest(TestCase):
    def setUp(self):
        self.seller = _make_seller("+22300000020")
        Subscription.objects.get_or_create(
            seller=self.seller, defaults={"plan": Plan.PRO}
        )

    def test_pro_plan_unlimited(self):
        for _ in range(FREE_MONTHLY_SALES_LIMIT + 5):
            _make_sale(self.seller)
        ok, msg = can_create_flash_sale(self.seller)
        self.assertTrue(ok, "Le plan Pro ne doit pas avoir de limite")
        self.assertEqual(msg, "")


class FailClosedQuotaCheckTest(TestCase):
    """can_seller_create_sale() (flash_sales/services/crud.py) doit fail-closed.

    Avant fix : toute exception dans subscriptions (DB down, bug futur, migration
    cassee) etait avalee et retournait silencieusement (True, "") — desactivant
    le quota pour tous les vendeurs sans que personne ne le sache. Desormais une
    exception bloque la creation et est loguee pour investigation.
    """

    def setUp(self):
        self.seller = _make_seller("+22300000040")

    def test_exception_in_limits_blocks_creation(self):
        from flash_sales.services.crud import can_seller_create_sale

        with patch(
            "subscriptions.services.limits.can_create_flash_sale",
            side_effect=RuntimeError("panne simulee (DB indisponible)"),
        ):
            can_create, reason = can_seller_create_sale(self.seller)

        self.assertFalse(can_create, "Une exception doit bloquer, pas laisser passer")
        self.assertTrue(reason, "Un message d'erreur doit etre renvoye au vendeur")

    def test_exception_is_logged_for_investigation(self):
        from flash_sales.services.crud import can_seller_create_sale

        with patch(
            "subscriptions.services.limits.can_create_flash_sale",
            side_effect=RuntimeError("panne simulee (DB indisponible)"),
        ):
            with self.assertLogs("flash_sales.services.crud", level="ERROR") as cm:
                can_seller_create_sale(self.seller)

        self.assertTrue(
            any("Quota check failed" in line for line in cm.output),
            "La panne doit etre loguee, pas seulement avalee silencieusement",
        )

    def test_normal_path_still_works_without_exception(self):
        """Garde-fou : le fix ne doit pas casser le chemin nominal (pas de panne)."""
        from flash_sales.services.crud import can_seller_create_sale

        Subscription.objects.get_or_create(
            seller=self.seller, defaults={"plan": Plan.FREE}
        )
        can_create, reason = can_seller_create_sale(self.seller)
        self.assertTrue(can_create)
        self.assertEqual(reason, "")


class CancelledSalesQuotaTest(TestCase):
    """Une vente CANCELLED ne doit pas compter dans le quota mensuel (fix limits.py)."""

    def setUp(self):
        self.seller = _make_seller("+22300000041")
        Subscription.objects.get_or_create(
            seller=self.seller, defaults={"plan": Plan.FREE}
        )

    def test_cancelled_sales_are_excluded_from_monthly_count(self):
        from subscriptions.services.limits import get_sale_quota

        _make_sale(self.seller, status=FlashSaleStatus.CANCELLED)
        _make_sale(self.seller, status=FlashSaleStatus.CANCELLED)
        _make_sale(self.seller, status=FlashSaleStatus.LIVE)

        quota = get_sale_quota(self.seller)
        self.assertEqual(quota["monthly_count"], 1)
        self.assertTrue(quota["can_create"])

    def test_cancelling_a_sale_frees_a_slot(self):
        sales = [_make_sale(self.seller) for _ in range(FREE_MONTHLY_SALES_LIMIT)]
        ok, _ = can_create_flash_sale(self.seller)
        self.assertFalse(ok, "Quota plein avant annulation")

        sales[0].status = FlashSaleStatus.CANCELLED
        sales[0].save(update_fields=["status"])

        ok, _ = can_create_flash_sale(self.seller)
        self.assertTrue(ok, "Annuler une vente doit liberer un slot de quota")

    def test_other_statuses_still_count_normally(self):
        """Garde-fou : seul CANCELLED est exclu, pas les autres statuts."""
        for status in (
            FlashSaleStatus.SCHEDULED,
            FlashSaleStatus.LIVE,
            FlashSaleStatus.CLOSED,
        ):
            _make_sale(self.seller, status=status)

        ok, msg = can_create_flash_sale(self.seller)
        self.assertFalse(ok, "SCHEDULED/LIVE/CLOSED doivent tous compter")
        # Le message doit afficher le quota consomme (ex. "3/3 ventes ce mois-ci").
        self.assertIn(f"{FREE_MONTHLY_SALES_LIMIT}/{FREE_MONTHLY_SALES_LIMIT} ventes", msg)


class PaymentActivationIdempotenceTest(TestCase):
    """activate_subscription_from_payment() ne doit jamais double-crediter un vendeur."""

    def setUp(self):
        self.seller = _make_seller("+22300000042")

    def _make_payment(self, *, plan=Plan.PRO, status=PaymentStatus.PENDING):
        return SubscriptionPayment.objects.create(
            seller=self.seller,
            plan=plan,
            provider=PaymentProvider.ORANGE,
            amount=5000,
            phone="+22300000042",
            status=status,
            order_id=f"HF-TEST-{uuid.uuid4().hex[:12].upper()}",
            notif_token=uuid.uuid4().hex,
        )

    def test_calling_twice_on_same_payment_does_not_extend_twice(self):
        from subscriptions.services.payment import activate_subscription_from_payment

        payment = self._make_payment()
        sub = activate_subscription_from_payment(payment)
        first_expiry = sub.expires_at

        # Deuxieme appel sur le meme payment (deja SUCCESS) : doit etre un no-op.
        sub_again = activate_subscription_from_payment(payment)
        self.assertEqual(sub_again.expires_at, first_expiry)

    def test_renewal_before_expiry_extends_from_expiry_not_from_now(self):
        from subscriptions.services.payment import activate_subscription_from_payment

        payment1 = self._make_payment()
        sub = activate_subscription_from_payment(payment1)
        first_expiry = sub.expires_at

        # Renouvellement anticipe : meme plan, abonnement pas encore expire.
        payment2 = self._make_payment()
        sub = activate_subscription_from_payment(payment2)

        self.assertEqual(sub.expires_at, first_expiry + timedelta(days=31))

    def test_renewal_after_expiry_starts_from_now_not_from_old_date(self):
        from subscriptions.services.payment import activate_subscription_from_payment

        Subscription.objects.create(
            seller=self.seller,
            plan=Plan.PRO,
            expires_at=timezone.now() - timedelta(days=10),
        )
        payment = self._make_payment()
        sub = activate_subscription_from_payment(payment)

        # Pas de cumul avec l'ancienne date expiree : repart de now() + 31j.
        self.assertGreater(sub.expires_at, timezone.now() + timedelta(days=29))
        self.assertLess(sub.expires_at, timezone.now() + timedelta(days=32))

    def test_cancel_payment_only_affects_pending(self):
        from subscriptions.services.payment import (
            activate_subscription_from_payment,
            cancel_payment,
        )

        payment = self._make_payment()
        activate_subscription_from_payment(payment)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

        # Annuler un payment deja SUCCESS ne doit pas le repasser a CANCELLED.
        cancel_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)


class SubscriptionExpiryTest(TestCase):
    """Un abonnement paye expire doit perdre l'acces aux fonctionnalites payantes."""

    def setUp(self):
        self.seller = _make_seller("+22300000043")

    def test_expired_pro_loses_paid_status_and_stats_access(self):
        sub = Subscription.objects.create(
            seller=self.seller,
            plan=Plan.PRO,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertTrue(sub.is_expired)
        self.assertFalse(sub.is_pro)
        self.assertFalse(sub.is_paid)
        self.assertFalse(sub.has_stats)
        self.assertFalse(sub.has_advanced_stats)
        self.assertTrue(sub.is_free)

    def test_expired_medium_loses_stats_access(self):
        sub = Subscription.objects.create(
            seller=self.seller,
            plan=Plan.MEDIUM,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(sub.is_medium)
        self.assertFalse(sub.has_stats)
        self.assertTrue(sub.is_free)

    def test_non_expired_pro_keeps_paid_status(self):
        sub = Subscription.objects.create(
            seller=self.seller,
            plan=Plan.PRO,
            expires_at=timezone.now() + timedelta(days=10),
        )
        self.assertFalse(sub.is_expired)
        self.assertTrue(sub.is_pro)
        self.assertTrue(sub.has_advanced_stats)

    def test_expired_pro_falls_back_to_free_quota(self):
        """Fix (Option A) : abonnement expire => quota retombe sur FREE (3/mois)."""
        from subscriptions.services.limits import get_sale_quota

        sub = Subscription.objects.create(
            seller=self.seller,
            plan=Plan.PRO,
            expires_at=timezone.now() + timedelta(days=10),  # valide au depart
        )
        for _ in range(FREE_MONTHLY_SALES_LIMIT + 2):  # 5 ventes, > limite FREE
            _make_sale(self.seller)

        # Tant que l'abonnement est valide : illimite, malgre les 5 ventes.
        quota = get_sale_quota(self.seller)
        self.assertTrue(quota["can_create"])
        self.assertIsNone(quota["monthly_limit"])

        # Expiration de l'abonnement PRO.
        sub.expires_at = timezone.now() - timedelta(days=1)
        sub.save(update_fields=["expires_at"])

        quota = get_sale_quota(self.seller)
        self.assertEqual(
            quota["monthly_limit"],
            FREE_MONTHLY_SALES_LIMIT,
            "Doit retomber sur la limite FREE (3), pas rester illimite (PRO)",
        )
        self.assertFalse(
            quota["can_create"],
            "5 ventes ce mois >= limite FREE (3) : doit etre bloque apres expiration",
        )

    def test_expired_pro_blocked_at_create_view(self):
        """Un vendeur PRO dont l'abonnement expire est bloque comme un FREE, au niveau HTTP."""
        from django.urls import reverse

        sub = Subscription.objects.create(
            seller=self.seller,
            plan=Plan.PRO,
            expires_at=timezone.now() + timedelta(days=10),
        )
        for _ in range(FREE_MONTHLY_SALES_LIMIT):  # 3 ventes = limite FREE atteinte
            _make_sale(self.seller)

        sub.expires_at = timezone.now() - timedelta(days=1)
        sub.save(update_fields=["expires_at"])

        self.client.force_login(self.seller.user)
        resp = self.client.post(
            reverse("flash_sales:create"),
            {
                "title": "4e vente apres expiration",
                "description": "",
                "teasers": "",
                "start_time": (timezone.now() + timedelta(days=1)).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "delivery_zone": "",
                "duration_preset": "60",
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "flash_sales/quota_exceeded.html")
        self.assertFalse(
            FlashSale.objects.filter(
                owner=self.seller, title="4e vente apres expiration"
            ).exists(),
            "Aucune vente ne doit etre creee : quota FREE (3) deja atteint",
        )


class BillingRedirectOwnershipTest(TestCase):
    """/billing/return/ et /billing/cancel/ n'agissent que sur les paiements du vendeur connecte."""

    def setUp(self):
        self.owner = _make_seller("+22300000051")
        self.other = _make_seller("+22300000052")
        self.payment = SubscriptionPayment.objects.create(
            seller=self.owner,
            plan=Plan.PRO,
            provider=PaymentProvider.ORANGE,
            amount=5000,
            phone="+22300000051",
            status=PaymentStatus.PENDING,
            order_id="HF-P-a1b2c3d4",
            notif_token=uuid.uuid4().hex,
        )

    def test_other_seller_cannot_cancel_payment(self):
        self.client.force_login(self.other.user)
        resp = self.client.get("/billing/cancel/", {"order_id": self.payment.order_id})
        self.assertEqual(resp.status_code, 302)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    def test_owner_cancel_marks_payment_cancelled(self):
        self.client.force_login(self.owner.user)
        self.client.get("/billing/cancel/", {"order_id": self.payment.order_id})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.CANCELLED)

    def test_other_seller_cannot_see_pending_payment(self):
        self.client.force_login(self.other.user)
        resp = self.client.get("/billing/return/", {"order_id": self.payment.order_id})
        self.assertRedirects(resp, "/seller/abonnement/", fetch_redirect_response=False)

    def test_owner_sees_pending_page(self):
        self.client.force_login(self.owner.user)
        resp = self.client.get("/billing/return/", {"order_id": self.payment.order_id})
        self.assertEqual(resp.status_code, 200)


class MediumPlanLimitsTest(TestCase):
    """MEDIUM = 10 ventes/mois (FREE = 3, PRO = illimite)."""

    def setUp(self):
        self.seller = _make_seller("+22300000030")
        Subscription.objects.get_or_create(
            seller=self.seller,
            defaults={
                "plan": Plan.MEDIUM,
                "expires_at": timezone.now() + timedelta(days=30),
            },
        )

    def test_medium_limit_is_ten(self):
        from subscriptions.models import PLAN_MONTHLY_SALES_LIMIT

        self.assertEqual(PLAN_MONTHLY_SALES_LIMIT[Plan.FREE], 3)
        self.assertEqual(PLAN_MONTHLY_SALES_LIMIT[Plan.MEDIUM], 10)
        self.assertIsNone(PLAN_MONTHLY_SALES_LIMIT[Plan.PRO])

    def test_medium_allows_beyond_free_limit_and_blocks_at_ten(self):
        for _ in range(9):
            _make_sale(self.seller)
        ok, _ = can_create_flash_sale(self.seller)
        self.assertTrue(ok, "La 10e vente doit etre autorisee en MEDIUM")
        _make_sale(self.seller)
        ok, msg = can_create_flash_sale(self.seller)
        self.assertFalse(ok)
        self.assertIn("10/10 ventes", msg)


class OrangeMoneyAmountIsWholeFcfaTest(TestCase):
    """Le montant part chez Orange Money en FCFA entiers : 2000 = 2 000 FCFA."""

    @patch("subscriptions.services.orange_money._get_access_token", return_value="tok")
    @patch("subscriptions.services.orange_money.requests.post")
    def test_plan_price_sent_as_is(self, mock_post, _tok):
        from django.test import override_settings

        from subscriptions.models import PLAN_PRICES
        from subscriptions.services.orange_money import initiate_payment

        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {
            "payment_url": "https://pay.example/x",
            "pay_token": "p",
            "notif_token": "n",
        }
        with override_settings(ORANGE_MONEY_MERCHANT_KEY="mk"):
            initiate_payment(
                amount=PLAN_PRICES[Plan.MEDIUM],
                order_id="HF-TEST-1",
                notif_token="n",
                return_url="https://x/r",
                cancel_url="https://x/c",
                notif_url="https://x/n",
            )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["amount"], 2000)
        self.assertIsInstance(payload["amount"], int)
        self.assertEqual(payload["currency"], "XOF")
