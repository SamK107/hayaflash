"""F-46 : l'admin Django ne contourne plus quota / 3 par jour / duree 2 h.

Meme fonction que les autres chemins (flash_sales/services/rules.py), appliquee
par la validation du formulaire admin, a la creation ET a la modification des
champs controles. Client de test Django (pas de navigateur).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.tests_rules import _future_day, _set_plan
from subscriptions.models import Plan

User = get_user_model()
FMT_D, FMT_T = "%Y-%m-%d", "%H:%M:%S"


class AdminBase(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            phone="+22370009999", password="x", display_name="Staff"
        )
        self.client.force_login(self.staff)
        user = User.objects.create_user(phone="+22370000010", password="x", display_name="V")
        self.seller = SellerProfile.objects.create(user=user, business_name="Boutique")
        self.other_seller = SellerProfile.objects.create(
            user=User.objects.create_user(phone="+22370000011", password="x", display_name="W"),
            business_name="Autre",
        )

    def _existing(self, start, *, hours=1, status=FlashSaleStatus.SCHEDULED, owner=None, **kw):
        return FlashSale.objects.create(
            owner=owner or self.seller,
            title=kw.pop("title", "Vente"),
            start_time=start,
            end_time=start + timedelta(hours=hours),
            status=status,
            **kw,
        )

    def _over_quota(self, seller, plan=Plan.FREE, n=3):
        _set_plan(seller, plan)
        for i in range(n):  # ventes creees ce mois-ci, loin dans le temps (pas de 3/jour)
            self._existing(
                timezone.now() - timedelta(days=10 + i),
                owner=seller,
                status=FlashSaleStatus.COMPLETED,
                title=f"Ancienne {i}",
            )

    def _form_data(self, *, start, end, owner, status, title):
        s, e = timezone.localtime(start), timezone.localtime(end)
        return {
            "title": title,
            "description": "",
            "owner": owner.pk,
            "start_time_0": s.strftime(FMT_D),
            "start_time_1": s.strftime(FMT_T),
            "end_time_0": e.strftime(FMT_D),
            "end_time_1": e.strftime(FMT_T),
            "status": status,
            "delivery_zone": "",
            "max_orders": "",
            # formset des produits lies (inline) : aucun produit
            "flash_sale_products-TOTAL_FORMS": "0",
            "flash_sale_products-INITIAL_FORMS": "0",
            "flash_sale_products-MIN_NUM_FORMS": "0",
            "flash_sale_products-MAX_NUM_FORMS": "1000",
        }

    def add(self, *, start, hours=1, owner=None, status="scheduled", title="Via admin"):
        data = self._form_data(
            start=start,
            end=start + timedelta(hours=hours),
            owner=owner or self.seller,
            status=status,
            title=title,
        )
        return self.client.post(reverse("admin:flash_sales_flashsale_add"), data)

    def change(self, sale, **overrides):
        """POST de modification : valeurs actuelles de la vente, sauf `overrides`
        (cles du formulaire : title, owner, status, start_time_0, end_time_1...)."""
        data = self._form_data(
            start=sale.start_time,
            end=sale.end_time,
            owner=sale.owner,
            status=sale.status,
            title=sale.title,
        )
        data.update(overrides)
        return self.client.post(
            reverse("admin:flash_sales_flashsale_change", args=[sale.pk]), data
        )

    def assertRefused(self, response, text):
        self.assertEqual(
            response.status_code, 200, "le formulaire aurait du etre reaffiche avec une erreur"
        )
        self.assertIn(text, response.content.decode())

    def assertSaved(self, response):
        self.assertEqual(response.status_code, 302, response.content.decode()[:1500])


class AdminCreationTests(AdminBase):
    def test_staff_creation_over_monthly_quota_is_refused(self):
        self._over_quota(self.seller)
        before = FlashSale.objects.count()
        resp = self.add(start=_future_day(5) + timedelta(hours=10))
        self.assertRefused(resp, "ventes ce mois-ci")
        self.assertEqual(FlashSale.objects.count(), before)

    def test_staff_creation_beyond_three_per_day_is_refused(self):
        _set_plan(self.seller, Plan.PRO)
        day = _future_day(6)
        for h in (8, 10, 12):
            self._existing(day + timedelta(hours=h))
        before = FlashSale.objects.count()
        resp = self.add(start=day + timedelta(hours=15))
        self.assertRefused(resp, "Maximum 3 ventes flash par jour")
        self.assertEqual(FlashSale.objects.count(), before)

    def test_staff_creation_longer_than_two_hours_is_refused(self):
        _set_plan(self.seller, Plan.PRO)
        resp = self.add(start=_future_day(7) + timedelta(hours=9), hours=3)
        self.assertRefused(resp, "2 heures au maximum")
        self.assertFalse(FlashSale.objects.exists())

    def test_compliant_staff_creation_still_works(self):
        _set_plan(self.seller, Plan.FREE)
        resp = self.add(start=_future_day(8) + timedelta(hours=9), title="Conforme")
        self.assertSaved(resp)
        self.assertTrue(FlashSale.objects.filter(title="Conforme").exists())


class AdminChangeTests(AdminBase):
    def test_typo_fix_stays_possible_when_seller_is_over_quota(self):
        self._over_quota(self.seller, n=4)  # 4 > 3 : deja hors quota
        sale = FlashSale.objects.filter(title="Ancienne 0").get()
        self.assertSaved(self.change(sale, title="Ancienne 0 corrigee"))
        sale.refresh_from_db()
        self.assertEqual(sale.title, "Ancienne 0 corrigee")

    def test_typo_fix_stays_possible_on_a_full_day(self):
        _set_plan(self.seller, Plan.PRO)
        day = _future_day(9)
        sales = [self._existing(day + timedelta(hours=h), title=f"J{h}") for h in (8, 10, 12, 14)]
        self.assertSaved(self.change(sales[0], title="J8 corrigee"))

    def test_moving_a_sale_to_a_full_day_is_refused(self):
        _set_plan(self.seller, Plan.PRO)
        day = timezone.localtime(_future_day(10))
        for h in (8, 10, 12):
            self._existing(day + timedelta(hours=h))
        mover = self._existing(day + timedelta(days=1, hours=8), title="Mover")
        resp = self.change(
            mover,
            start_time_0=day.strftime(FMT_D),
            start_time_1="15:00:00",
            end_time_0=day.strftime(FMT_D),
            end_time_1="16:00:00",
        )
        self.assertRefused(resp, "Maximum 3 ventes flash par jour")
        before = mover.start_time
        mover.refresh_from_db()
        self.assertEqual(mover.start_time, before)

    def test_rescheduling_within_rules_is_allowed_when_seller_is_over_quota(self):
        """La vente est deja comptee dans le quota : la deplacer ne le consomme pas."""
        self._over_quota(self.seller, n=3)
        sale = self._existing(_future_day(14) + timedelta(hours=9))  # 4e du mois
        day = timezone.localtime(_future_day(15))
        resp = self.change(
            sale,
            start_time_0=day.strftime(FMT_D),
            start_time_1="10:00:00",
            end_time_0=day.strftime(FMT_D),
            end_time_1="11:00:00",
        )
        self.assertSaved(resp)

    def test_stretching_a_sale_beyond_two_hours_is_refused(self):
        _set_plan(self.seller, Plan.PRO)
        sale = self._existing(_future_day(11) + timedelta(hours=9))
        end = timezone.localtime(sale.start_time + timedelta(hours=3))
        resp = self.change(
            sale, end_time_0=end.strftime(FMT_D), end_time_1=end.strftime(FMT_T)
        )
        self.assertRefused(resp, "2 heures au maximum")

    def test_reassigning_to_a_seller_over_quota_is_refused(self):
        self._over_quota(self.other_seller)
        sale = self._existing(_future_day(12) + timedelta(hours=9))
        resp = self.change(sale, owner=self.other_seller.pk)
        self.assertRefused(resp, "ventes ce mois-ci")
        sale.refresh_from_db()
        self.assertEqual(sale.owner_id, self.seller.pk)

    def test_forcing_live_status_applies_the_opening_rules(self):
        self._over_quota(self.seller)
        sale = self._existing(timezone.now() - timedelta(minutes=1))  # 4e vente du mois
        resp = self.change(sale, status="live")
        self.assertRefused(resp, "ventes ce mois-ci")
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.SCHEDULED)

    def test_other_status_changes_are_not_blocked(self):
        self._over_quota(self.seller)
        sale = self._existing(_future_day(13) + timedelta(hours=9))
        self.assertSaved(self.change(sale, status="cancelled"))
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.CANCELLED)
