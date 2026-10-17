from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from analytics.services import monthly_report as mr
from analytics.tests_monthly_report import ReportFixture, _seller
from delivery.models import Delivery
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import OrderStatus
from products.models import FlashSaleProduct, Product

User = get_user_model()

FEB = datetime(2025, 2, 10, 12, tzinfo=dt_tz.utc)
MARCH = datetime(2025, 3, 15, 12, tzinfo=dt_tz.utc)


def _bilan(seller, y=2025, m=3):
    return mr.shop_bilan(seller, y, m)


class ThresholdTests(ReportFixture):
    def _row(self, bilan, key):
        return next(r for r in bilan["comparison"]["rows"] if r["key"] == key)

    def test_weak_base_gives_no_percentage(self) -> None:
        for _ in range(2):  # 2 réalisées en février : < 3
            self.order(when=FEB, price=20000)
        self.order(when=MARCH, price=20000)
        b = _bilan(self.seller)
        self.assertTrue(b["comparison"]["weak"])
        row = self._row(b, "revenue")
        self.assertEqual(row["variation"]["state"], "weak")
        self.assertIsNone(row["variation"]["pct"])
        self.assertEqual(row["previous"], 40000)  # valeur brute conservée
        self.assertIn("base trop faible pour comparer", b["summary"])
        self.assertNotRegex(b["summary"], r"[+-]\d+ %")

    def test_weak_when_revenue_below_10000(self) -> None:
        for _ in range(3):
            self.order(when=FEB, price=3000)  # 9 000 FCFA
        self.order(when=MARCH)
        self.assertTrue(_bilan(self.seller)["comparison"]["weak"])

    def test_strong_base_gives_percentage_and_arrows(self) -> None:
        for _ in range(4):
            self.order(when=FEB, price=5000)  # 20 000
        for _ in range(5):
            self.order(when=MARCH, price=5000)  # 25 000
        b = _bilan(self.seller)
        self.assertFalse(b["comparison"]["weak"])
        v = self._row(b, "revenue")["variation"]
        self.assertEqual((v["direction"], v["pct"]), ("up", 25))
        self.assertIn("+25 %", b["summary"])
        self.assertEqual(self._row(b, "average_basket")["variation"]["direction"], "equal")

    def test_no_previous_month(self) -> None:
        fresh = _seller("+22370000050", "Neuve", joined=MARCH)
        b = _bilan(fresh)
        self.assertFalse(b["comparison"]["has_previous"])
        self.assertEqual(len(b["trend"]["rows"]), 1)

    def test_rate_variation_in_points(self) -> None:
        for _ in range(4):
            self.order(when=FEB, price=5000)
        for _ in range(4):
            self.order(when=MARCH, price=5000)
        self.order(when=MARCH, status=OrderStatus.CANCELLED, collected=False,
                   delivery_status=Delivery.Status.PENDING)
        v = self._row(_bilan(self.seller), "realization_rate")["variation"]
        self.assertEqual((v["direction"], v["points"], v["pct"]), ("down", -20, None))


class TrendTests(TestCase):
    def test_window_across_year_start_and_signup(self) -> None:
        s = _seller("+22370000060", "Vieille", joined=datetime(2024, 11, 5, 12, tzinfo=dt_tz.utc))
        rows = _bilan(s, 2025, 1)["trend"]["rows"]
        self.assertEqual([r["short"] for r in rows], ["Novembre", "Décembre", "Janvier"])
        # Inscrite en décembre : pas de novembre.
        d = _seller("+22370000061", "Dec", joined=datetime(2024, 12, 5, 12, tzinfo=dt_tz.utc))
        self.assertEqual(
            [r["short"] for r in _bilan(d, 2025, 1)["trend"]["rows"]],
            ["Décembre", "Janvier"],
        )
        # Inscrite le mois dernier, fiche du mois courant : 2 mois.
        cur = mr.current_month()
        prev = mr.previous_month(*cur)
        last = _seller("+22370000062", "Last", joined=datetime(prev[0], prev[1], 5, 12, tzinfo=dt_tz.utc))
        self.assertEqual(len(_bilan(last, *cur)["trend"]["rows"]), 2)
        self.assertEqual(len(_bilan(last, *cur)["trend"]["bars"]), 2)


class MoversTests(ReportFixture):
    def test_top_gains_and_drops_absolute(self) -> None:
        jan = datetime(2025, 1, 20, 12, tzinfo=dt_tz.utc)
        self.order(when=jan, name="A", price=10000)
        self.order(when=jan, name="B", price=3000)
        self.order(when=MARCH, name="A", price=4000)
        self.order(when=MARCH, name="B", price=9000)
        self.order(when=MARCH, name="C", price=2000)
        mv = _bilan(self.seller)["trend"]["movers"]
        self.assertEqual([(m["name"], m["delta"]) for m in mv["up"]], [("B", 6000), ("C", 2000)])
        self.assertEqual([(m["name"], m["delta"]) for m in mv["down"]], [("A", -6000)])


