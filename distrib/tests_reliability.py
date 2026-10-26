"""P8 / P10 : indice de fiabilité (SPEC_03 §15.5, test 21) et tableaux de bord (§6, §15.8)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from distrib.models import (
    DistribSettlement,
    DistribStatement,
    ResellerPayout,
)
from distrib.services import dashboard, reliability, statements
from distrib.tests_models import make_distributor
from distrib.tests_settlement import SettlementBase

S = DistribSettlement.Status
User = get_user_model()


class ReliabilityBase(SettlementBase):
    def make_lines(self, statuses, *, age_days=0):
        """Une ligne par statut, créée par le vrai circuit de commande puis repositionnée."""
        lines = []
        stamp = timezone.now() - timedelta(days=age_days)
        for status in statuses:
            line = self.line(self.place(phone=f"+2237600{len(lines) + 10 + self.n:04d}"))
            DistribSettlement.objects.filter(pk=line.pk).update(
                status=status, created_at=stamp, updated_at=stamp,
                paid_confirmed_at=stamp if status == S.PAID_CONFIRMED else None,
            )
            lines.append(line.pk)
        return DistribSettlement.objects.filter(pk__in=lines)

    def statement(self, status, *, closed_days_ago=0, amount=1000):
        today = timezone.localdate()
        n = DistribStatement.objects.count()
        return DistribStatement.objects.create(
            distributor=self.d, invite=self.invite, status=status, amount=amount, line_count=1,
            period_start=today - timedelta(days=7 * (n + 2)), period_end=today - timedelta(days=7 * (n + 1)),
            closed_at=timezone.now() - timedelta(days=closed_days_ago),
        )


class ReliabilityIndexTests(ReliabilityBase):
    def test_test21_exact_figures_on_a_known_dataset(self):
        lines = self.make_lines([S.PAID_CONFIRMED] * 7 + [S.NOT_DELIVERED] * 2 + [S.CANCELLED])
        nd = list(lines.filter(status=S.NOT_DELIVERED))
        DistribSettlement.objects.filter(pk=nd[0].pk).update(not_delivered_reason="refused")
        DistribSettlement.objects.filter(pk=nd[1].pk).update(not_delivered_reason="other")
        confirmed = list(lines.filter(status=S.PAID_CONFIRMED))
        for pk_, source in zip(confirmed, ["customer"] * 3 + ["distributor"] * 2 + ["auto"] * 2):
            DistribSettlement.objects.filter(pk=pk_.pk).update(confirmation_source=source)
        DistribSettlement.objects.filter(pk=confirmed[0].pk).update(conflict_flag=True)
        # Hors fenêtre : ne compte nulle part.
        self.make_lines([S.NOT_DELIVERED] * 3, age_days=45)
        # Un versement contesté récent, un ancien ; un relevé en retard.
        statement = self.statement(DistribStatement.Status.PAID)
        ResellerPayout.objects.create(
            distributor=self.d, invite=self.invite, statement=statement, attempt=1, amount=1000,
            om_reference="OM1", status=ResellerPayout.Status.CONTESTED,
        )
        old = self.statement(DistribStatement.Status.PAID)
        ResellerPayout.objects.create(
            distributor=self.d, invite=self.invite, statement=old, attempt=1, amount=1000,
            om_reference="OM0", status=ResellerPayout.Status.CONTESTED,
            paid_at=timezone.now() - timedelta(days=40),
        )
        self.statement(DistribStatement.Status.TO_PAY, closed_days_ago=10)
        self.statement(DistribStatement.Status.TO_PAY, closed_days_ago=1)  # pas encore en retard (3 j)

        r = reliability.reliability(self.d)

        self.assertEqual((r["total"], r["not_delivered"]), (9, 2))  # annulée et ancien hors compte
        self.assertEqual(r["not_delivered_percent"], Decimal("22.2"))
        self.assertEqual(r["reasons"], {"refused": 1, "absent": 0, "cancelled": 0, "other": 1})
        self.assertEqual((r["conflicts"], r["contested"], r["overdue"]), (1, 1, 1))
        self.assertEqual(r["confirmed_total"], 7)
        self.assertEqual(
            {k: (v["count"], v["percent"]) for k, v in r["sources"].items()},
            {"distributor": (2, Decimal("28.6")), "customer": (3, Decimal("42.9")), "auto": (2, Decimal("28.6"))},
        )
        self.assertEqual(
            r["alerts"],
            [reliability.ALERT_NOT_DELIVERED, reliability.ALERT_CONFLICTS,
             reliability.ALERT_CONTESTED, reliability.ALERT_OVERDUE],
        )

    def test_not_delivered_threshold_is_strict_and_configurable(self):
        self.make_lines([S.PAID_CONFIRMED] * 8 + [S.NOT_DELIVERED] * 2)
        self.assertEqual(reliability.reliability(self.d)["alerts"], [])  # 20 % pile : pas d'alerte
        self.make_lines([S.NOT_DELIVERED])
        self.assertIn(reliability.ALERT_NOT_DELIVERED, reliability.reliability(self.d)["alerts"])
        self.d.alert_not_delivered_percent = 50
        self.assertNotIn(reliability.ALERT_NOT_DELIVERED, reliability.reliability(self.d)["alerts"])
        self.d.alert_not_delivered_percent = 0  # 0 = alerte désactivée
        self.assertNotIn(reliability.ALERT_NOT_DELIVERED, reliability.reliability(self.d)["alerts"])

    def test_empty_history_is_quiet(self):
        r = reliability.reliability(self.d)
        self.assertEqual((r["total"], r["not_delivered_percent"], r["alerts"]), (0, Decimal("0.0"), []))
        self.assertEqual(r["sources"]["auto"]["percent"], Decimal("0.0"))

    def test_conflict_and_contest_thresholds(self):
        line = self.make_lines([S.NOT_DELIVERED])[0]
        DistribSettlement.objects.filter(pk=line.pk).update(conflict_flag=True)
        self.d.alert_conflicts = 2
        self.assertNotIn(reliability.ALERT_CONFLICTS, reliability.reliability(self.d)["alerts"])
        self.d.alert_conflicts = 1
        self.assertIn(reliability.ALERT_CONFLICTS, reliability.reliability(self.d)["alerts"])

    def test_the_index_is_scoped_to_one_distributor(self):
        other = make_distributor(phone="+22371000077", name="Autre")
        self.make_lines([S.NOT_DELIVERED] * 3)
        self.assertEqual(reliability.reliability(other)["total"], 0)


class DashboardFiguresTests(ReliabilityBase):
    def test_distributor_summary_figures(self):
        lines = self.make_lines([S.ORDERED, S.IN_DELIVERY, S.PAID_CONFIRMED, S.NOT_DELIVERED, S.CANCELLED])
        confirmed = lines.get(status=S.PAID_CONFIRMED)
        DistribSettlement.objects.filter(pk=confirmed.pk).update(sale_amount=4800, reseller_margin=1800)
        s = dashboard.distributor_summary(self.d)
        self.assertEqual(s["orders_today"], 4)  # l'annulée n'est pas comptée
        self.assertEqual((s["in_delivery"], s["to_confirm"]), (1, 2))  # ordered + in_delivery
        self.assertEqual(s["revenue_month"], Decimal("4800"))
        self.assertEqual(s["margins_due"], Decimal("1800"))

    def test_format_remaining(self):
        self.assertEqual(dashboard.format_remaining(30), "1 min")
        self.assertEqual(dashboard.format_remaining(3600), "1 h")
        self.assertEqual(dashboard.format_remaining(5 * 3600 + 20 * 60), "5 h 20 min")
        self.assertEqual(dashboard.format_remaining(2 * 86400 + 3 * 3600), "2 j 3 h")
        self.assertEqual(dashboard.format_remaining(-5), "1 min")


@override_settings(DISTRIB_ENABLED=True)
class DashboardPagesTests(ReliabilityBase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(phone="+22390000019", password="x", display_name="Eq", is_staff=True)
        self.other = make_distributor(phone="+22371000088", name="Concurrent")

    def test_every_dashboard_polls_every_30_seconds_and_the_fragments_are_not_cached(self):
        self.client.force_login(self.d.user)
        for page, fragment in [
            ("/distrib/", "/distrib/accueil/direct/"),
            ("/distrib/commandes/", "/distrib/commandes/direct/"),
            ("/distrib/revendeurs/", "/distrib/revendeurs/direct/"),
        ]:
            html = self.client.get(page).content.decode()
            self.assertIn('hx-trigger="every 30s"', html, page)
            self.assertIn(f'hx-get="{fragment}', html, page)
            resp = self.client.get(fragment)
            self.assertEqual(resp.status_code, 200, fragment)
            self.assertNotIn("<html", resp.content.decode(), fragment)
            self.assertIn("no-store", resp["Cache-Control"], fragment)
        self.client.force_login(self.seller.user)
        for page, fragment in [
            ("/distrib/mes-grossistes/", "/distrib/mes-grossistes/direct/"),
            ("/distrib/mes-gains/", "/distrib/mes-gains/direct/"),
        ]:
            self.assertIn('hx-trigger="every 30s"', self.client.get(page).content.decode(), page)
            self.assertEqual(self.client.get(fragment).status_code, 200, fragment)
        self.client.force_login(self.staff)
        self.assertIn('hx-trigger="every 30s"', self.client.get("/distrib/pilotage/").content.decode())
        self.assertEqual(self.client.get("/distrib/pilotage/direct/").status_code, 200)

    def test_fragments_follow_the_same_access_rules_as_their_pages(self):
        for url in ["/distrib/accueil/direct/", "/distrib/commandes/direct/", "/distrib/revendeurs/direct/",
                    "/distrib/pilotage/direct/", "/distrib/mes-gains/direct/", "/distrib/mes-grossistes/direct/"]:
            self.assertEqual(self.client.get(url).status_code, 302, url)  # anonyme
        self.client.force_login(self.seller.user)
        for url in ["/distrib/accueil/direct/", "/distrib/commandes/direct/", "/distrib/pilotage/direct/"]:
            self.assertEqual(self.client.get(url).status_code, 403, url)  # revendeur
        self.client.force_login(self.d.user)
        for url in ["/distrib/pilotage/direct/", "/distrib/mes-gains/direct/"]:
            self.assertEqual(self.client.get(url).status_code, 403, url)  # grossiste, pas staff/boutique
        with override_settings(DISTRIB_ENABLED=False):
            for url in ["/distrib/accueil/direct/", "/distrib/commandes/direct/", "/distrib/pilotage/direct/"]:
                self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_home_shows_only_my_figures(self):
        self.make_lines([S.ORDERED, S.IN_DELIVERY])
        self.client.force_login(self.other.user)
        html = self.client.get("/distrib/accueil/direct/").content.decode()
        self.assertNotIn("à suivre", html)  # aucune commande chez le concurrent
        self.client.force_login(self.d.user)
        self.assertIn("2 commandes à suivre", self.client.get("/distrib/accueil/direct/").content.decode())

    def test_countdown_reads_in_days_hours_and_minutes(self):
        line = self.make_lines([S.IN_DELIVERY])[0]
        DistribSettlement.objects.filter(pk=line.pk).update(
            confirmed_at=timezone.now(), auto_confirm_at=timezone.now() + timedelta(hours=5, minutes=20, seconds=30)
        )
        self.client.force_login(self.d.user)
        self.assertContains(self.client.get("/distrib/commandes/direct/"), "Confirmée automatiquement dans 5 h 20 min")
        self.assertContains(self.client.get("/distrib/accueil/direct/"), "Confirmée automatiquement dans 5 h 20 min")
        self.assertContains(self.client.get("/distrib/commandes/direct/"), "data-dx-until=")

    def test_reliability_is_visible_to_staff_only(self):
        self.make_lines([S.PAID_CONFIRMED] * 2 + [S.NOT_DELIVERED] * 2)
        self.client.force_login(self.staff)
        page = self.client.get("/distrib/pilotage/direct/")
        self.assertContains(page, "Fiabilité")
        self.assertRegex(page.content.decode(), r"50[.,]0 %")
        self.assertContains(page, "Trop de « Pas livré »")
        for user in (self.d.user, self.seller.user):
            self.client.force_login(user)
            for url in ["/distrib/", "/distrib/accueil/direct/", "/distrib/commandes/", "/distrib/revendeurs/",
                        "/distrib/mes-gains/", "/distrib/mes-grossistes/", "/distrib/stock/", "/distrib/releves/"]:
                resp = self.client.get(url)
                if resp.status_code == 200:
                    self.assertNotContains(resp, "Fiabilité", msg_prefix=url)
                    self.assertNotContains(resp, "Trop de « Pas livré »", msg_prefix=url)

    def test_pilotage_lists_alerting_distributors_first(self):
        make_distributor(phone="+22371000099", name="Aaa Calme")
        self.make_lines([S.NOT_DELIVERED] * 2)
        self.client.force_login(self.staff)
        html = self.client.get("/distrib/pilotage/direct/").content.decode()
        self.assertLess(html.index(self.d.business_name), html.index("Aaa Calme"))

    def test_reseller_overview_shows_sales_stock_and_dues(self):
        self.make_lines([S.PAID_CONFIRMED])
        DistribSettlement.objects.filter(status=S.PAID_CONFIRMED).update(reseller_margin=1800)
        self.client.force_login(self.d.user)
        page = self.client.get("/distrib/revendeurs/direct/")
        self.assertContains(page, "1 vente confirmée")
        self.assertContains(page, "1800 FCFA")
        self.assertContains(page, "en stock alloué")

    def test_my_wholesalers_links_to_my_gains_with_the_amount_due(self):
        self.make_lines([S.PAID_CONFIRMED])
        DistribSettlement.objects.filter(status=S.PAID_CONFIRMED).update(reseller_margin=1800)
        self.client.force_login(self.seller.user)
        page = self.client.get("/distrib/mes-grossistes/")
        self.assertContains(page, "Mes gains")
        self.assertContains(page, "1800 FCFA restant dû")


@override_settings(DISTRIB_ENABLED=True)
class NoFreeTextTests(ReliabilityBase):
    """§15.8 : gros boutons, pas de saisie libre hors motif « Autre »."""

    def test_not_delivered_note_is_only_read_for_the_other_reason(self):
        line = self.make_lines([S.IN_DELIVERY])[0]
        self.client.force_login(self.d.user)
        self.client.post(f"/distrib/commandes/{line.pk}/pas-livre/", {"reason": "absent", "note": "texte libre"})
        line.refresh_from_db()
        self.assertEqual((line.status, line.not_delivered_note), (S.NOT_DELIVERED, ""))

    def test_other_reason_still_requires_a_note(self):
        line = self.make_lines([S.IN_DELIVERY])[0]
        self.client.force_login(self.d.user)
        self.client.post(f"/distrib/commandes/{line.pk}/pas-livre/", {"reason": "other", "note": ""})
        line.refresh_from_db()
        self.assertEqual(line.status, S.IN_DELIVERY)

    def test_the_note_input_is_hidden_until_other_is_chosen(self):
        line = self.make_lines([S.IN_DELIVERY])[0]
        self.client.force_login(self.d.user)
        html = self.client.get("/distrib/commandes/").content.decode()
        self.assertIn('data-dx-when-other="other" hidden', html)
        self.assertIn("data-dx-reason", html)
        self.assertIn(f'id="reason-{line.pk}"', html)

    def _declared_payout(self):
        self.make_lines([S.PAID_CONFIRMED])
        statement = self.statement(DistribStatement.Status.TO_PAY)
        return statements.declare_paid(statement, self.d.user, "OM123")

    def test_not_received_uses_a_fixed_choice_list(self):
        payout = self._declared_payout()
        self.client.force_login(self.seller.user)
        html = self.client.get("/distrib/mes-gains/").content.decode()
        self.assertIn('name="reason" required data-dx-reason', html)
        self.assertNotIn('<input class="hf-input" id="why-', html)
        self.client.post(
            f"/distrib/mes-gains/versements/{payout.pk}/repondre/",
            {"decision": "contest", "reason": "wrong_amount", "note": "ignoré"},
        )
        payout.refresh_from_db()
        self.assertEqual(payout.status, ResellerPayout.Status.CONTESTED)
        self.assertEqual(payout.contest_reason, "Le montant reçu est différent")

    def test_free_reason_text_is_refused_and_other_needs_a_note(self):
        payout = self._declared_payout()
        self.client.force_login(self.seller.user)
        url = f"/distrib/mes-gains/versements/{payout.pk}/repondre/"
        self.client.post(url, {"decision": "contest", "reason": "n'importe quoi"})
        self.client.post(url, {"decision": "contest", "reason": "other", "note": "  "})
        payout.refresh_from_db()
        self.assertEqual(payout.status, ResellerPayout.Status.DECLARED)
        self.client.post(url, {"decision": "contest", "reason": "other", "note": "Mauvais numéro"})
        payout.refresh_from_db()
        self.assertEqual(payout.contest_reason, "Autre : Mauvais numéro")

    def test_contest_reason_text_helper(self):
        self.assertEqual(statements.contest_reason_text("no_money"), "Je n'ai rien reçu sur mon Orange Money")
        self.assertEqual(statements.contest_reason_text("inconnu"), "")
        self.assertEqual(statements.contest_reason_text("other", ""), "")
        self.assertEqual(len(statements.contest_reason_text("other", "x" * 500)), len("Autre : ") + 150)


class NoInlineScriptTests(ReliabilityBase):
    """CSP sans 'unsafe-inline' (CLAUDE.md point 12) : les nouveaux écrans n'embarquent aucun script."""

    @override_settings(DISTRIB_ENABLED=True)
    def test_new_screens_have_no_inline_script_or_handler(self):
        staff = User.objects.create_user(phone="+22390000029", password="x", display_name="Eq", is_staff=True)
        import re

        for user, urls in [
            (self.d.user, ["/distrib/", "/distrib/commandes/", "/distrib/revendeurs/"]),
            (self.seller.user, ["/distrib/mes-grossistes/", "/distrib/mes-gains/"]),
            (staff, ["/distrib/pilotage/"]),
        ]:
            self.client.force_login(user)
            for url in urls:
                html = self.client.get(url).content.decode()
                self.assertFalse(re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html), url)
                self.assertFalse(re.search(r"\son(click|change|submit|load)=", html), url)
                self.assertIn("distrib/live.js", html, url)
