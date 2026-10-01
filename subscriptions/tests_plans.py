"""Tarifs administrables (PlanConfig) et tarifs speciaux par vendeur.

Couvre la section D du prompt « tarifs administrables » : migration de
donnees, secours fail-closed, changement de prix/limite, tarif special
(ciblage, expiration, epuisement, POST forge, uses_count, duree, refus),
reporting (tests exclus du CA), montant du webhook, garde-fou templates.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import AuditLog
from flash_sales.models import FlashSale, FlashSaleStatus
from subscriptions.models import (
    OverrideReason,
    PaymentProvider,
    PaymentStatus,
    Plan,
    PlanConfig,
    SellerPriceOverride,
    Subscription,
    SubscriptionPayment,
    WebhookLog,
)
from subscriptions.services import plans
from subscriptions.services.plans import (
    DEFAULT_MONTHLY_LIMITS,
    DEFAULT_PRICES,
    get_features,
    get_monthly_limit,
    get_official_price,
    get_price,
    invalidate_plan_cache,
)

User = get_user_model()

FAKE_INIT = {"payment_url": "https://pay.example/om", "raw": {"ok": True, "pay_token": "PT"}}
INIT_PATH = "subscriptions.services.orange_money.initiate_payment"
STATUS_PATH = "subscriptions.services.orange_money.get_transaction_status"


def _seller(phone, *, plan=Plan.FREE, expires_at=None):
    user = User.objects.create_user(phone=phone, password="x", display_name="Vendeur")
    seller = SellerProfile.objects.create(user=user, business_name=f"Boutique {phone[-4:]}")
    Subscription.objects.create(seller=seller, plan=plan, expires_at=expires_at)
    return seller


def _override(seller, **kwargs):
    now = timezone.now()
    data = {
        "seller": seller,
        "plan": Plan.MEDIUM,
        "price": 100,
        "reason": OverrideReason.TEST,
        "starts_at": now - timedelta(minutes=1),
        "expires_at": now + timedelta(hours=2),
        "max_uses": 1,
    }
    data.update(kwargs)
    return SellerPriceOverride.objects.create(**data)


def _make_sale(seller):
    now = timezone.now()
    return FlashSale.objects.create(
        owner=seller,
        title="Vente",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        status=FlashSaleStatus.SCHEDULED,
    )


class PlanCacheIsolation(TestCase):
    """Le cache (LocMem) survit au rollback de chaque test : on le vide."""

    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)


def _initiate(seller, plan=Plan.MEDIUM):
    from subscriptions.services.payment import create_orange_payment

    request = RequestFactory().get("/")
    with patch(INIT_PATH, return_value=FAKE_INIT) as init:
        payment = create_orange_payment(
            seller=seller, plan=plan, phone="+22370000000", request=request
        )
    return payment, init


def _webhook(payment, *, status="SUCCESS", **extra):
    body = {"status": status, "notif_token": payment.notif_token, "txnid": "TX1", **extra}
    # F-61 : le webhook SUCCESS doit etre confirme par Orange (transactionstatus) ;
    # ici Orange confirme, sauf test explicite du contraire (tests_webhook_active_check).
    confirmed = {"status": "SUCCESS", "txn_id": "TX1", "notif_token": "", "amount": None, "raw": {}}
    with patch(STATUS_PATH, return_value=confirmed):
        return Client().post(
            reverse("billing_callback_orange"),
            data=json.dumps(body),
            content_type="application/json",
        )


# ── A. Configuration des plans ────────────────────────────────────────────────


class PlanConfigSeedAndFallbackTests(PlanCacheIsolation):
    def test_data_migration_seeds_three_rows(self):
        rows = {r.plan: r for r in PlanConfig.objects.all()}
        self.assertEqual(set(rows), {Plan.FREE, Plan.MEDIUM, Plan.PRO})
        self.assertEqual((rows[Plan.FREE].price, rows[Plan.FREE].monthly_sales_limit), (0, 3))
        self.assertEqual((rows[Plan.MEDIUM].price, rows[Plan.MEDIUM].monthly_sales_limit), (2000, 10))
        self.assertEqual((rows[Plan.PRO].price, rows[Plan.PRO].monthly_sales_limit), (5000, None))
        self.assertTrue(all(r.duration_days == 31 and r.is_active for r in rows.values()))
        self.assertIn("Tableau de bord LIVE temps réel", rows[Plan.PRO].features)

    def test_features_start_with_generated_quota_line(self):
        self.assertEqual(get_features(Plan.MEDIUM)[0], "10 ventes flash par mois")
        self.assertEqual(get_features(Plan.PRO)[0], "Ventes flash illimitées")

    def test_database_unavailable_falls_back_to_defaults(self):
        with patch.object(plans, "_load_from_db", side_effect=RuntimeError("db down")):
            with self.assertLogs("subscriptions.services.plans", level="ERROR"):
                self.assertEqual(get_official_price(Plan.MEDIUM), DEFAULT_PRICES[Plan.MEDIUM])
            self.assertEqual(get_monthly_limit(Plan.FREE), DEFAULT_MONTHLY_LIMITS[Plan.FREE])

    def test_missing_row_falls_back_for_that_plan(self):
        PlanConfig.objects.filter(plan=Plan.PRO).delete()
        invalidate_plan_cache()
        with self.assertLogs("subscriptions.services.plans", level="ERROR"):
            self.assertEqual(get_official_price(Plan.PRO), 5000)

    def test_quota_still_enforced_when_config_unreadable(self):
        from flash_sales.services.crud import can_seller_create_sale

        seller = _seller("+22371000001")
        for _ in range(3):
            _make_sale(seller)
        with patch.object(plans, "_load_from_db", side_effect=RuntimeError("db down")):
            with self.assertLogs("subscriptions.services.plans", level="ERROR"):
                ok, _ = can_seller_create_sale(seller)
        self.assertFalse(ok)

    def test_quota_fail_closed_if_plan_service_raises(self):
        from flash_sales.services.crud import can_seller_create_sale

        seller = _seller("+22371000002")
        with patch(
            "subscriptions.services.limits.get_monthly_limit", side_effect=RuntimeError("bug")
        ):
            with self.assertLogs("flash_sales", level="ERROR"):
                ok, reason = can_seller_create_sale(seller)
        self.assertFalse(ok)
        self.assertIn("quota", reason)


class PlanConfigValidationTests(PlanCacheIsolation):
    def _cfg(self, plan):
        return PlanConfig.objects.get(plan=plan)

    def test_free_must_stay_zero(self):
        cfg = self._cfg(Plan.FREE)
        cfg.price = 500
        with self.assertRaises(ValidationError):
            cfg.full_clean()

    def test_paid_plan_minimum_100(self):
        cfg = self._cfg(Plan.MEDIUM)
        cfg.price = 50
        with self.assertRaises(ValidationError):
            cfg.full_clean()

    def test_medium_limit_cannot_exceed_pro_limit(self):
        pro = self._cfg(Plan.PRO)
        pro.monthly_sales_limit = 20
        pro.save()
        medium = self._cfg(Plan.MEDIUM)
        medium.monthly_sales_limit = 25
        with self.assertRaises(ValidationError):
            medium.full_clean()
        medium.monthly_sales_limit = 20
        medium.full_clean()  # egalite autorisee

    def test_features_must_be_list_of_strings(self):
        cfg = self._cfg(Plan.PRO)
        cfg.features = "pas une liste"
        with self.assertRaises(ValidationError):
            cfg.full_clean()


class PlanConfigAdminTests(PlanCacheIsolation):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(phone="+22379999999", password="x")
        self.client.force_login(self.admin)

    def test_no_add_no_delete(self):
        self.assertEqual(
            self.client.get(reverse("admin:subscriptions_planconfig_add")).status_code, 403
        )
        cfg = PlanConfig.objects.get(plan=Plan.MEDIUM)
        self.assertEqual(
            self.client.get(
                reverse("admin:subscriptions_planconfig_delete", args=[cfg.pk])
            ).status_code,
            403,
        )

    def test_change_shows_new_payments_only_warning(self):
        cfg = PlanConfig.objects.get(plan=Plan.MEDIUM)
        resp = self.client.get(reverse("admin:subscriptions_planconfig_change", args=[cfg.pk]))
        self.assertContains(resp, "NOUVEAUX paiements uniquement")

    def test_price_change_applies_to_new_payments_only_and_is_audited(self):
        seller = _seller("+22371000003")
        old_payment, _ = _initiate(seller)
        self.assertEqual(old_payment.amount, 2000)

        cfg = PlanConfig.objects.get(plan=Plan.MEDIUM)
        resp = self.client.post(
            reverse("admin:subscriptions_planconfig_change", args=[cfg.pk]),
            {
                "price": "3000",
                "monthly_sales_limit": "10",
                "duration_days": "31",
                "features": json.dumps(cfg.features),
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["adminform"].form.errors)

        new_payment, init = _initiate(seller)
        self.assertEqual(new_payment.amount, 3000)
        self.assertEqual(init.call_args.kwargs["amount"], 3000)
        old_payment.refresh_from_db()
        self.assertEqual(old_payment.amount, 2000)

        log = AuditLog.objects.filter(action="plan_config.updated").latest("id")
        self.assertEqual(log.metadata["changes"]["price"], {"avant": 2000, "apres": 3000})
        cfg.refresh_from_db()
        self.assertEqual(cfg.updated_by, self.admin)

    def test_limit_change_applies_to_quota(self):
        from subscriptions.services.limits import can_create_flash_sale

        seller = _seller("+22371000004")
        _make_sale(seller)
        self.assertTrue(can_create_flash_sale(seller)[0])
        cfg = PlanConfig.objects.get(plan=Plan.FREE)
        cfg.monthly_sales_limit = 1
        cfg.save()  # invalide le cache
        ok, msg = can_create_flash_sale(seller)
        self.assertFalse(ok)
        self.assertIn("1/1 ventes", msg)


# ── B. Tarif special par vendeur ──────────────────────────────────────────────


class SellerPriceOverrideTests(PlanCacheIsolation):
    def setUp(self):
        super().setUp()
        self.seller = _seller("+22372000001")
        self.other = _seller("+22372000002")

    def test_applies_to_target_seller_only(self):
        _override(self.seller)
        self.assertEqual(get_price(Plan.MEDIUM, self.seller), 100)
        self.assertEqual(get_price(Plan.MEDIUM, self.other), 2000)
        self.assertEqual(get_price(Plan.PRO, self.seller), 5000)  # autre plan
        self.assertEqual(get_price(Plan.MEDIUM), 2000)  # sans vendeur

    def test_expired_exhausted_or_disabled_gives_official_price(self):
        o = _override(self.seller)
        now = timezone.now()
        SellerPriceOverride.objects.filter(pk=o.pk).update(expires_at=now - timedelta(seconds=1))
        self.assertEqual(get_price(Plan.MEDIUM, self.seller), 2000)
        SellerPriceOverride.objects.filter(pk=o.pk).update(
            expires_at=now + timedelta(hours=1), uses_count=1
        )
        self.assertEqual(get_price(Plan.MEDIUM, self.seller), 2000)
        SellerPriceOverride.objects.filter(pk=o.pk).update(uses_count=0, is_active=False)
        self.assertEqual(get_price(Plan.MEDIUM, self.seller), 2000)
        SellerPriceOverride.objects.filter(pk=o.pk).update(
            is_active=True, starts_at=now + timedelta(hours=1)
        )
        self.assertEqual(get_price(Plan.MEDIUM, self.seller), 2000)  # pas encore commence

    def test_validation_bounds(self):
        now = timezone.now()
        base = {
            "seller": self.seller,
            "plan": Plan.MEDIUM,
            "reason": OverrideReason.PROMO,
            "starts_at": now,
            "expires_at": now + timedelta(days=1),
        }
        for bad in (
            {"price": 50},  # < 100
            {"price": 2500},  # > prix officiel
            {"price": 500, "expires_at": now + timedelta(days=31)},  # > 30 j
            {"price": 500, "expires_at": now - timedelta(hours=1)},  # fin avant debut
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    SellerPriceOverride(**{**base, **bad}).full_clean()
        SellerPriceOverride(**{**base, "price": 500}).full_clean()

    def test_payment_created_with_special_amount_and_reference(self):
        o = _override(self.seller)
        payment, init = _initiate(self.seller)
        self.assertEqual(payment.amount, 100)
        self.assertTrue(payment.is_special_price)
        self.assertEqual(payment.price_override, o)
        self.assertEqual(init.call_args.kwargs["amount"], 100)
        reference = init.call_args.kwargs["reference"]
        self.assertEqual(reference, "HayaFlash Medium SPECIAL")
        self.assertLessEqual(len(reference), 30)
        o.refresh_from_db()
        self.assertEqual(o.uses_count, 0)  # pas encore paye

    def test_forged_amount_in_post_is_ignored(self):
        self.client.force_login(self.seller.user)
        url = reverse("subscriptions:checkout", args=[Plan.MEDIUM])
        with patch(INIT_PATH, return_value=FAKE_INIT):
            self.client.post(url, {"provider": "orange", "phone": "+22370000000", "amount": "1"})
        self.assertEqual(SubscriptionPayment.objects.get(seller=self.seller).amount, 2000)

        _override(self.seller)
        with patch(INIT_PATH, return_value=FAKE_INIT):
            self.client.post(url, {"provider": "orange", "phone": "+22370000000", "amount": "1"})
        self.assertEqual(
            SubscriptionPayment.objects.filter(seller=self.seller).latest("created_at").amount,
            100,
        )

    def test_checkout_page_shows_special_price(self):
        _override(self.seller)
        self.client.force_login(self.seller.user)
        resp = self.client.get(reverse("subscriptions:checkout", args=[Plan.MEDIUM]))
        self.assertContains(resp, "Tarif spécial")
        self.assertContains(resp, "au lieu de")
        self.assertNotContains(resp, 'name="amount"')

    def test_uses_count_incremented_only_on_success(self):
        o = _override(self.seller)
        failed, _ = _initiate(self.seller)
        _webhook(failed, status="FAILED")
        o.refresh_from_db()
        self.assertEqual(o.uses_count, 0)

        payment, _ = _initiate(self.seller)
        _webhook(payment)
        o.refresh_from_db()
        self.assertEqual(o.uses_count, 1)
        self.assertEqual(get_price(Plan.MEDIUM, self.seller), 2000)  # epuise

    def test_special_duration_applied(self):
        _override(self.seller, duration_days=1)
        payment, _ = _initiate(self.seller)
        _webhook(payment)
        sub = Subscription.objects.get(seller=self.seller)
        self.assertEqual(sub.plan, Plan.MEDIUM)
        delta = sub.expires_at - timezone.now()
        self.assertTrue(timedelta(hours=23) < delta <= timedelta(days=1), delta)

    def test_official_payment_uses_plan_duration(self):
        cfg = PlanConfig.objects.get(plan=Plan.MEDIUM)
        cfg.duration_days = 7
        cfg.save()
        payment, _ = _initiate(self.seller)
        _webhook(payment)
        delta = Subscription.objects.get(seller=self.seller).expires_at - timezone.now()
        self.assertTrue(timedelta(days=6) < delta <= timedelta(days=7), delta)

    def test_refused_if_official_paid_plan_active(self):
        from subscriptions.services.payment import PaymentNotAllowed

        paid = _seller("+22372000003", plan=Plan.PRO, expires_at=timezone.now() + timedelta(days=20))
        _override(paid)
        with self.assertRaises(PaymentNotAllowed):
            _initiate(paid)
        self.assertFalse(SubscriptionPayment.objects.filter(seller=paid).exists())

        # Via la page : message clair, bouton desactive, aucun paiement cree.
        self.client.force_login(paid.user)
        url = reverse("subscriptions:checkout", args=[Plan.MEDIUM])
        self.assertContains(self.client.get(url), "ne s'applique pas")
        with patch(INIT_PATH, return_value=FAKE_INIT):
            resp = self.client.post(url, {"provider": "orange", "phone": "+22370000000"})
        self.assertContains(resp, "Tarif spécial non applicable")
        self.assertFalse(SubscriptionPayment.objects.filter(seller=paid).exists())

    def test_override_admin_create_deactivate_audited(self):
        admin_user = User.objects.create_superuser(phone="+22379999998", password="x")
        self.client.force_login(admin_user)
        now = timezone.now()
        resp = self.client.post(
            reverse("admin:subscriptions_sellerpriceoverride_add"),
            {
                "seller": self.seller.pk,
                "plan": Plan.MEDIUM,
                "price": "100",
                "duration_days": "1",
                "reason": OverrideReason.TEST,
                "reason_detail": "test paiement reel",
                "starts_at_0": timezone.localtime(now).strftime("%Y-%m-%d"),
                "starts_at_1": timezone.localtime(now).strftime("%H:%M:%S"),
                "expires_at_0": timezone.localtime(now + timedelta(hours=2)).strftime("%Y-%m-%d"),
                "expires_at_1": timezone.localtime(now + timedelta(hours=2)).strftime("%H:%M:%S"),
                "max_uses": "1",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        o = SellerPriceOverride.objects.get(seller=self.seller)
        self.assertEqual(o.created_by, admin_user)
        self.assertTrue(AuditLog.objects.filter(action="price_override.created", entity_id=o.pk).exists())

        self.client.post(
            reverse("admin:subscriptions_sellerpriceoverride_changelist"),
            {"action": "deactivate_overrides", "_selected_action": [o.pk]},
        )
        o.refresh_from_db()
        self.assertFalse(o.is_active)
        self.assertTrue(AuditLog.objects.filter(action="price_override.deactivated", entity_id=o.pk).exists())


# ── C. Reporting et webhook ───────────────────────────────────────────────────


class ReportingAndWebhookTests(PlanCacheIsolation):
    def setUp(self):
        super().setUp()
        self.seller = _seller("+22373000001")

    def _paid(self, amount, override=None):
        return SubscriptionPayment.objects.create(
            seller=self.seller,
            plan=Plan.MEDIUM,
            provider=PaymentProvider.ORANGE,
            amount=amount,
            phone="+22370000000",
            order_id=f"HF-T-{SubscriptionPayment.objects.count():08d}",
            notif_token=f"tok{SubscriptionPayment.objects.count()}",
            status=PaymentStatus.SUCCESS,
            paid_at=timezone.now(),
            price_override=override,
            is_special_price=override is not None,
        )

    def test_test_payments_excluded_from_revenue(self):
        from subscriptions.services.platform_reporting import (
            get_orange_remittance_summary,
            get_revenue_breakdown,
            get_subscription_revenue_ytd,
        )

        self._paid(2000)
        self._paid(100, _override(self.seller, reason=OverrideReason.TEST))
        self._paid(1500, _override(self.seller, reason=OverrideReason.PROMO, price=1500))

        self.assertEqual(int(get_subscription_revenue_ytd()), 3500)  # test exclu
        b = get_revenue_breakdown()
        self.assertEqual(b["official"], {"total": 2000, "count": 1})
        self.assertEqual(b["special"], {"total": 1500, "count": 1})
        self.assertEqual(b["test"], {"total": 100, "count": 1})
        # Retrocession Orange : argent reellement encaisse, tests compris.
        self.assertEqual(int(get_orange_remittance_summary()["all_time"]["total_collected"]), 3600)

        staff = User.objects.create_superuser(phone="+22379999997", password="x")
        self.client.force_login(staff)
        resp = self.client.get(reverse("platform_admin"))
        self.assertEqual(resp.context["total_revenue"], 3500)
        self.assertContains(resp, "Tests (hors CA)")

    def test_webhook_amount_mismatch_blocks_activation(self):
        payment, _ = _initiate(self.seller)
        with self.assertLogs("subscriptions.billing_views", level="ERROR"):
            _webhook(payment, amount="1")
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.FREE)
        log = WebhookLog.objects.get(payment=payment)
        self.assertFalse(log.processed)
        self.assertIn("Montant incohérent", log.error_message)

    def test_webhook_unreadable_amount_blocks_activation(self):
        payment, _ = _initiate(self.seller)
        with self.assertLogs("subscriptions.billing_views", level="ERROR"):
            _webhook(payment, amount="deux mille")
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)

    def test_webhook_matching_or_absent_amount_activates_and_stays_idempotent(self):
        payment, _ = _initiate(self.seller)
        _webhook(payment, amount="2000")
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        expires = Subscription.objects.get(seller=self.seller).expires_at
        _webhook(payment)  # rejeu : idempotent
        self.assertEqual(Subscription.objects.get(seller=self.seller).expires_at, expires)

        other = _seller("+22373000002")
        p2, _ = _initiate(other)
        _webhook(p2)  # pas de montant dans le payload (cas documente Orange)
        p2.refresh_from_db()
        self.assertEqual(p2.status, PaymentStatus.SUCCESS)

    def test_legacy_webhook_also_checks_amount(self):
        payment, _ = _initiate(self.seller)
        body = {"status": "SUCCESS", "notif_token": payment.notif_token, "amount": 5}
        with self.assertLogs("subscriptions.views", level="ERROR"):
            Client().post(
                reverse("subscriptions:payment_callback"),
                data=json.dumps(body),
                content_type="application/json",
            )
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)


# ── Garde-fou : aucun tarif ni quota ecrit en dur dans les templates ─────────

PRICE_RE = re.compile(r"\b\d{1,3}(?:[   .]?\d{3})+\s*(?:FCFA|F\s?CFA)\b")
QUOTA_RE = re.compile(r"\b\d+\s+ventes?\s+(?:flash\s+)?par\s+mois\b", re.IGNORECASE)


class NoHardcodedPricesInTemplatesTest(TestCase):
    def test_templates_have_no_literal_price_or_quota(self):
        roots = [Path(d) for d in settings.TEMPLATES[0]["DIRS"]]
        offenders = []
        for root in roots:
            for path in root.rglob("*.html"):
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if PRICE_RE.search(line) or QUOTA_RE.search(line):
                        offenders.append(f"{path}:{n}: {line.strip()[:100]}")
        self.assertEqual(
            offenders,
            [],
            "Tarif/quota en dur : lire depuis le contexte ou {% plan_price %} / "
            "{% plan_quota_label %} (subscriptions/templatetags/plan_tags.py).",
        )


class OrangeNotifTokenTests(PlanCacheIsolation):
    """Orange genere son propre notif_token : c'est lui qui revient dans le webhook
    (bug constate au test reel du 27/09 : abonnement jamais active)."""

    def setUp(self):
        super().setUp()  # vide le cache des tarifs (PlanCacheIsolation)
        self.seller = _seller("+22370009901")

    def _initiate_with_orange_token(self, token="orangeTok32charsXXXXXXXXXXXXXXXX"):
        fake = {
            "payment_url": "https://pay.example/om",
            "raw": {"status": 201, "message": "OK", "pay_token": "p", "notif_token": token},
        }
        request = RequestFactory().post("/")
        request.user = self.seller.user
        from subscriptions.services.payment import create_orange_payment

        with patch(INIT_PATH, return_value=fake):
            return create_orange_payment(
                seller=self.seller, plan=Plan.MEDIUM, phone="+22370000000", request=request
            )

    def test_notif_token_orange_stocke(self):
        payment = self._initiate_with_orange_token()
        self.assertEqual(payment.notif_token, "orangeTok32charsXXXXXXXXXXXXXXXX")

    def test_webhook_avec_token_orange_active_abonnement(self):
        payment = self._initiate_with_orange_token()
        resp = _webhook(payment)
        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.seller.subscription.refresh_from_db()
        self.assertEqual(self.seller.subscription.plan, Plan.MEDIUM)
        self.assertTrue(WebhookLog.objects.filter(payment=payment, processed=True).exists())

    def test_webhook_token_inconnu_trace_sans_activation(self):
        payment = self._initiate_with_orange_token()
        resp = Client().post(
            reverse("billing_callback_orange"),
            data=json.dumps({"status": "SUCCESS", "notif_token": "inconnu", "txnid": "T"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        log = WebhookLog.objects.get(notif_token="inconnu")
        self.assertIsNone(log.payment)
        self.assertFalse(log.processed)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)
