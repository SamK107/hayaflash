"""P7 : commission, releves hebdomadaires, versements, plafonds (SPEC_03 §5.5-5.6, §15.4, §15.6, §15.7).

Couvre SPEC §10 tests 10 et 11 et §15.11 tests 18 a 20 et 22 a 25.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings
from django.utils import timezone

from core.models import AuditLog
from distrib.models import (
    DistribPayment,
    DistribSettlement,
    DistribStatement,
    ResellerInvite,
    ResellerPayout,
)
from distrib.services import allocation, ceilings, commission, statements
from distrib.services import settlement as svc
from distrib.tests_models import make_seller
from distrib.tests_settlement import SettlementBase
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import OrderStatus
from products.models import FlashSaleProduct
from products.services.crud import attach_product_to_sale

S = DistribSettlement.Status
SS = DistribStatement.Status
PS = ResellerPayout.Status

MONDAY = datetime(2026, 10, 26, 10, 0)  # lundi : la semaine ecoulee va du 19 au 25 octobre


def aware(*args) -> datetime:
    return timezone.make_aware(datetime(*args))


class MoneyBase(SettlementBase):
    def confirmed(self, at, *, qty=1, imported=None, sale=None, source="distributor", promo=None, phone="+22376000001"):
        """Ligne `paid_confirmed` a l'instant `at` (passe par le vrai circuit de commande)."""
        imported = imported or self.imported
        sale = sale or self.sale
        if promo is not None:
            FlashSaleProduct.objects.filter(flash_sale=sale, product=imported.product).update(promo_price=promo)
        self.n += 1
        from orders.services.create_order import create_order

        with self.captureOnCommitCallbacks(execute=True):
            order = create_order(
                {
                    "flash_sale_id": sale.pk, "customer_name": "Cliente", "customer_phone": phone,
                    "client_request_id": f"money-{self.n}-{imported.pk}",
                    "items": [{"product_id": imported.product_id, "quantity": qty}],
                    "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
                }
            )
        line = DistribSettlement.objects.get(order=order)
        svc.confirm_paid(line, source=source, by=self.d.user if source == "distributor" else None, at=at)
        return DistribSettlement.objects.get(pk=line.pk)

    def second_reseller(self, phone="+22370000002"):
        seller = make_seller(phone, "Fanta")
        invite = ResellerInvite.objects.create(
            distributor=self.d, display_name="Fanta", phone=phone,
            status=ResellerInvite.Status.ACCEPTED, seller=seller,
        )
        imported = allocation.import_product(
            invite=invite, wholesale_product=self.wp, retail_price=4800, actor=self.d.user, quantity=10
        )
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=seller, title="Live 2", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=2), status=FlashSaleStatus.LIVE,
        )
        attach_product_to_sale(flash_sale=sale, product=imported.product)
        return invite, imported, sale

    def week_statement(self, *lines_at, **kw):
        """Cree des lignes confirmees dans la semaine du 19 au 25/10 et clot le releve."""
        lines = [self.confirmed(at, **kw) for at in lines_at]
        statements.close_weekly_statements(now=aware(2026, 10, 26, 10, 0))
        return DistribStatement.objects.get(invite=lines[0].invite), lines