class SignalTests(ReportFixture):
    def keys(self, y=2025, m=3):
        return {s["key"] for s in _bilan(self.seller, y, m)["signals"]}

    def test_dependence(self) -> None:
        self.order(when=MARCH, name="A", price=3000)
        self.order(when=MARCH, name="B", price=3500)
        self.order(when=MARCH, name="C", price=3500)
        self.assertNotIn("dependence", self.keys())  # A = 30 %
        self.order(when=MARCH, name="A", price=5000)  # A = 8 000 / 15 000 = 53 %
        self.assertIn("dependence", self.keys())

    def test_delivery_rate(self) -> None:
        for _ in range(2):
            self.order(when=MARCH)
        for _ in range(3):
            self.order(when=MARCH, status=OrderStatus.CANCELLED, collected=False,
                       delivery_status=Delivery.Status.PENDING)
        self.assertIn("delivery", self.keys())  # 2/5 = 40 %
        self.order(when=MARCH)
        self.order(when=MARCH)
        self.order(when=MARCH)  # 5/8 = 62 %
        self.assertNotIn("delivery", self.keys())

    def test_delivery_needs_five_orders(self) -> None:
        self.order(when=MARCH, status=OrderStatus.CANCELLED, collected=False,
                   delivery_status=Delivery.Status.PENDING)
        self.assertNotIn("delivery", self.keys())

    def test_stale_includes_delivered_unpaid(self) -> None:
        for _ in range(4):
            self.order(when=MARCH)
        self.assertNotIn("stale", self.keys())
        self.order(when=MARCH, collected=False)  # livrée non encaissée : 1/5 = 20 %, pas > 20
        self.assertNotIn("stale", self.keys())
        self.order(when=MARCH, collected=False)  # 2/6 = 33 %
        b = _bilan(self.seller)
        self.assertIn("stale", {s["key"] for s in b["signals"]})
        self.assertTrue(b["report"]["pending_alert"])
        self.assertEqual(b["report"]["orders_delivered_unpaid"], 2)  # ligne dédiée conservée

    def test_inactivity(self) -> None:
        self.assertIn("inactive", self.keys(2025, 6))
        self.assertNotIn("inactive", self.keys(2025, 3))

    def test_loyal_customers(self) -> None:
        for i in range(5):
            self.order(when=MARCH, phone=f"+2237200000{i}")
        self.assertNotIn("loyal", {s["key"] for s in _bilan(self.seller, 2025, 2)["signals"]})
        self.assertIn("loyal", self.keys())
        for i in range(2):
            self.order(when=FEB, phone=f"+2237200000{i}")
        text = next(s["text"] for s in _bilan(self.seller)["signals"] if s["key"] == "loyal")
        self.assertIn("40 %", text)  # 2 sur 5

    def test_loyal_needs_five_customers(self) -> None:
        for i in range(4):
            self.order(when=MARCH, phone=f"+2237300000{i}")
        self.assertNotIn("loyal", self.keys())

    def _sale(self, hour: int, day: int) -> FlashSale:
        return FlashSale.objects.create(
            title=f"v{day}", owner=self.seller, status=FlashSaleStatus.COMPLETED,
            start_time=datetime(2025, 3, day, hour, tzinfo=dt_tz.utc),
            end_time=datetime(2025, 3, day, hour + 1, tzinfo=dt_tz.utc),
        )

    def _revenue(self, sale, amount):
        self.sale = sale
        self.order(when=MARCH, price=amount)

    def test_best_slot(self) -> None:
        FlashSale.objects.filter(pk=self.sale.pk).update(status=FlashSaleStatus.CANCELLED)
        # Un seul créneau à 2 ventes : pas de signal.
        for d in (1, 2):
            self._revenue(self._sale(9, d), 1000)
        self.assertNotIn("slot", self.keys())
        # Deuxième créneau à 2 ventes : le soir rapporte plus par vente.
        for d in (3, 4):
            self._revenue(self._sale(19, d), 5000)
        b = _bilan(self.seller)
        slot = next(s for s in b["signals"] if s["key"] == "slot")
        self.assertIn("soir", slot["text"])
        self.assertIn("5 000 FCFA", slot["text"])

    def test_best_slot_needs_two_sales_per_slot(self) -> None:
        FlashSale.objects.filter(pk=self.sale.pk).update(status=FlashSaleStatus.CANCELLED)
        for d in (1, 2):
            self._revenue(self._sale(9, d), 1000)
        self._revenue(self._sale(19, 3), 5000)  # 1 seule vente le soir
        self.assertNotIn("slot", self.keys())

    def test_sleeping_stock(self) -> None:
        sold = self.product
        dormant = Product.objects.create(
            owner=self.seller, name="Dormant", stock_available=15,
            stock_initial=15, price=Decimal(1000),
        )
        second = FlashSale.objects.create(
            title="v2", owner=self.seller, status=FlashSaleStatus.COMPLETED,
            start_time=datetime(2025, 3, 20, 10, tzinfo=dt_tz.utc),
            end_time=datetime(2025, 3, 20, 12, tzinfo=dt_tz.utc),
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=dormant)
        # Présent dans 1 seule vente : pas de signal.
        self.assertNotIn("sleeping", self.keys())
        FlashSaleProduct.objects.create(flash_sale=second, product=dormant)
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=sold)
        FlashSaleProduct.objects.create(flash_sale=second, product=sold)
        self.order(when=MARCH)  # `sold` est vendu
        b = _bilan(self.seller)
        self.assertEqual([p["name"] for p in b["sleeping"]], ["Dormant"])
        self.assertIn("Dormant (stock 15)", b["summary"])
        # Une fois vendu, le signal disparaît.
        self.order(when=MARCH)
        Product.objects.filter(pk=dormant.pk).update(stock_available=0)
        self.assertNotIn("sleeping", self.keys())

    def test_sleeping_ignores_inactive_product(self) -> None:
        p = Product.objects.create(
            owner=self.seller, name="Off", stock_available=5, stock_initial=5,
            price=Decimal(1000), is_active=False,
        )
        s2 = FlashSale.objects.create(
            title="v2", owner=self.seller, status=FlashSaleStatus.COMPLETED,
            start_time=datetime(2025, 3, 20, 10, tzinfo=dt_tz.utc),
            end_time=datetime(2025, 3, 20, 12, tzinfo=dt_tz.utc),
        )
        for s in (self.sale, s2):
            FlashSaleProduct.objects.create(flash_sale=s, product=p)
        self.assertNotIn("sleeping", self.keys())


