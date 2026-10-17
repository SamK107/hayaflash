from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from analytics.services import monthly_report as mr
from delivery.models import Delivery
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderItem, OrderStatus
from products.models import Product

User = get_user_model()


def _seller(phone: str, name: str, *, joined: datetime | None = None) -> SellerProfile:
    user = User.objects.create_user(phone=phone, password="x", display_name=name)
    seller = SellerProfile.objects.create(user=user, business_name=name)
    if joined:
        SellerProfile.objects.filter(pk=seller.pk).update(created_at=joined)
        seller.refresh_from_db()
    return seller


class ReportFixture(TestCase):
    def setUp(self) -> None:
        self.joined = datetime(2025, 1, 10, 12, tzinfo=dt_tz.utc)
        self.seller = _seller("+22370000001", "Awa Boutique", joined=self.joined)
        self.product = Product.objects.create(
            owner=self.seller, name="Sac", stock_available=99,
            stock_initial=99, price=Decimal(1000),
        )
        self.sale = FlashSale.objects.create(
            title="Vente", owner=self.seller, status=FlashSaleStatus.COMPLETED,
            start_time=datetime(2025, 3, 5, 10, tzinfo=dt_tz.utc),
            end_time=datetime(2025, 3, 5, 12, tzinfo=dt_tz.utc),
        )
        self._n = 0

    def order(self, *, when, status=OrderStatus.DELIVERED, collected=True,
              delivery_status=None, price=1000, qty=1, name="Sac",
              phone="+22371000001", with_delivery=True) -> Order:
        self._n += 1
        o = Order.service_objects.create(
            flash_sale=self.sale, status=status, customer_phone=phone,
            client_request_id=f"r{self._n}",
        )
        Order.service_objects.filter(pk=o.pk).update(created_at=when)
        OrderItem.objects.create(
            order=o, product=self.product, product_name_snapshot=name,
            price_snapshot=Decimal(price), quantity=qty,
        )
        if with_delivery:
            Delivery.objects.create(
                order=o, address_text="x", cod_amount=Decimal(price * qty),
                cod_collected=collected,
                status=delivery_status or Delivery.Status.DELIVERED,
            )
        return o


MARCH = datetime(2025, 3, 15, 12, tzinfo=dt_tz.utc)


class AccessTests(ReportFixture):
    def test_access_control(self) -> None:
        urls = [
            reverse("platform_admin_shops"),
            reverse("platform_admin_shop_report", args=[self.seller.pk]),
        ]
        staff = User.objects.create_user(
            phone="+22370009999", password="x", display_name="Admin", is_staff=True
        )
        for url in urls:
            anon = Client().get(url)
            self.assertEqual(anon.status_code, 302)
            self.assertIn("login", anon.url)
            seller_client = Client()
            seller_client.force_login(self.seller.user)
            self.assertIn(seller_client.get(url).status_code, (302, 403))
            self.assertNotEqual(seller_client.get(url).status_code, 200)
            admin = Client()
            admin.force_login(staff)
            self.assertEqual(admin.get(url + "?mois=2025-03").status_code, 200)


class DefinitionTests(ReportFixture):
    def test_only_delivered_and_collected_counts_in_revenue(self) -> None:
        self.order(when=MARCH, price=1000, qty=2)  # réalisée
        self.order(when=MARCH, collected=False)  # livrée non payée
        self.order(when=MARCH, status=OrderStatus.CANCELLED, collected=False,
                   delivery_status=Delivery.Status.PENDING)
        self.order(when=MARCH, status=OrderStatus.OUT_FOR_DELIVERY, collected=False,
                   delivery_status=Delivery.Status.FAILED)
        self.order(when=MARCH, status=OrderStatus.PENDING, collected=False,
                   delivery_status=Delivery.Status.PENDING)
        self.order(when=MARCH, status=OrderStatus.DELIVERED, with_delivery=False)
        r = mr.shop_month_report(self.seller, 2025, 3)
        self.assertEqual(r["revenue"], 2000)
        self.assertEqual(r["items_sold"], 2)
        self.assertEqual(r["orders_placed"], 6)
        self.assertEqual(r["orders_realized"], 1)
        self.assertEqual(r["orders_cancelled"], 1)
        self.assertEqual(r["orders_failed"], 1)
        self.assertEqual(r["orders_delivered_unpaid"], 2)
        self.assertEqual(r["orders_pending_update"], 1)
        self.assertEqual(r["average_basket"], 2000)
        self.assertEqual(r["sales_count"], 1)

    def test_pending_alert_above_20_percent(self) -> None:
        for _ in range(3):
            self.order(when=MARCH)
        self.order(when=MARCH, status=OrderStatus.PENDING, collected=False,
                   delivery_status=Delivery.Status.PENDING)
        r = mr.shop_month_report(self.seller, 2025, 3)
        self.assertTrue(r["pending_alert"])  # 1/4 = 25 %
        self.assertEqual(r["realization_rate"], 75)

    def test_month_is_local_time(self) -> None:
        # 23 h 30 UTC le 31/03 = 00 h 30 le 1er avril à Lagos (UTC+1).
        late = datetime(2025, 3, 31, 23, 30, tzinfo=dt_tz.utc)
        self.order(when=late)
        with timezone.override("Africa/Lagos"):
            self.assertEqual(mr.shop_month_report(self.seller, 2025, 3)["orders_placed"], 0)
            self.assertEqual(mr.shop_month_report(self.seller, 2025, 4)["orders_placed"], 1)
        with timezone.override("UTC"):
            self.assertEqual(mr.shop_month_report(self.seller, 2025, 3)["orders_placed"], 1)

    def test_customers_and_returning(self) -> None:
        feb = datetime(2025, 2, 10, 12, tzinfo=dt_tz.utc)
        self.order(when=feb, phone="+22371000001")
        self.order(when=MARCH, phone="+22371000001")
        self.order(when=MARCH, phone="+22371000002")
        self.order(when=MARCH, phone="+22371000002")
        r = mr.shop_month_report(self.seller, 2025, 3)
        self.assertEqual(r["customers"], 2)
        self.assertEqual(r["customers_returning"], 1)

    def test_empty_month(self) -> None:
        r = mr.shop_month_report(self.seller, 2025, 6)
        self.assertTrue(r["is_empty"])
        self.assertEqual(r["revenue"], 0)