class CommissionTests(MoneyBase):
    """§10 test 10 et §15.11 test 20."""

    def test_rate_minimum_maximum_and_rounding(self):
        d = self.d
        day = date(2026, 10, 25)
        self.assertEqual(commission.commission_for(d, 4800, day)[0], Decimal("288"))  # 6 %
        self.assertEqual(commission.commission_for(d, 1000, day)[0], Decimal("250"))  # minimum
        self.assertEqual(commission.commission_for(d, 40000, day)[0], Decimal("1500"))  # plafond par commande
        d.commission_rate = Decimal("5.5")
        self.assertEqual(commission.commission_for(d, 4810, day)[0], Decimal("265"))  # 264,55 arrondi au FCFA
        self.assertEqual(commission.commission_for(d, 4801, day)[0], Decimal("264"))  # 264,055
        d.commission_min = Decimal("0")
        self.assertEqual(commission.commission_for(d, 1000, day)[0], Decimal("55"))  # minimum a 0
        self.assertEqual(commission.commission_for(d, 0, day), (Decimal("0"), False))

    def test_amounts_are_whole_fcfa(self):
        amount, _ = commission.commission_for(self.d, Decimal("4833"), date(2026, 10, 25))
        self.assertEqual(amount, amount.to_integral_value())

    def test_computed_from_month_one_but_not_billable_during_the_pilot(self):
        self.d.pilot_until = timezone.localdate() + timedelta(days=20)
        self.d.save()
        line = self.confirmed(timezone.now())
        self.assertEqual((line.commission_amount, line.commission_billable), (Decimal("288"), False))
        self.assertEqual(ceilings.commission_outstanding(self.d), Decimal("0"))  # l'encours ne compte que le facturable

    def test_billable_only_after_pilot_until(self):
        today = timezone.localdate()
        for pilot_until, expected in (
            (today, False),  # le jour meme : encore offert
            (today - timedelta(days=1), True),
            (None, True),
        ):
            self.d.pilot_until = pilot_until
            self.d.save()
            line = self.confirmed(timezone.now())
            self.assertEqual(line.commission_billable, expected, pilot_until)
            DistribSettlement.objects.filter(pk=line.pk).delete()

    def test_cap_of_1500_per_order_end_to_end(self):
        self.d.pilot_until = None
        self.d.save()
        line = self.confirmed(timezone.now(), qty=9)  # 43 200 FCFA
        self.assertEqual((line.sale_amount, line.commission_amount), (Decimal("43200"), Decimal("1500")))

    def test_commission_computed_whatever_the_confirmation_source(self):
        self.d.pilot_until = None
        self.d.save()
        for source in ("distributor", "customer", "auto"):
            line = self.confirmed(timezone.now(), source=source)
            self.assertEqual(line.commission_amount, Decimal("288"), source)

    def test_outstanding_and_payments(self):
        self.d.pilot_until = None
        self.d.save()
        for _ in range(3):
            self.confirmed(timezone.now())
        self.assertEqual(ceilings.commission_outstanding(self.d), Decimal("864"))
        DistribPayment.objects.create(distributor=self.d, amount=300, reference="OM1")
        self.assertEqual(ceilings.commission_outstanding(self.d), Decimal("564"))

    def test_cancelled_lines_cost_nothing(self):
        line = self.line(self.place())
        self.set_order_status(line.order, OrderStatus.CANCELLED)
        self.assertEqual(DistribSettlement.objects.get().commission_amount, Decimal("0"))

    def test_margin_due_to_resellers_and_statement_amounts(self):
        """§10 test 11 : marges dues exactes avec releves regles."""
        statement, lines = self.week_statement(aware(2026, 10, 20, 9, 0), aware(2026, 10, 22, 9, 0))
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("3600"))
        statements.declare_paid(statement, self.d.user, "OM100")
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("0"))  # declare = regle
        self.confirmed(timezone.now())
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("1800"))