class SummaryTests(ReportFixture):
    def test_no_phone_and_matches_page(self) -> None:
        for i in range(5):
            self.order(when=MARCH, name="Produit A", price=14900, phone=f"+2237800000{i}")
        self.order(when=FEB, name="Produit A", price=5000, phone="+22378000000")
        s = self.seller
        staff = User.objects.create_user(
            phone="+22370009000", password="x", display_name="Admin", is_staff=True
        )
        c = Client()
        c.force_login(staff)
        url = reverse("platform_admin_shop_report", args=[s.pk]) + "?mois=2025-03"
        html = c.get(url).content.decode()
        b = _bilan(s)
        summary = b["summary"]
        # Aucun numéro (ni vendeuse ni acheteurs), aucun nom d'acheteur.
        for phone in ("+22370000001", "22370000001", "7800000", s.user.phone):
            self.assertNotIn(phone, summary)
        self.assertNotRegex(summary, r"\+\d{6,}")
        self.assertNotRegex(summary, r"(?<!\d)\d{8,}(?!\d)")
        self.assertNotIn("Awa Shop", summary)  # nom du compte, seul le nom de boutique sort
        # Mêmes chiffres que la page.
        r = b["report"]
        self.assertIn(f"{r['revenue']:,}".replace(",", " ") + " FCFA", summary)
        self.assertIn(f"{r['orders_placed']} passées, {r['orders_realized']} réalisées", summary)
        self.assertIn("Produit A 100,0 %", summary)
        self.assertIn("BILAN HAYAFLASH — Boutique : Awa Boutique — Mars 2025", summary)
        self.assertIn("Février 5 000 | Mars 74 500", summary.replace("Février", "Février"))
        self.assertIn("74", html)
        self.assertIn(summary.splitlines()[0], html)
        self.assertEqual(r["revenue"], 74500)
        self.assertIn("data-hf-copy-from", html)


class QueryCountTests(ReportFixture):
    def test_report_page_query_count_bounded(self) -> None:
        for i in range(6):
            self.order(when=MARCH, name=f"P{i}", price=3000, phone=f"+2237900000{i}")
            self.order(when=FEB, name=f"P{i}", price=3000, phone=f"+2237900000{i}")
        staff = User.objects.create_user(
            phone="+22370009001", password="x", display_name="Admin", is_staff=True
        )
        c = Client()
        c.force_login(staff)
        url = reverse("platform_admin_shop_report", args=[self.seller.pk]) + "?mois=2025-03"
        c.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(c.get(url).status_code, 200)
        few = len(ctx)
        for i in range(30):
            self.order(when=MARCH, name=f"Q{i}", price=3000, phone=f"+2237910{i:04d}")
        with CaptureQueriesContext(connection) as ctx2:
            c.get(url)
        self.assertEqual(few, len(ctx2))
        self.assertLessEqual(few, 40)
