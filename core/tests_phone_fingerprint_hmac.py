"""E6 / F-98 : l'empreinte d'un numéro est un HMAC-SHA256 (clé secrète), plus un SHA-256 nu.

Un numéro malien tient sur 8 chiffres : un SHA-256 sans clé se retrouve par énumération (10^8 essais). L'empreinte
des journaux (`phone_fingerprint`) et la clé des compteurs (`phone_key`) partagent le même condensat ; les deux passent
au HMAC avec la clé secrète de Django (comme `ip_fingerprint`, qui utilise déjà `SECRET_KEY` avec un préfixe de domaine).
Conséquence connue : les anciennes empreintes des journaux deviennent incomparables aux nouvelles, et les compteurs de
limitation en cache repartent de zéro une fois au déploiement.
"""

from __future__ import annotations

import hashlib
import re

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from core.services import rate_limit
from core.services.rate_limit import ip_fingerprint, phone_fingerprint, phone_key

PHONE = "+22370123456"


def old_digest(phone):
    return hashlib.sha256((phone or "").encode("utf-8")).hexdigest()[:16]


class PhoneFingerprintHmacTests(SimpleTestCase):
    def test_format_is_unchanged(self):
        self.assertRegex(phone_fingerprint(PHONE), r"^tel:[0-9a-f]{16}$")

    def test_it_is_no_longer_the_bare_sha256(self):
        self.assertNotEqual(phone_fingerprint(PHONE), f"tel:{old_digest(PHONE)}")

    def test_a_known_digest_cannot_be_found_by_enumeration_without_the_key(self):
        # Un attaquant qui connaît l'algorithme précédent (SHA-256 tronqué) et énumère les numéros ne retrouve rien.
        target = phone_fingerprint(PHONE)
        candidates = {f"tel:{old_digest(f'+2237012{n:04d}')}" for n in range(0, 10000)}
        self.assertNotIn(target, candidates)

    def test_it_is_deterministic_and_distinguishes_numbers(self):
        self.assertEqual(phone_fingerprint(PHONE), phone_fingerprint(PHONE))
        self.assertNotEqual(phone_fingerprint(PHONE), phone_fingerprint("+22370123457"))

    def test_it_depends_on_the_secret_key(self):
        with override_settings(SECRET_KEY="une-autre-cle-secrete-pour-le-test"):
            other = phone_fingerprint(PHONE)
            other_key = phone_key("register", PHONE)
        self.assertNotEqual(other, phone_fingerprint(PHONE))
        self.assertNotEqual(other_key, phone_key("register", PHONE))

    def test_empty_or_missing_numbers_do_not_raise(self):
        for value in (None, ""):
            self.assertRegex(phone_fingerprint(value), r"^tel:[0-9a-f]{16}$")

    def test_phone_and_ip_fingerprints_are_domain_separated(self):
        self.assertNotEqual(phone_fingerprint("1.2.3.4")[4:], ip_fingerprint("1.2.3.4"))

    def test_the_counter_key_uses_the_same_digest_and_never_the_number(self):
        key = phone_key("register", PHONE)
        self.assertEqual(key, f"register:phone:{phone_fingerprint(PHONE)[4:]}")
        self.assertNotIn("7012", key)
        self.assertRegex(key, r"^register:phone:[0-9a-f]{16}$")

    def test_a_missing_key_is_a_clear_error_never_a_silent_weak_digest(self):
        # Django refuse déjà une SECRET_KEY vide ; en staging/production le démarrage échoue plus tôt encore
        # (« Missing required env var: SECRET_KEY »). Ici : jamais de condensat calculé avec une clé vide.
        with override_settings(SECRET_KEY=""):
            with self.assertRaises(ImproperlyConfigured):
                phone_fingerprint(PHONE)

    def test_the_digest_helper_does_not_use_a_bare_hash(self):
        import inspect

        source = inspect.getsource(rate_limit._phone_digest)
        self.assertIn("hmac", source)
        self.assertIn("SECRET_KEY", source)
        self.assertNotRegex(source, re.compile(r"hashlib\.sha256\(\(phone"))