class WeeklyStatementTests(MoneyBase):
    """Test 22."""

    def test_closing_includes_exactly_the_lines_confirmed_until_sunday_235959(self):
        in_a = self.confirmed(aware(2026, 10, 20, 9, 0))
        in_b = self.confirmed(aware(2026, 10, 25, 23, 59, 59))
        late = self.confirmed(aware(2026, 10, 26, 0, 0, 1))  # lundi 00:00:01 : releve SUIVANT
        old = self.confirmed(aware(2026, 10, 2, 9, 0))  # rattrapage : jamais couvert, entre dans ce releve
        self.assertEqual(statements.close_weekly_statements(now=aware(*MONDAY.timetuple()[:5])), 1)
        statement = DistribStatement.objects.get()
        self.assertEqual((statement.period_start, statement.period_end), (date(2026, 10, 19), date(2026, 10, 25)))
        self.assertEqual(statement.status, SS.TO_PAY)
        self.assertEqual((statement.line_count, statement.amount), (3, Decimal("5400")))  # somme des marges, calculee
        self.assertEqual(
            set(statement.lines.values_list("pk", flat=True)), {in_a.pk, in_b.pk, old.pk}
        )
        late.refresh_from_db()
        self.assertIsNone(late.statement_id)
        # La semaine suivante la ligne en retard est reprise.
        statements.close_weekly_statements(now=aware(2026, 11, 2, 10, 0))
        late.refresh_from_db()
        self.assertEqual(late.statement.period_start, date(2026, 10, 26))

    def test_replaying_the_closing_creates_no_duplicate(self):
        self.confirmed(aware(2026, 10, 20, 9, 0))
        now = aware(2026, 10, 26, 10, 0)
        self.assertEqual(statements.close_weekly_statements(now=now), 1)
        self.assertEqual(statements.close_weekly_statements(now=now), 0)
        self.assertEqual(statements.close_weekly_statements(now=now + timedelta(hours=3)), 0)
        self.assertEqual(DistribStatement.objects.count(), 1)

    def test_zero_statement_is_not_created(self):
        self.confirmed(aware(2026, 10, 20, 9, 0), promo=3000)  # marge 0
        self.assertEqual(statements.close_weekly_statements(now=aware(2026, 10, 26, 10, 0)), 0)
        self.assertEqual(DistribStatement.objects.count(), 0)

    def test_one_statement_per_reseller(self):
        invite2, imported2, sale2 = self.second_reseller()
        self.confirmed(aware(2026, 10, 20, 9, 0))
        self.confirmed(aware(2026, 10, 21, 9, 0), imported=imported2, sale=sale2, phone="+22376000009")
        self.assertEqual(statements.close_weekly_statements(now=aware(2026, 10, 26, 10, 0)), 2)
        self.assertEqual({s.invite_id for s in DistribStatement.objects.all()}, {self.invite.pk, invite2.pk})

    def test_only_confirmed_uncovered_lines_are_taken(self):
        self.confirmed(aware(2026, 10, 20, 9, 0))
        self.place()  # commande non confirmee
        statements.close_weekly_statements(now=aware(2026, 10, 26, 10, 0))
        self.assertEqual(DistribStatement.objects.get().line_count, 1)

    def test_the_week_boundaries_use_the_local_calendar(self):
        start, end, cutoff = statements.week_bounds(aware(2026, 10, 28, 15, 0))  # mercredi
        self.assertEqual((start, end), (date(2026, 10, 19), date(2026, 10, 25)))
        self.assertEqual(timezone.localtime(cutoff), aware(2026, 10, 26, 0, 0))

    def test_the_task_runs_the_closing_and_is_off_when_disabled(self):
        self.confirmed(aware(2026, 10, 20, 9, 0))
        from distrib.tasks import close_weekly_statements_task

        with override_settings(DISTRIB_ENABLED=False):
            close_weekly_statements_task()
        self.assertEqual(DistribStatement.objects.count(), 0)
        with mock.patch("django.utils.timezone.now", return_value=aware(2026, 10, 26, 10, 0)):
            close_weekly_statements_task()
        self.assertEqual(DistribStatement.objects.count(), 1)


