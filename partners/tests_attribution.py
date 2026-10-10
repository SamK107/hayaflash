"""BLOC B : lien /r/<code>/, cookie hf_ref, attribution à l'inscription."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.tests_register_security import payload
from partners.models import Partner, PartnerClick, Referral
from partners.services.attribution import attribute_referral
from partners.tests_models import make_partner, make_seller

User = get_user_model()
REGISTER = "/register/"


def signup(client, phone="+22370000201", **extra):
    return client.post(reverse("register"), payload(phone=phone, **extra))


class ReferralLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.partner = make_partner(code="AWA2026")

    def test_valid_code_records_click_sets_cookie_and_redirects(self):
        resp = self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.1.1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], REGISTER)
        cookie = resp.cookies["hf_ref"]
        self.assertEqual(cookie.value, "AWA2026")
        self.assertEqual(int(cookie["max-age"]), 30 * 24 * 3600)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        click = PartnerClick.objects.get()
        self.assertEqual(click.partner, self.partner)
        self.assertEqual(len(click.ip_hash), 16)
        self.assertNotIn("196.200.1.1", click.ip_hash)

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_cookie_is_secure_when_the_site_is_https_only(self):
        resp = self.client.get("/r/AWA2026/")
        self.assertTrue(resp.cookies["hf_ref"]["secure"])

    def test_code_is_case_insensitive(self):
        resp = self.client.get("/r/awa2026/")
        self.assertEqual(resp.cookies["hf_ref"].value, "AWA2026")

    def test_same_ip_gives_same_hash_other_ip_other_hash(self):
        self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.1.1")
        self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.1.1")
        self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.1.2")
        hashes = list(PartnerClick.objects.order_by("id").values_list("ip_hash", flat=True))
        self.assertEqual(hashes[0], hashes[1])
        self.assertNotEqual(hashes[0], hashes[2])

    def test_unknown_inactive_expired_and_released_look_identical_and_do_nothing(self):
        paused = make_partner(code="PAUSE01", phone="+22360000011", status="paused")
        ended = make_partner(code="ENDED01", phone="+22360000012", status="ended")
        released = make_partner(code="FREE001", phone="+22360000013", status="slot_released")
        expired = make_partner(code="OLD0001", phone="+22360000014")
        Partner.objects.filter(pk=expired.pk).update(
            contract_end=timezone.localdate() - timedelta(days=1)
        )
        for code in ("NOSUCH1", "PAUSE01", "ENDED01", "FREE001", "OLD0001", "@@", "x" * 40):
            with self.subTest(code=code):
                resp = self.client.get(f"/r/{code}/")
                self.assertEqual(resp.status_code, 302)
                self.assertEqual(resp["Location"], REGISTER)
                self.assertNotIn("hf_ref", resp.cookies)
                self.assertEqual(resp.content, b"")
        self.assertEqual(PartnerClick.objects.count(), 0)
        for p in (paused, ended, released, expired):
            self.assertEqual(p.clicks.count(), 0)

    def test_valid_and_invalid_responses_differ_only_by_the_cookie(self):
        ok = self.client.get("/r/AWA2026/")
        bad = self.client.get("/r/NOSUCH1/")
        self.assertEqual((ok.status_code, ok["Location"], ok.content), (bad.status_code, bad["Location"], bad.content))

    def test_redirect_target_is_fixed(self):
        for qs in ("?next=https://evil.example/", "?url=//evil.example", "?redirect=/admin/"):
            resp = self.client.get(f"/r/AWA2026/{qs}")
            self.assertEqual(resp["Location"], REGISTER)

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post("/r/AWA2026/").status_code, 405)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT_REFERRAL_IP=(3, 60))
    def test_rate_limit_per_ip_stops_recording_but_answers_the_same(self):
        for _ in range(3):
            self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.9.9")
        resp = self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.9.9")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], REGISTER)
        self.assertNotIn("hf_ref", resp.cookies)
        self.assertEqual(PartnerClick.objects.count(), 3)
        other = self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.9.10")
        self.assertIn("hf_ref", other.cookies)


class RegisterAttributionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.partner = make_partner(code="AWA2026")

    def referral_of(self, phone):
        return Referral.objects.filter(seller__user__phone=phone).first()

    def test_cookie_attributes_the_new_seller(self):
        self.client.cookies["hf_ref"] = "AWA2026"
        resp = signup(self.client)
        self.assertEqual(resp.status_code, 302)
        ref = self.referral_of("+22370000201")
        self.assertEqual(ref.partner, self.partner)
        self.assertEqual(ref.source, "link")
        self.assertEqual(len(ref.signup_ip_hash), 16)

    def test_typed_code_attributes_as_code_source(self):
        resp = signup(self.client, partner_code="awa2026")
        self.assertEqual(resp.status_code, 302)
        ref = self.referral_of("+22370000201")
        self.assertEqual((ref.partner, ref.source), (self.partner, "code"))

    def test_typed_code_wins_over_cookie(self):
        other = make_partner(code="BOB2026", phone="+22360000003")
        self.client.cookies["hf_ref"] = "AWA2026"
        signup(self.client, partner_code="BOB2026")
        self.assertEqual(self.referral_of("+22370000201").partner, other)

    def test_typed_invalid_code_wins_over_valid_cookie_and_attributes_nothing(self):
        self.client.cookies["hf_ref"] = "AWA2026"
        resp = signup(self.client, partner_code="NOSUCH1")
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self.referral_of("+22370000201"))

    def test_signup_without_code_is_unchanged(self):
        resp = signup(self.client)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Referral.objects.count(), 0)
        self.assertTrue(SellerProfile.objects.filter(user__phone="+22370000201").exists())

    def test_invalid_inactive_expired_released_codes_succeed_without_attribution(self):
        make_partner(code="PAUSE01", phone="+22360000011", status="paused")
        make_partner(code="FREE001", phone="+22360000013", status="slot_released")
        expired = make_partner(code="OLD0001", phone="+22360000014")
        Partner.objects.filter(pk=expired.pk).update(contract_end=timezone.localdate() - timedelta(days=1))
        for i, code in enumerate(("NOSUCH1", "PAUSE01", "FREE001", "OLD0001", "@@@")):
            with self.subTest(code=code):
                phone = f"+2237000030{i}"
                resp = signup(self.client, phone=phone, partner_code=code)
                self.assertEqual(resp.status_code, 302)
                self.assertEqual(resp["Location"], reverse("seller_home"))
                self.assertTrue(User.objects.filter(phone=phone).exists())
                self.assertIsNone(self.referral_of(phone))
                self.client.logout()

    def test_response_is_identical_with_valid_invalid_or_no_code(self):
        results = []
        for i, code in enumerate(("AWA2026", "NOSUCH1", "")):
            resp = signup(self.client, phone=f"+2237000040{i}", partner_code=code)
            results.append((resp.status_code, resp["Location"], resp.content))
            self.client.logout()
        self.assertEqual(len(set(results)), 1)

    def test_attribution_failure_never_breaks_signup(self):
        with patch("partners.services.attribution._create_referral", side_effect=RuntimeError("boom")):
            resp = signup(self.client, partner_code="AWA2026")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(phone="+22370000201").exists())
        self.assertEqual(Referral.objects.count(), 0)

    def test_attribution_is_in_the_same_transaction_as_the_account(self):
        # Si la création du profil vendeur échoue, aucun parrainage orphelin.
        with patch("core.views.record_legal_acceptances", side_effect=RuntimeError("boom")):
            signup(self.client, partner_code="AWA2026")
        self.assertEqual(Referral.objects.count(), 0)
        self.assertFalse(User.objects.filter(phone="+22370000201").exists())

    def test_cookie_is_cleared_after_signup(self):
        self.client.cookies["hf_ref"] = "AWA2026"
        resp = signup(self.client)
        self.assertEqual(resp.cookies["hf_ref"].value, "")

    def test_register_form_prefills_code_from_cookie(self):
        self.client.cookies["hf_ref"] = "AWA2026"
        page = self.client.get(reverse("register"))
        self.assertContains(page, 'name="partner_code"')
        self.assertContains(page, 'value="AWA2026"')
        self.client.cookies.clear()
        self.assertNotContains(self.client.get(reverse("register")), 'value="AWA2026"')


class AntiAbuseTests(TestCase):
    def setUp(self):
        self.partner = make_partner(code="AWA2026", phone="+22360000001")

    def attribute(self, seller, **kw):
        return attribute_referral(seller=seller, partner_code="AWA2026", signup_phone=seller.user.phone, **kw)

    def test_self_referral_by_phone_is_ignored(self):
        seller = make_seller(phone=self.partner.phone)
        self.assertIsNone(self.attribute(seller, ip_hash="h" * 16))
        self.assertEqual(Referral.objects.count(), 0)

    def test_self_referral_ignores_phone_formatting(self):
        seller = make_seller(phone="+22360000001")
        self.assertIsNone(
            attribute_referral(seller=seller, partner_code="AWA2026", signup_phone="+223 6000 0001")
        )

    def test_more_than_three_same_ip_in_seven_days_are_flagged_not_blocked(self):
        refs = [self.attribute(make_seller(phone=f"+2237001000{i}"), ip_hash="h" * 16) for i in range(4)]
        self.assertTrue(all(r is not None for r in refs))
        self.assertEqual(Referral.objects.count(), 4)
        self.assertEqual(Referral.objects.filter(flagged=True).count(), 4)
        self.assertTrue(all(r.flag_reason for r in Referral.objects.filter(flagged=True)))

    def test_three_same_ip_are_not_flagged(self):
        for i in range(3):
            self.attribute(make_seller(phone=f"+2237001000{i}"), ip_hash="h" * 16)
        self.assertEqual(Referral.objects.filter(flagged=True).count(), 0)

    def test_old_referrals_outside_the_week_do_not_count(self):
        for i in range(3):
            r = self.attribute(make_seller(phone=f"+2237001000{i}"), ip_hash="h" * 16)
            Referral.objects.filter(pk=r.pk).update(attributed_at=timezone.now() - timedelta(days=8))
        self.attribute(make_seller(phone="+22370010009"), ip_hash="h" * 16)
        self.assertEqual(Referral.objects.filter(flagged=True).count(), 0)

    def test_other_ip_hashes_are_independent(self):
        for i in range(4):
            self.attribute(make_seller(phone=f"+2237001000{i}"), ip_hash=f"{i}" * 16)
        self.assertEqual(Referral.objects.filter(flagged=True).count(), 0)


class ImmutabilityTests(TestCase):
    def test_referral_cannot_be_reassigned(self):
        a = make_partner(code="AWA2026")
        b = make_partner(code="BOB2026", phone="+22360000003")
        seller = make_seller()
        ref = attribute_referral(seller=seller, partner_code="AWA2026", signup_phone=seller.user.phone)
        again = attribute_referral(seller=seller, partner_code="BOB2026", signup_phone=seller.user.phone)
        self.assertEqual(again.pk, ref.pk)
        self.assertEqual(Referral.objects.get(pk=ref.pk).partner, a)
        ref.partner = b
        with self.assertRaises(Exception):
            ref.save()
        self.assertEqual(Referral.objects.get(pk=ref.pk).partner, a)