class ProductTests(ReportFixture):
    def test_shares_cumulative_and_total_matches_revenue(self) -> None:
        self.order(when=MARCH, name="A", price=3000, qty=1)
        self.order(when=MARCH, name="B", price=500, qty=2)
        self.order(when=MARCH, name="C", price=1000, qty=1)
        self.order(when=MARCH, name="A", price=3000, qty=1)
        r = mr.shop_month_report(self.seller, 2025, 3)
        self.assertEqual(r["revenue"], 8000)
        names = [p["name"] for p in r["products"]]
        self.assertEqual(names, ["A", "B", "C"])  # B et C à égalité : ordre alpha
        self.assertEqual(sum(p["revenue"] for p in r["products"]), r["revenue"])
        self.assertEqual([p["share"] for p in r["products"]], [75.0, 12.5, 12.5])
        self.assertEqual([p["cumulative"] for p in r["products"]], [75.0, 87.5, 100.0])
        self.assertEqual(r["products"][0]["quantity"], 2)


class MonthTests(TestCase):
    def test_default_is_last_complete_month(self) -> None:
        self.assertEqual(mr.default_month(date(2026, 1, 20)), (2025, 12))
        self.assertEqual(mr.default_month(date(2026, 10, 17)), (2026, 9))

    def test_parse_month(self) -> None:
        self.assertEqual(mr.parse_month("2025-03"), (2025, 3))
        for bad in ("", None, "2025-13", "abc", "2025-3-1"):
            self.assertIsNone(mr.parse_month(bad))

    def test_choices_start_at_registration_and_mark_current(self) -> None:
        reg = datetime(2026, 8, 5, 12, tzinfo=dt_tz.utc)
        ch = mr.month_choices(reg, date(2026, 10, 17))
        self.assertEqual([c["value"] for c in ch], ["2026-10", "2026-09", "2026-08"])
        self.assertIn("(en cours)", ch[0]["label"])

    def test_report_view_defaults_and_clamps(self) -> None:
        seller = _seller("+22370000002", "Neuve")
        staff = User.objects.create_user(
            phone="+22370009998", password="x", display_name="Admin", is_staff=True
        )
        c = Client()
        c.force_login(staff)
        url = reverse("platform_admin_shop_report", args=[seller.pk])
        # Inscrite ce mois-ci : le défaut est ramené au mois d'inscription.
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        cur = mr.current_month()
        self.assertEqual(resp.context["selected"], f"{cur[0]}-{cur[1]:02d}")
        # Mois hors bornes -> repli, jamais d'erreur.
        self.assertEqual(c.get(url + "?mois=1999-01").status_code, 200)
        self.assertEqual(c.get(url + "?mois=zzz").status_code, 200)


class ShopListTests(ReportFixture):
    def test_list_order_search_and_activity(self) -> None:
        other = _seller("+22370000003", "Binta Mode", joined=self.joined + timedelta(days=5))
        FlashSale.objects.create(
            title="Récente", owner=other, status=FlashSaleStatus.COMPLETED,
            start_time=timezone.now() - timedelta(days=3),
            end_time=timezone.now() - timedelta(days=3) + timedelta(hours=1),
        )
        rows = mr.list_shops()
        self.assertEqual([r["name"] for r in rows], ["Awa Boutique", "Binta Mode"])
        self.assertEqual([r["rank"] for r in rows], [1, 2])
        self.assertFalse(rows[0]["is_active"])
        self.assertTrue(rows[1]["is_active"])
        self.assertEqual(rows[0]["last_sale"].date(), date(2025, 3, 5))
        self.assertEqual(rows[1]["wa_url"], "https://wa.me/22370000003")
        self.assertEqual(mr.list_shops(newest_first=True)[0]["name"], "Binta Mode")
        self.assertEqual([r["name"] for r in mr.list_shops(search="binta")], ["Binta Mode"])
        self.assertEqual([r["name"] for r in mr.list_shops(search="0000001")], ["Awa Boutique"])
        # Le rang reste celui de l'inscription, même filtré.
        self.assertEqual(mr.list_shops(search="binta")[0]["rank"], 2)

    def test_query_count_independent_of_shop_count(self) -> None:
        staff = User.objects.create_user(
            phone="+22370009997", password="x", display_name="Admin", is_staff=True
        )
        c = Client()
        c.force_login(staff)
        url = reverse("platform_admin_shops")
        c.get(url)  # chauffe les caches éventuels
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as few:
            c.get(url)
        for i in range(8):
            _seller(f"+2237100{i:04d}", f"Boutique {i}")
        with CaptureQueriesContext(connection) as many:
            c.get(url)
        self.assertEqual(len(few), len(many))