class PayTests(MoneyBase):
    """Test 23."""

    def setUp(self):
        super().setUp()
        self.statement, self.lines = self.week_statement(aware(2026, 10, 20, 9, 0), aware(2026, 10, 21, 9, 0))

    def test_pay_creates_payout_attempt_1_covering_exactly_the_statement_lines(self):
        invite2, imported2, sale2 = self.second_reseller()
        other = self.confirmed(aware(2026, 10, 22, 9, 0), imported=imported2, sale=sale2, phone="+22376000009")
        statements.close_weekly_statements(now=aware(2026, 10, 26, 12, 0))
        payout = statements.declare_paid(self.statement, self.d.user, " OM-123 456 ")
        self.assertEqual((payout.attempt, payout.status, payout.amount, payout.om_reference), (1, PS.DECLARED, Decimal("3600"), "OM123456"))
        self.assertEqual(payout.recorded_by, self.d.user)
        self.assertEqual(set(payout.lines.values_list("pk", flat=True)), {line.pk for line in self.lines})
        other.refresh_from_db()
        self.assertIsNone(other.payout_id)
        self.statement.refresh_from_db()
        self.assertEqual(self.statement.status, SS.PAID)
        self.assertEqual(payout.contest_deadline - payout.paid_at, timedelta(hours=72))

    def test_reference_is_mandatory_and_cleaned(self):
        for bad in ("", "  ", "---", None):
            with self.assertRaisesMessage(ValidationError, "obligatoire"):
                statements.declare_paid(self.statement, self.d.user, bad)
        self.assertEqual(ResellerPayout.objects.count(), 0)
        self.assertEqual(len(statements.declare_paid(self.statement, self.d.user, "A" * 200).om_reference), 40)

    def test_no_amount_can_be_typed_no_partial_payment(self):
        self.client.force_login(self.d.user)
        self.client.post(f"/distrib/releves/{self.statement.pk}/payer/", {"om_reference": "OM1", "amount": "1"})
        self.assertEqual(ResellerPayout.objects.get().amount, Decimal("3600"))
        form = self.client.get("/distrib/releves/").content.decode()
        self.assertNotIn('name="amount"', form)

    def test_double_click_has_no_further_effect(self):
        statements.declare_paid(self.statement, self.d.user, "OM1")
        with self.assertRaisesMessage(ValidationError, "déjà payé"):
            statements.declare_paid(self.statement, self.d.user, "OM1")
        with self.assertRaises(ValidationError):
            statements.declare_paid(self.statement, self.d.user, "OM2")
        self.assertEqual(ResellerPayout.objects.count(), 1)

    def test_only_the_owner_distributor_can_pay(self):
        other = make_seller("+22371000002", "Autre gros").user
        from distrib.models import Distributor

        stranger = Distributor.objects.create(user=other, business_name="Autre gros")
        with self.assertRaises(PermissionDenied):
            statements.declare_paid(self.statement, stranger.user, "OM1")
        self.client.force_login(stranger.user)
        self.assertEqual(self.client.post(f"/distrib/releves/{self.statement.pk}/payer/", {"om_reference": "OM1"}).status_code, 404)
        self.assertEqual(self.client.get(f"/distrib/releves/{self.statement.pk}/").status_code, 404)
        self.assertEqual(ResellerPayout.objects.count(), 0)

    def test_statement_is_frozen_after_paid(self):
        statements.declare_paid(self.statement, self.d.user, "OM1")
        line = self.lines[0]
        self.set_order_status(line.order, OrderStatus.CANCELLED)
        self.statement.refresh_from_db()
        self.assertEqual((self.statement.amount, self.statement.line_count), (Decimal("3600"), 2))

    def test_view_flow(self):
        self.client.force_login(self.d.user)
        resp = self.client.post(f"/distrib/releves/{self.statement.pk}/payer/", {"om_reference": "OM9"})
        self.assertRedirects(resp, "/distrib/releves/")
        page = self.client.get("/distrib/releves/")
        self.assertContains(page, "OM9")
        self.assertContains(page, "3600")
        self.assertEqual(self.client.get(f"/distrib/releves/{self.statement.pk}/payer/").status_code, 405)


