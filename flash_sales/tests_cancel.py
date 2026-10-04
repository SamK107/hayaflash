"""F-91 : l'annulation d'une vente est refusee cote serveur sauf si elle est
programmee (pas encore commandable) ET sans aucune commande.

Un POST direct ne doit pas pouvoir liberer le slot de quota (RM-05) d'une vente
bouclee ou deja commandee.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.tests_rules import RulesBase, _future_day
from orders.models import Order
from subscriptions.services.limits import count_sales_this_month

User = get_user_model()


class CancelSaleServerSideTests(RulesBase):
    def _post_cancel(self, sale):
        return self.client.post(reverse("flash_sales:cancel", args=[sale.pk]))

    def _messages(self, resp):
        return " ".join(str(m) for m in get_messages(resp.wsgi_request))

    def _future_sale(self, **kw):
        return self._sale(start=_future_day(3) + timedelta(hours=10), **kw)

    def _order_on(self, sale):
        return Order.service_objects.create(
            flash_sale=sale, customer_name="Ada", customer_phone="+22370000009"
        )

    def assertRefused(self, sale, expected_text):
        before_quota = count_sales_this_month(self.seller)
        before_status = FlashSale.objects.get(pk=sale.pk).status
        resp = self._post_cancel(sale)
        self.assertEqual(resp.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.status, before_status)
        self.assertEqual(count_sales_this_month(self.seller), before_quota)
        self.assertIn(expected_text, self._messages(resp))

    def test_closed_sale_cannot_be_cancelled(self):
        sale = self._sale(
            start=timezone.now() - timedelta(days=2), status=FlashSaleStatus.CLOSED
        )
        self.assertRefused(sale, "terminée")

    def test_completed_sale_cannot_be_cancelled(self):
        sale = self._sale(
            start=timezone.now() - timedelta(days=2), status=FlashSaleStatus.COMPLETED
        )
        self.assertRefused(sale, "terminée")

    def test_cancelled_sale_cannot_be_cancelled_again(self):
        sale = self._sale(
            start=timezone.now() - timedelta(days=2), status=FlashSaleStatus.CANCELLED
        )
        self.assertRefused(sale, "déjà annulée")

    def test_live_sale_cannot_be_cancelled(self):
        sale = self._sale(
            start=timezone.now() - timedelta(minutes=10), status=FlashSaleStatus.LIVE
        )
        self.assertRefused(sale, "en cours")

    def test_scheduled_sale_with_order_cannot_be_cancelled(self):
        sale = self._future_sale()
        self._order_on(sale)
        self.assertRefused(sale, "commande")

    def test_scheduled_sale_without_order_is_cancelled_and_slot_freed(self):
        sale = self._future_sale()
        before = count_sales_this_month(self.seller)
        resp = self._post_cancel(sale)
        self.assertEqual(resp.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.CANCELLED)
        self.assertEqual(count_sales_this_month(self.seller), before - 1)

    def test_other_seller_gets_404(self):
        sale = self._future_sale()
        other = User.objects.create_user(
            phone="+22370000002", password="x", display_name="Autre"
        )
        SellerProfile.objects.create(user=other)
        self.client.force_login(other)
        resp = self._post_cancel(sale)
        self.assertEqual(resp.status_code, 404)
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.SCHEDULED)
