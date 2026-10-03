"""F-81 bloc 2 : prochaine vente + inscrits a prevenir (dedoublonnes, tous statuts)."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from accounts.models import SellerProfile
from flash_sales.models import FlashSaleStatus, SaleInterest
from flash_sales.services.notify_interests import (
    interests_to_notify,
    next_scheduled_sale,
    normalize_whatsapp_number,
)
from flash_sales.tests_alertes import AlertFixture

User = get_user_model()


class NormalizeWhatsappNumberTests(AlertFixture):
    def test_formats(self) -> None:
        cases = {
            "+223 70 00 00 01": "22370000001",
            "+22370000001": "22370000001",
            "0022370000001": "22370000001",
            "(+223) 70-00-00-01": "22370000001",
            "+33 6 12 34 56 78": "33612345678",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_whatsapp_number(raw), expected, raw)

    def test_invalid(self) -> None:
        # Jamais de pays devine : un numero nu (meme a 8 chiffres) n'a pas de lien.
        for raw in ("", "abc", "123", "+22", "7000", "70 00 00 01", "70000001",
                    "0612345678", "12345678901234567", "+223 70 00 00 0x"):
            self.assertIsNone(normalize_whatsapp_number(raw), raw)


class NextScheduledSaleTests(AlertFixture):
    def test_returns_earliest_scheduled_future_sale(self) -> None:
        self.make_sale(title="Plus tard", start_in_h=48)
        soon = self.make_sale(title="Bientôt", start_in_h=5)
        self.make_sale(title="Terminée", status=FlashSaleStatus.CLOSED, start_in_h=-9)
        self.make_sale(title="En cours", status=FlashSaleStatus.LIVE, start_in_h=-1, duration_h=3)
        self.assertEqual(next_scheduled_sale(self.seller), soon)

    def test_none_when_no_scheduled_sale(self) -> None:
        self.make_sale(status=FlashSaleStatus.CLOSED, start_in_h=-9)
        self.assertIsNone(next_scheduled_sale(self.seller))

    def test_other_sellers_sales_are_ignored(self) -> None:
        other_user = User.objects.create_user(phone="+22370000002", password="x", display_name="B")
        other = SellerProfile.objects.create(user=other_user, business_name="B")
        self.make_sale(title="Chez B", start_in_h=2, owner=other)
        self.assertIsNone(next_scheduled_sale(self.seller))


class InterestsToNotifyTests(AlertFixture):
    def _interest(self, sale, phone, name=""):
        return SaleInterest.objects.create(flash_sale=sale, phone=phone, name=name)

    def test_dedup_by_normalized_number_keeps_latest_name(self) -> None:
        sale = self.make_sale()
        self._interest(sale, "+223 70 00 00 01", "")
        self._interest(sale, "00223 70 00 00 01", "Fatoumata")
        self._interest(sale, "+22370000001", "")
        self._interest(sale, "+22371111111", "Moussa")
        got = interests_to_notify(self.seller)
        self.assertEqual(len(got), 2)
        by = {i.phone_e164: i for i in got}
        self.assertEqual(by["22370000001"].name, "Fatoumata")
        self.assertEqual(by["22371111111"].name, "Moussa")

    def test_includes_interests_of_closed_sales(self) -> None:
        closed = self.make_sale(status=FlashSaleStatus.CLOSED, start_in_h=-9)
        self.make_sale(title="Prochaine", start_in_h=4)
        self._interest(closed, "+22370000001", "Awa")
        self.assertEqual([i.phone_e164 for i in interests_to_notify(self.seller)], ["22370000001"])

    def test_same_number_on_several_sales_counted_once(self) -> None:
        a = self.make_sale(status=FlashSaleStatus.CLOSED, start_in_h=-9)
        b = self.make_sale(start_in_h=4)
        self._interest(a, "+22370000001")
        self._interest(b, "00223 70 00 00 01")
        self.assertEqual(len(interests_to_notify(self.seller)), 1)

    def test_isolation_between_sellers(self) -> None:
        other_user = User.objects.create_user(phone="+22370000002", password="x", display_name="B")
        other = SellerProfile.objects.create(user=other_user, business_name="B")
        other_sale = self.make_sale(title="Chez B", start_in_h=2, owner=other)
        mine = self.make_sale(title="Chez moi", start_in_h=3)
        self._interest(other_sale, "+22379999999", "Client de B")
        self._interest(mine, "+22370000001", "Mon client")
        names = [i.name for i in interests_to_notify(self.seller)]
        self.assertEqual(names, ["Mon client"])
        self.assertEqual([i.name for i in interests_to_notify(other)], ["Client de B"])

    def test_invalid_number_is_kept_without_e164(self) -> None:
        sale = self.make_sale()
        self._interest(sale, "1234567", "Douteux")
        (inv,) = interests_to_notify(self.seller)
        self.assertIsNone(inv.phone_e164)
        self.assertEqual(inv.phone, "1234567")

    def test_empty_when_no_interests(self) -> None:
        self.make_sale()
        self.assertEqual(interests_to_notify(self.seller), [])