class PayoutLifecycleTests(MoneyBase):
    """Test 18."""

    def setUp(self):
        super().setUp()
        self.statement, self.lines = self.week_statement(aware(2026, 10, 20, 9, 0), aware(2026, 10, 21, 9, 0))

    def reseller_says(self, payout, *, accept, reason=""):
        return statements.answer_payout(payout, self.seller.user, accept=accept, reason=reason)

    def test_silence_means_accepted_after_72_hours_not_before(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.assertEqual(statements.accept_due_payouts(now=payout.contest_deadline - timedelta(seconds=1)), 0)
        self.assertEqual(statements.accept_due_payouts(now=payout.contest_deadline), 1)
        payout.refresh_from_db()
        self.statement.refresh_from_db()
        self.assertEqual((payout.status, payout.accepted_source, self.statement.status), (PS.ACCEPTED, "auto", SS.ACCEPTED))
        self.assertEqual(statements.accept_due_payouts(now=payout.contest_deadline + timedelta(days=9)), 0)

    def test_task_accepts_and_is_off_when_disabled(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        ResellerPayout.objects.filter(pk=payout.pk).update(contest_deadline=timezone.now() - timedelta(minutes=1))
        from distrib.tasks import accept_payouts_task

        with override_settings(DISTRIB_ENABLED=False):
            accept_payouts_task()
        self.assertEqual(ResellerPayout.objects.get().status, PS.DECLARED)
        accept_payouts_task()
        self.assertEqual(ResellerPayout.objects.get().status, PS.ACCEPTED)

    def test_reseller_can_confirm_before_the_deadline(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.reseller_says(payout, accept=True)
        payout.refresh_from_db()
        self.assertEqual((payout.status, payout.accepted_source), (PS.ACCEPTED, "reseller"))

    def test_not_received_contests_the_payout_and_the_statement_and_the_amount_stays_due(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("0"))
        self.reseller_says(payout, accept=False, reason="Rien reçu sur mon Orange Money")
        payout.refresh_from_db()
        self.statement.refresh_from_db()
        self.assertEqual((payout.status, payout.contest_reason), (PS.CONTESTED, "Rien reçu sur mon Orange Money"))
        self.assertEqual((self.statement.status, self.statement.contest_count), (SS.CONTESTED, 1))
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("3600"))  # reste du dans les calculs
        self.assertTrue(AuditLog.objects.filter(action="distrib.signal.payout_contested", entity_id=self.statement.pk).exists())

    def test_contesting_needs_a_reason_and_only_the_concerned_reseller(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        with self.assertRaises(ValidationError):
            self.reseller_says(payout, accept=False, reason="  ")
        invite2, *_ = self.second_reseller()
        with self.assertRaises(PermissionDenied):
            statements.answer_payout(payout, invite2.seller.user, accept=True)
        with self.assertRaises(PermissionDenied):
            statements.answer_payout(payout, self.d.user, accept=True)
        payout.refresh_from_db()
        self.assertEqual(payout.status, PS.DECLARED)

    def test_cannot_answer_twice(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.reseller_says(payout, accept=True)
        with self.assertRaises(ValidationError):
            self.reseller_says(payout, accept=False, reason="finalement non")

    def test_single_redeclaration_with_a_different_reference(self):
        first = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.reseller_says(first, accept=False, reason="non")
        with self.assertRaisesMessage(ValidationError, "nouvelle référence"):
            statements.declare_paid(self.statement, self.d.user, "om1")  # meme reference (casse ignoree)
        with self.assertRaisesMessage(ValidationError, "obligatoire"):
            statements.declare_paid(self.statement, self.d.user, "")
        second = statements.declare_paid(self.statement, self.d.user, "OM2")
        self.assertEqual((second.attempt, second.amount, second.status), (2, Decimal("3600"), PS.DECLARED))
        self.assertEqual(second.contest_deadline - second.paid_at, timedelta(hours=72))  # nouveau delai
        first.refresh_from_db()
        self.assertEqual(first.status, PS.CONTESTED)  # historique conserve
        self.assertEqual({line.payout_id for line in self.statement.lines.all()}, {second.pk})  # lignes repointees
        self.statement.refresh_from_db()
        self.assertEqual(self.statement.status, SS.PAID)
        # Une 2e redeclaration par le grossiste est refusee.
        with self.assertRaises(ValidationError):
            statements.declare_paid(self.statement, self.d.user, "OM3")
        self.assertEqual(ResellerPayout.objects.count(), 2)

    def test_second_contestation_escalates_and_the_distributor_can_do_nothing(self):
        first = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.reseller_says(first, accept=False, reason="non")
        second = statements.declare_paid(self.statement, self.d.user, "OM2")
        self.reseller_says(second, accept=False, reason="toujours rien")
        self.statement.refresh_from_db()
        self.assertEqual((self.statement.status, self.statement.contest_count), (SS.ESCALATED, 2))
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("3600"))
        with self.assertRaisesMessage(ValidationError, "équipe"):
            statements.declare_paid(self.statement, self.d.user, "OM3")
        self.assertTrue(AuditLog.objects.filter(action="distrib.signal.payout_escalated").exists())

    def escalate(self):
        first = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.reseller_says(first, accept=False, reason="non")
        second = statements.declare_paid(self.statement, self.d.user, "OM2")
        self.reseller_says(second, accept=False, reason="non")
        staff = make_seller("+22370000099", "Equipe").user
        staff.is_staff = True
        staff.save()
        return staff

    def test_only_staff_closes_an_escalated_statement(self):
        staff = self.escalate()
        with self.assertRaises(PermissionDenied):
            statements.staff_close_escalated(self.statement, self.d.user, "ok")
        with self.assertRaises(ValidationError):
            statements.staff_close_escalated(self.statement, staff, " ")
        statements.staff_close_escalated(self.statement, staff, "Versement vérifié sur le relevé Orange")
        self.statement.refresh_from_db()
        last = self.statement.payouts.order_by("-attempt").first()
        self.assertEqual((self.statement.status, last.status, last.accepted_source), (SS.ACCEPTED, PS.ACCEPTED, "staff"))
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("0"))
        self.assertTrue(AuditLog.objects.filter(action="distrib.statement_closed_by_staff", actor=staff).exists())

    def test_staff_reopen_detaches_lines_and_lets_the_distributor_pay_again(self):
        staff = self.escalate()
        statements.staff_reopen_escalated(self.statement, staff, "Le revendeur a changé de numéro Orange")
        self.statement.refresh_from_db()
        self.assertEqual((self.statement.status, self.statement.contest_count), (SS.TO_PAY, 0))
        self.assertEqual({line.payout_id for line in self.statement.lines.all()}, {None})
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("3600"))
        again = statements.declare_paid(self.statement, self.d.user, "OM9")
        self.assertEqual((again.attempt, again.status), (3, PS.DECLARED))  # numerotee a la suite, historique intact
        self.assertTrue(AuditLog.objects.filter(action="distrib.statement_reopened_by_staff", actor=staff).exists())

    def test_staff_actions_only_on_escalated_statements(self):
        staff = make_seller("+22370000099", "Equipe").user
        staff.is_staff = True
        staff.save()
        for action in (statements.staff_close_escalated, statements.staff_reopen_escalated):
            with self.assertRaises(ValidationError):
                action(self.statement, staff, "test")

    def test_reseller_views(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.client.force_login(self.seller.user)
        page = self.client.get("/distrib/mes-gains/")
        self.assertContains(page, "Versement reçu ?")
        self.assertContains(page, "OM1")
        resp = self.client.post(f"/distrib/mes-gains/versements/{payout.pk}/repondre/", {"decision": "contest", "reason": "rien"})
        self.assertRedirects(resp, "/distrib/mes-gains/")
        self.assertEqual(ResellerPayout.objects.get().status, PS.CONTESTED)
        # Un autre revendeur ne peut ni voir ni repondre.
        invite2, *_ = self.second_reseller()
        self.client.force_login(invite2.seller.user)
        self.assertNotContains(self.client.get("/distrib/mes-gains/"), "OM1")
        self.assertEqual(
            self.client.post(f"/distrib/mes-gains/versements/{payout.pk}/repondre/", {"decision": "accept"}).status_code, 404
        )

    def test_distributor_cannot_use_the_reseller_answer_endpoint(self):
        payout = statements.declare_paid(self.statement, self.d.user, "OM1")
        self.client.force_login(self.d.user)
        self.assertEqual(
            self.client.post(f"/distrib/mes-gains/versements/{payout.pk}/repondre/", {"decision": "accept"}).status_code, 403
        )


class ReversalAndAlertTests(MoneyBase):
    """Tests 24 et 25."""

    def auto_line(self, at):
        line = self.confirmed(at, source="auto")
        return line

    def test_test24_cancelled_after_auto_confirmation_inside_a_to_pay_statement_recalculates_it(self):
        a = self.auto_line(aware(2026, 10, 20, 9, 0))
        b = self.auto_line(aware(2026, 10, 21, 9, 0))
        statements.close_weekly_statements(now=aware(2026, 10, 26, 10, 0))
        statement = DistribStatement.objects.get()
        self.assertEqual(statement.amount, Decimal("3600"))
        self.set_order_status(b.order, OrderStatus.CANCELLED)
        statement.refresh_from_db()
        self.assertEqual((statement.amount, statement.line_count, statement.status), (Decimal("1800"), 1, SS.TO_PAY))
        self.assertEqual(set(statement.lines.values_list("pk", flat=True)), {a.pk})
        self.assertEqual(DistribSettlement.objects.get(pk=b.pk).status, S.CANCELLED)

    def test_test24_inside_a_paid_statement_nothing_changes_but_a_signal(self):
        a = self.auto_line(aware(2026, 10, 20, 9, 0))
        statements.close_weekly_statements(now=aware(2026, 10, 26, 10, 0))
        statement = DistribStatement.objects.get()
        statements.declare_paid(statement, self.d.user, "OM1")
        self.set_order_status(a.order, OrderStatus.CANCELLED)
        a.refresh_from_db()
        statement.refresh_from_db()
        self.assertEqual((a.status, a.conflict_flag, statement.amount, statement.status), (S.PAID_CONFIRMED, True, Decimal("1800"), SS.PAID))
        self.assertTrue(AuditLog.objects.filter(action="distrib.signal.cancelled_after_confirmation").exists())

    def test_test25_overdue_alert_counts_from_closing_and_uses_the_distributor_delay(self):
        self.confirmed(aware(2026, 10, 20, 9, 0))
        closed = aware(2026, 10, 26, 10, 0)
        statements.close_weekly_statements(now=closed)
        self.assertEqual(self.d.payout_delay_days, 3)
        self.assertEqual(statements.overdue_statements(self.d, now=closed + timedelta(days=3)).count(), 0)  # pas avant
        self.assertEqual(statements.overdue_statements(self.d, now=closed + timedelta(days=3, seconds=1)).count(), 1)
        self.d.payout_delay_days = 5
        self.d.save()
        self.assertEqual(statements.overdue_statements(self.d, now=closed + timedelta(days=4)).count(), 0)
        self.assertEqual(statements.overdue_statements(self.d, now=closed + timedelta(days=5, seconds=1)).count(), 1)

    def test_test25_a_paid_statement_is_never_overdue_but_contested_ones_stay_signalled(self):
        self.confirmed(aware(2026, 10, 20, 9, 0))
        closed = aware(2026, 10, 26, 10, 0)
        statements.close_weekly_statements(now=closed)
        statement = DistribStatement.objects.get()
        payout = statements.declare_paid(statement, self.d.user, "OM1")
        far = closed + timedelta(days=30)
        self.assertEqual(statements.overdue_statements(self.d, now=far).count(), 0)
        statements.answer_payout(payout, self.seller.user, accept=False, reason="non")
        self.assertEqual(statements.unsettled_statements(self.d).count(), 1)
        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("1800"))

    def test_test19_ceiling_unblocks_and_blocks_again_through_the_real_payout_flow(self):
        """80 % -> alerte, > 100 % -> blocage des nouvelles allocations ; deblocage automatique au versement."""
        self.d.reseller_credit_ceiling = Decimal("3000")
        self.d.save()
        self.confirmed(aware(2026, 10, 20, 9, 0))  # 1 800 = 60 %
        self.assertEqual(ceilings.reseller_level(self.invite), "ok")
        self.confirmed(aware(2026, 10, 21, 9, 0))  # 3 600 > 3 000
        self.assertEqual(ceilings.reseller_level(self.invite), "blocked")
        with self.assertRaisesMessage(ValidationError, "Règle les marges dues pour débloquer"):
            allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)
        statements.close_weekly_statements(now=aware(2026, 10, 26, 10, 0))
        statement = DistribStatement.objects.get()
        payout = statements.declare_paid(statement, self.d.user, "OM1")
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)  # debloque
        statements.answer_payout(payout, self.seller.user, accept=False, reason="non")
        with self.assertRaises(ValidationError):  # le montant conteste est de nouveau du
            allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)
        # Jamais bloque : les commandes en cours et la reprise de stock.
        self.place()
        allocation.take_back(imported=self.imported, quantity=1, actor=self.d.user)


