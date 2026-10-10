"""BLOC G : seed_partners_demo (dev uniquement, idempotent, --reset limité aux données démo)."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from partners.models import CommissionEntry, Partner, Payout, Referral
from partners.tests_models import make_partner, make_seller

DEV = dict(ENVIRONMENT="dev", DEBUG=True)


def run(*args):
    out = StringIO()
    call_command("seed_partners_demo", *args, stdout=out)
    return out.getvalue()


class SeedGuardTests(TestCase):
    def test_refuses_with_test_settings(self):
        with self.assertRaises(CommandError):
            run()
        self.assertEqual(Partner.objects.count(), 0)

    def test_refuses_outside_dev_even_with_debug(self):
        for env in ("staging", "prod"):
            with self.subTest(env=env), override_settings(ENVIRONMENT=env, DEBUG=True):
                with self.assertRaises(CommandError):
                    run()

    def test_refuses_when_debug_is_off(self):
        with override_settings(ENVIRONMENT="dev", DEBUG=False):
            with self.assertRaises(CommandError):
                run()
        self.assertEqual(Partner.objects.count(), 0)


@override_settings(**DEV)
class SeedTests(TestCase):
    def counts(self):
        return (
            Partner.objects.count(),
            Referral.objects.count(),
            CommissionEntry.objects.count(),
            Payout.objects.count(),
        )

    def test_creates_three_partners_with_referrals_and_commissions(self):
        run()
        partners, referrals, entries, payouts = self.counts()
        self.assertEqual(partners, 5)  # 3 sous contrat + 1 prospect + 1 en essai
        self.assertGreaterEqual(referrals, 6)
        self.assertGreaterEqual(entries, 4)
        self.assertGreaterEqual(payouts, 1)
        self.assertTrue(Referral.objects.filter(flagged=True).exists())
        self.assertTrue(Partner.objects.filter(code="DEMOFAN", status="paused").exists())

    def test_demo_phones_are_fictitious(self):
        run()
        for p in Partner.objects.all():
            self.assertTrue(p.phone.startswith("+22370000"), p.phone)
        for r in Referral.objects.select_related("seller__user"):
            self.assertTrue(r.seller.user.phone.startswith("+22370000"))

    def test_idempotent(self):
        run()
        before = self.counts()
        run()
        self.assertEqual(self.counts(), before)

    def test_reset_removes_only_demo_data(self):
        real = make_partner(code="REELLE1", phone="+22360000077", name="Vraie partenaire")
        real_seller = make_seller("+22371234567")
        Referral.objects.create(partner=real, seller=real_seller)
        run()
        run("--reset")
        self.assertTrue(Partner.objects.filter(pk=real.pk).exists())
        self.assertTrue(Referral.objects.filter(partner=real).exists())
        self.assertEqual(Partner.objects.filter(code__startswith="DEMO").count(), 5)

    def test_reset_then_seed_gives_the_same_shape(self):
        run()
        before = self.counts()
        run("--reset")
        self.assertEqual(self.counts(), before)


@override_settings(**DEV)
class SeedDocumentsTests(TestCase):
    def test_prospect_trial_and_contract_partners_exist(self):
        from partners.models import PartnerAcceptance

        run()
        prospect = Partner.objects.get(code="DEMOPRO")
        self.assertEqual((prospect.status, prospect.phase), ("prospect", "none"))
        trial = Partner.objects.get(code="DEMOESS")
        self.assertEqual((trial.status, trial.phase), ("active", "trial"))
        self.assertTrue(trial.acceptances.filter(doc_type="trial_letter").exists())
        self.assertTrue(trial.cite_shop_consent)
        contract = Partner.objects.get(code="DEMOAWA")
        self.assertEqual(contract.phase, "contract")
        self.assertTrue(contract.acceptances.filter(doc_type="program_terms").exists())
        self.assertEqual(PartnerAcceptance.objects.count(), 4)  # 3 contrats + 1 lettre d essai

    def test_demo_consultation_link_works_and_is_announced(self):
        from django.test import Client

        from partners.management.commands.seed_partners_demo import DEMO_TOKEN

        out = run()
        self.assertIn(f"/partenaires/d/{DEMO_TOKEN}/", out)
        resp = Client().get(f"/partenaires/d/{DEMO_TOKEN}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "lettre d")

    def test_reset_clears_documents_and_links_of_demo_only(self):
        from partners.models import OutboundMessage, PartnerAccessLink, PartnerAcceptance

        real = make_partner(code="REELLE2", phone="+22360000078", name="Vraie")
        run()
        run("--reset")
        self.assertTrue(PartnerAcceptance.objects.filter(partner=real).exists())
        self.assertEqual(PartnerAccessLink.objects.count(), 1)
        self.assertEqual(OutboundMessage.objects.count(), 1)
        self.assertEqual(Partner.objects.filter(code__startswith="DEMO").count(), 5)
