"""core/countries.py : source unique des pays et de la validation des numeros internationaux."""

from __future__ import annotations

from django.test import SimpleTestCase

from core.countries import COUNTRIES, DEFAULT_COUNTRY, country_for_digits, validate_international


class CountriesTests(SimpleTestCase):
    def test_initial_list(self) -> None:
        codes = {c.name: c.calling_code for c in COUNTRIES}
        self.assertEqual(
            codes,
            {
                "Mali": "223",
                "Sénégal": "221",
                "Côte d'Ivoire": "225",
                "Burkina Faso": "226",
                "Niger": "227",
                "Guinée": "224",
                "Togo": "228",
                "Bénin": "229",
                "Mauritanie": "222",
            },
        )
        self.assertEqual(DEFAULT_COUNTRY.calling_code, "223")
        self.assertEqual(len({c.calling_code for c in COUNTRIES}), len(COUNTRIES))

    def test_country_lookup(self) -> None:
        self.assertEqual(country_for_digits("22370000001").name, "Mali")
        self.assertEqual(country_for_digits("221771234567").name, "Sénégal")
        self.assertIsNone(country_for_digits("33612345678"))

    def test_valid_numbers_are_returned_in_full_international_form(self) -> None:
        cases = {
            "+223 70 00 00 01": "+22370000001",
            "00223 70 00 00 01": "+22370000001",
            "+221 77 123 45 67": "+221771234567",
            "+(225) 07-01-02-03-04": "+2250701020304",
        }
        for raw, expected in cases.items():
            self.assertEqual(validate_international(raw), (expected, ""), raw)

    def test_number_without_country_code_is_refused(self) -> None:
        e164, error = validate_international("70 00 00 01")
        self.assertIsNone(e164)
        self.assertIn("indicatif", error)

    def test_unknown_country_is_refused(self) -> None:
        e164, error = validate_international("+33 6 12 34 56 78")
        self.assertIsNone(e164)
        self.assertIn("non pris en charge", error)

    def test_length_is_checked_per_country(self) -> None:
        for raw in ("+223 7000", "+223 70 00 00 01 99", "+225 70 00 00 01", "+221 77 123 45"):
            e164, error = validate_international(raw)
            self.assertIsNone(e164, raw)
            self.assertIn("chiffres", error)

    def test_adding_a_country_is_one_entry(self) -> None:
        from core import countries

        orig = countries.COUNTRIES
        countries.COUNTRIES = orig + (countries.Country("Ghana", "233", 9),)
        try:
            self.assertEqual(validate_international("+233 24 123 4567"), ("+233241234567", ""))
        finally:
            countries.COUNTRIES = orig