class MoneyPagesTests(MoneyBase):
    def test_statements_page_alerts_and_cloisonnement(self):
        self.d.credit_ceiling = Decimal("1000")
        self.d.pilot_until = None
        self.d.save()
        for _ in range(4):
            self.confirmed(timezone.now())  # 4 x 288 = 1 152 > 1 000
        self.client.force_login(self.d.user)
        page = self.client.get("/distrib/releves/")
        self.assertContains(page, "Encours de commission 1152 FCFA")
        self.assertContains(page, "bloquées")
        other = make_seller("+22371000002", "Autre gros").user
        from distrib.models import Distributor

        Distributor.objects.create(user=other, business_name="Autre gros")
        self.client.force_login(other)
        self.assertNotContains(self.client.get("/distrib/releves/"), "Awa")

    def test_commission_offered_label_during_the_pilot(self):
        self.d.pilot_until = timezone.localdate() + timedelta(days=10)
        self.d.save()
        line = self.confirmed(timezone.now())
        self.client.force_login(self.d.user)
        self.assertContains(self.client.get("/distrib/commandes/"), "Commission offerte (période d'essai)")
        self.assertEqual(line.commission_billable, False)

    def test_my_gains_shows_countdown_and_customer_reference_to_the_reseller(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        line = self.line(order)
        self.client.force_login(self.seller.user)
        page = self.client.get("/distrib/mes-gains/")
        self.assertContains(page, "Confirmée automatiquement dans")
        self.assertNotContains(page, line.receipt_token)
        from distrib.services import receipts

        receipts.customer_confirm(line.receipt_token, "OM555")
        self.assertContains(self.client.get("/distrib/mes-gains/"), "OM555")

    def test_my_gains_requires_a_shop_and_the_switch(self):
        self.client.force_login(self.d.user)
        self.assertEqual(self.client.get("/distrib/mes-gains/").status_code, 403)
        self.client.force_login(self.seller.user)
        with override_settings(DISTRIB_ENABLED=False):
            self.assertEqual(self.client.get("/distrib/mes-gains/").status_code, 404)

    def test_pilotage_payment_and_staff_actions(self):
        staff = make_seller("+22370000099", "Equipe").user
        staff.is_staff = True
        staff.save()
        self.client.force_login(self.d.user)
        self.assertEqual(self.client.post(f"/distrib/pilotage/grossistes/{self.d.pk}/reglement/", {"amount": "500"}).status_code, 403)
        self.client.force_login(staff)
        for bad in ("", "abc", "-5", "0", "12.5"):
            self.client.post(f"/distrib/pilotage/grossistes/{self.d.pk}/reglement/", {"amount": bad})
        self.assertEqual(DistribPayment.objects.count(), 0)
        self.client.post(f"/distrib/pilotage/grossistes/{self.d.pk}/reglement/", {"amount": "500", "reference": "OM-PAY"})
        payment = DistribPayment.objects.get()
        self.assertEqual((payment.amount, payment.recorded_by, payment.reference), (500, staff, "OM-PAY"))
        self.assertContains(self.client.get("/distrib/pilotage/"), "encours")
