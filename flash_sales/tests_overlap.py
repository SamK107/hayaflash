"""F-90 : un vendeur ne peut pas avoir deux ventes dont les creneaux se chevauchent.

Meme fonction que les autres regles (flash_sales/services/rules.py), appliquee a
la creation, l'edition, le clonage, l'ouverture (manuelle et Celery) et l'admin.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import AuditLog
from flash_sales.models import FlashSale, FlashSaleStatus, SaleOpeningRefused
from flash_sales.services.crud import (
    clone_flash_sale,
    create_flash_sale,
    update_flash_sale,
)
from flash_sales.tasks import auto_open_scheduled_sales
from flash_sales.tests_admin_rules import FMT_D, FMT_T, AdminBase
from flash_sales.tests_rules import BAMAKO, RulesBase, _future_day, _set_plan
from subscriptions.models import Plan

User = get_user_model()


def _msgs(exc):
    return " ".join(exc.messages)


class OverlapBase(RulesBase):
    def setUp(self):
        super().setUp()
        _set_plan(self.seller, Plan.PRO)  # pas de quota : isole la regle testee
        self.day = _future_day(5)
        self.t10 = self.day + timedelta(hours=10)
        # Vente existante : 10h00 -> 11h30
        self.existing = self._sale(start=self.t10, hours=1.5, title="Sacs de luxe")

    def _create(self, start, hours=1):
        return create_flash_sale(
            owner=self.seller,
            title="Nouvelle",
            start_time=start,
            end_time=start + timedelta(hours=hours),
        )

    def assertOverlapRefused(self, call):
        with self.assertRaises(ValidationError) as cm:
            call()
        self.assertIn("Choisissez un autre créneau", _msgs(cm.exception))
        return _msgs(cm.exception)


class CreationOverlapTests(OverlapBase):
    def test_partial_overlap_at_start_refused(self):
        self.assertOverlapRefused(lambda: self._create(self.t10 - timedelta(minutes=30)))

    def test_partial_overlap_at_end_refused(self):
        self.assertOverlapRefused(lambda: self._create(self.t10 + timedelta(hours=1)))

    def test_new_sale_inside_existing_refused(self):
        self.assertOverlapRefused(
            lambda: self._create(self.t10 + timedelta(minutes=15), hours=0.5)
        )

    def test_new_sale_containing_existing_refused(self):
        self.assertOverlapRefused(lambda: self._create(self.t10 - timedelta(minutes=15), hours=2))

    def test_exact_same_slot_refused(self):
        self.assertOverlapRefused(lambda: self._create(self.t10, hours=1.5))

    def test_consecutive_slots_allowed(self):
        self._create(self.t10 + timedelta(hours=1.5))  # debute quand l'autre finit
        self._create(self.t10 - timedelta(hours=1))  # finit quand l'autre debute
        self.assertEqual(FlashSale.objects.filter(owner=self.seller).count(), 3)

    def test_cancelled_sale_is_ignored(self):
        self.existing.status = FlashSaleStatus.CANCELLED
        self.existing.save()
        self._create(self.t10)

    def test_completed_and_closed_count_only_when_slot_overlaps(self):
        for status in (FlashSaleStatus.COMPLETED, FlashSaleStatus.CLOSED):
            FlashSale.objects.all().delete()
            old = self._sale(start=self.t10, hours=1, status=status)
            self.assertOverlapRefused(lambda: self._create(self.t10 + timedelta(minutes=30)))
            self._create(old.end_time)  # creneau different : passe
            self._create(old.start_time - timedelta(hours=1))

    def test_other_seller_never_concerned(self):
        other = SellerProfile.objects.create(
            user=User.objects.create_user(
                phone="+22370000002", password="x", display_name="Autre"
            )
        )
        _set_plan(other, Plan.PRO)
        sale = create_flash_sale(
            owner=other,
            title="Autre vendeur",
            start_time=self.t10,
            end_time=self.t10 + timedelta(hours=1),
        )
        self.assertEqual(sale.owner, other)

    def test_message_is_french_with_local_times_and_title(self):
        msg = self.assertOverlapRefused(lambda: self._create(self.t10))
        local = self.t10.astimezone(BAMAKO)
        self.assertIn("Vous avez déjà une vente de ", msg)
        self.assertIn(local.strftime("%H:%M"), msg)
        self.assertIn((local + timedelta(hours=1.5)).strftime("%H:%M"), msg)
        self.assertIn("(Sacs de luxe)", msg)


class EditOverlapTests(OverlapBase):
    def test_edit_without_self_conflict(self):
        update_flash_sale(sale=self.existing, seller=self.seller, title="Nouveau titre")
        update_flash_sale(
            sale=self.existing,
            seller=self.seller,
            start_time=self.t10 + timedelta(minutes=10),
            end_time=self.t10 + timedelta(hours=1),
        )

    def test_edit_into_another_sale_refused(self):
        other = self._sale(start=self.t10 + timedelta(hours=3), hours=1, title="Autre")
        self.assertOverlapRefused(
            lambda: update_flash_sale(
                sale=other,
                seller=self.seller,
                start_time=self.t10 + timedelta(hours=1),
                end_time=self.t10 + timedelta(hours=2),
            )
        )

    def test_already_overlapping_sale_must_be_moved_to_be_edited(self):
        # Donnees heritees : deux ventes deja chevauchantes (creees avant la regle).
        legacy = self._sale(start=self.t10 + timedelta(minutes=30), hours=1, title="Heritee")
        # Toute edition repasse par la regle : refusee tant que ca chevauche.
        self.assertOverlapRefused(
            lambda: update_flash_sale(sale=legacy, seller=self.seller, title="Renomme")
        )
        # Deplacer la vente hors du conflit corrige la situation.
        update_flash_sale(
            sale=legacy,
            seller=self.seller,
            start_time=self.t10 + timedelta(hours=1.5),
            end_time=self.t10 + timedelta(hours=2.5),
        )

    def test_seller_form_edit_shows_overlap_error(self):
        other = self._sale(start=self.t10 + timedelta(hours=3), hours=1, title="Autre")
        local = timezone.localtime(self.t10 + timedelta(hours=1))
        resp = self.client.post(
            reverse("flash_sales:edit", args=[other.pk]),
            {
                "title": "Autre",
                "description": "",
                "start_time": local.strftime("%Y-%m-%dT%H:%M"),
                "duration_preset": "60",
                "delivery_zone": "",
                "category": "",
            },
        )
        self.assertContains(resp, "Choisissez un autre créneau")
        other.refresh_from_db()
        self.assertEqual(other.start_time, self.t10 + timedelta(hours=3))


class CloneOverlapTests(OverlapBase):
    def test_clone_refused_when_provisional_slot_overlaps(self):
        now = timezone.now()
        FlashSale.objects.create(
            owner=self.seller,
            title="Demain",
            start_time=now + timedelta(days=1, minutes=-30),
            end_time=now + timedelta(days=1, minutes=30),
            status=FlashSaleStatus.SCHEDULED,
        )
        self.assertOverlapRefused(
            lambda: clone_flash_sale(sale=self.existing, seller=self.seller)
        )

    def test_clone_allowed_when_no_overlap(self):
        clone_flash_sale(sale=self.existing, seller=self.seller)


class OpeningOverlapTests(OverlapBase):
    def _live_now(self):
        now = timezone.now()
        return FlashSale.objects.create(
            owner=self.seller,
            title="En cours",
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(minutes=50),
            status=FlashSaleStatus.LIVE,
        )

    def _overlapping_scheduled(self):
        now = timezone.now()
        return FlashSale.objects.create(
            owner=self.seller,
            title="Chevauchante",
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(minutes=59),
            status=FlashSaleStatus.SCHEDULED,
        )

    def test_manual_open_refused_when_overlapping_live_sale(self):
        live = self._live_now()
        sale = self._overlapping_scheduled()
        with self.assertRaises(SaleOpeningRefused) as cm:
            sale.open_sale()
        self.assertIn("Choisissez un autre créneau", str(cm.exception))
        sale.refresh_from_db()
        live.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.SCHEDULED)
        self.assertEqual(live.status, FlashSaleStatus.LIVE)

    def test_manual_open_of_future_sale_checks_shifted_window(self):
        self._live_now()
        sale = self._sale(start=timezone.now() + timedelta(hours=5), hours=1, title="Future")
        with self.assertRaises(SaleOpeningRefused):
            sale.open_sale()  # la fenetre est avancee a "maintenant" : chevauche

    def test_auto_open_refused_and_recorded_and_other_sale_untouched(self):
        live = self._live_now()
        sale = self._overlapping_scheduled()
        end_before = live.end_time
        auto_open_scheduled_sales()
        auto_open_scheduled_sales()  # beat repasse : une seule trace
        sale.refresh_from_db()
        live.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.SCHEDULED)
        self.assertEqual(live.status, FlashSaleStatus.LIVE)
        self.assertEqual(live.end_time, end_before)
        logs = AuditLog.objects.filter(action="flashsale.open_refused", entity_id=sale.pk)
        self.assertEqual(logs.count(), 1)
        self.assertIn("Choisissez un autre créneau", str(logs.first().metadata))

    def test_auto_open_still_works_without_overlap(self):
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.seller,
            title="Ok",
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(minutes=59),
            status=FlashSaleStatus.SCHEDULED,
        )
        auto_open_scheduled_sales()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.LIVE)


class AdminOverlapTests(AdminBase):
    def test_admin_creation_overlapping_is_refused(self):
        _set_plan(self.seller, Plan.PRO)
        t = _future_day(6) + timedelta(hours=10)
        self._existing(t, hours=1, title="Existante")
        before = FlashSale.objects.count()
        resp = self.add(start=t + timedelta(minutes=30))
        self.assertRefused(resp, "Choisissez un autre créneau")
        self.assertEqual(FlashSale.objects.count(), before)

    def test_admin_consecutive_creation_allowed(self):
        _set_plan(self.seller, Plan.PRO)
        t = _future_day(6) + timedelta(hours=10)
        self._existing(t, hours=1)
        self.assertSaved(self.add(start=t + timedelta(hours=1)))

    def test_admin_move_into_other_sale_refused(self):
        _set_plan(self.seller, Plan.PRO)
        t = _future_day(7) + timedelta(hours=10)
        self._existing(t, hours=1, title="A")
        b = self._existing(t + timedelta(hours=3), hours=1, title="B")
        local = timezone.localtime(t + timedelta(minutes=15))
        resp = self.change(
            b,
            start_time_0=local.strftime(FMT_D),
            start_time_1=local.strftime(FMT_T),
            end_time_0=local.strftime(FMT_D),
            end_time_1=(local + timedelta(hours=1)).strftime(FMT_T),
        )
        self.assertRefused(resp, "Choisissez un autre créneau")
