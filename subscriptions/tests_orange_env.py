"""Variables d'environnement Orange Money : ORANGE_ML_* et ORANGE_MONEY_* sont toutes deux acceptees.

.env.example documente ORANGE_ML_* ; le code (et ses messages d'erreur) parlait de ORANGE_MONEY_*.
Règle : ORANGE_ML_* l'emporte si les deux existent ; sinon on prend ORANGE_MONEY_* ; sinon le défaut.
Les valeurs sont lues pour : identifiants OAuth, clé marchand, URL de base, URLs de retour,
timeout et devise. Aucun secret dans les journaux ni dans les messages d'erreur.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from config.settings._orange import orange_settings
from subscriptions.services import orange_money as om

POST = "subscriptions.services.orange_money.requests.post"
SUFFIXES = (
    "CLIENT_ID", "CLIENT_SECRET", "MERCHANT_KEY", "BASE_URL", "RETURN_URL", "CANCEL_URL", "NOTIFY_URL",
    "TIMEOUT", "CURRENCY",
)

ML = {
    "ORANGE_ML_CLIENT_ID": "ml-id",
    "ORANGE_ML_CLIENT_SECRET": "ml-secret",
    "ORANGE_ML_MERCHANT_KEY": "ml-merchant",
    "ORANGE_ML_BASE_URL": "https://ml.example/",
    "ORANGE_ML_TIMEOUT": "33",
    "ORANGE_ML_CURRENCY": "XAF",
}
MONEY = {k.replace("ORANGE_ML_", "ORANGE_MONEY_"): v.replace("ml", "money") for k, v in ML.items()}


def resp(status=200, body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    r.text = text
    return r


def initiate():
    return om.initiate_payment(
        amount=2000, order_id="HF-M-12345678", notif_token="n" * 64,
        return_url="https://x/r", cancel_url="https://x/c", notif_url="https://x/n",
    )


class ResolutionTests(SimpleTestCase):
    def test_only_ml_variables(self):
        s = orange_settings(ML)
        self.assertEqual(
            (s["ORANGE_MONEY_CLIENT_ID"], s["ORANGE_MONEY_CLIENT_SECRET"], s["ORANGE_MONEY_MERCHANT_KEY"]),
            ("ml-id", "ml-secret", "ml-merchant"),
        )
        self.assertEqual(s["ORANGE_MONEY_BASE_URL"], "https://ml.example")
        self.assertEqual((s["ORANGE_MONEY_TIMEOUT"], s["ORANGE_MONEY_CURRENCY"]), (33, "XAF"))

    def test_only_money_variables(self):
        s = orange_settings(MONEY)
        self.assertEqual(
            (s["ORANGE_MONEY_CLIENT_ID"], s["ORANGE_MONEY_CLIENT_SECRET"], s["ORANGE_MONEY_MERCHANT_KEY"]),
            ("money-id", "money-secret", "money-merchant"),
        )
        self.assertEqual(s["ORANGE_MONEY_BASE_URL"], "https://money.example")
        self.assertEqual((s["ORANGE_MONEY_TIMEOUT"], s["ORANGE_MONEY_CURRENCY"]), (33, "XAF"))

    def test_ml_wins_when_both_exist(self):
        s = orange_settings({**MONEY, **ML})
        self.assertEqual(s["ORANGE_MONEY_MERCHANT_KEY"], "ml-merchant")
        self.assertEqual(s["ORANGE_MONEY_CLIENT_ID"], "ml-id")

    def test_empty_ml_falls_back_to_money(self):
        s = orange_settings({"ORANGE_ML_MERCHANT_KEY": "  ", "ORANGE_MONEY_MERCHANT_KEY": " mk "})
        self.assertEqual(s["ORANGE_MONEY_MERCHANT_KEY"], "mk")

    def test_defaults_when_nothing_is_defined(self):
        s = orange_settings({})
        for key in ("CLIENT_ID", "CLIENT_SECRET", "MERCHANT_KEY", "BASE_URL", "RETURN_URL", "CANCEL_URL", "NOTIFY_URL"):
            self.assertEqual(s[f"ORANGE_MONEY_{key}"], "")
        self.assertEqual((s["ORANGE_MONEY_TIMEOUT"], s["ORANGE_MONEY_CURRENCY"]), (20, "XOF"))

    def test_invalid_timeout_falls_back_to_the_default(self):
        for bad in ("abc", "0", "-5", "999"):
            with self.subTest(bad=bad):
                self.assertEqual(orange_settings({"ORANGE_ML_TIMEOUT": bad})["ORANGE_MONEY_TIMEOUT"], 20)


class InitiationReadsTheResolvedValuesTests(SimpleTestCase):
    def check(self, environ, merchant, client_id, secret, timeout, currency):
        with override_settings(**orange_settings(environ)), patch(POST) as post:
            post.side_effect = [resp(200, {"access_token": "TOK"}), resp(201, {"payment_url": "https://pay"})]
            result = initiate()
        token_call, pay_call = post.call_args_list
        self.assertEqual(result["payment_url"], "https://pay")
        self.assertEqual(token_call.kwargs["auth"], (client_id, secret))
        self.assertEqual(pay_call.kwargs["json"]["merchant_key"], merchant)
        self.assertEqual(pay_call.kwargs["json"]["currency"], currency)
        self.assertEqual((token_call.kwargs["timeout"], pay_call.kwargs["timeout"]), (timeout, timeout))
        self.assertIs(pay_call.kwargs["verify"], True)

    def test_only_ml(self):
        self.check(ML, "ml-merchant", "ml-id", "ml-secret", 33, "XAF")

    def test_only_money(self):
        self.check(MONEY, "money-merchant", "money-id", "money-secret", 33, "XAF")

    def test_both_ml_wins(self):
        self.check({**MONEY, **ML}, "ml-merchant", "ml-id", "ml-secret", 33, "XAF")

    def test_defaults_for_timeout_and_currency(self):
        keys_only = {k: v for k, v in ML.items() if k.endswith(("_ID", "_SECRET", "_KEY"))}
        self.check(keys_only, "ml-merchant", "ml-id", "ml-secret", 20, "XOF")


class MissingConfigurationTests(SimpleTestCase):
    def test_missing_merchant_key_names_both_variants(self):
        with override_settings(**orange_settings({})):
            with self.assertRaises(om.OrangeMoneyError) as cm:
                initiate()
        message = str(cm.exception)
        self.assertIn("ORANGE_ML_MERCHANT_KEY", message)
        self.assertIn("ORANGE_MONEY_MERCHANT_KEY", message)

    def test_missing_client_credentials_name_both_variants(self):
        with override_settings(**orange_settings({})):
            with self.assertRaises(om.OrangeMoneyError) as cm:
                om._get_access_token()
        message = str(cm.exception)
        for name in (
            "ORANGE_ML_CLIENT_ID", "ORANGE_MONEY_CLIENT_ID", "ORANGE_ML_CLIENT_SECRET", "ORANGE_MONEY_CLIENT_SECRET",
        ):
            self.assertIn(name, message)


class NoSecretLeakTests(SimpleTestCase):
    SECRETS = ("ml-secret", "ml-merchant", "ml-id", "TOK-SECRET")

    def test_error_messages_never_contain_secrets_even_if_the_api_echoes_them(self):
        echo = "invalid ml-secret ml-merchant ml-id TOK-SECRET"
        cases = [
            [resp(401, {}, echo)],
            [resp(200, {"access_token": "TOK-SECRET"}), resp(400, {}, echo)],
            [
                resp(200, {"access_token": "TOK-SECRET"}),
                resp(200, {"merchant_key": "ml-merchant", "client_secret": "ml-secret"}),
            ],
        ]
        for responses in cases:
            with self.subTest(first=responses[0].status_code, n=len(responses)):
                with override_settings(**orange_settings(ML)), patch(POST, side_effect=responses):
                    with self.assertRaises(om.OrangeMoneyError) as cm:
                        initiate()
                for secret in self.SECRETS:
                    self.assertNotIn(secret, str(cm.exception))

    def test_status_check_error_never_contains_secrets(self):
        responses = [resp(200, {"access_token": "TOK-SECRET"}), resp(500, {}, "oops ml-secret TOK-SECRET")]
        with override_settings(**orange_settings(ML)), patch(POST, side_effect=responses):
            with self.assertRaises(om.OrangeMoneyError) as cm:
                om.get_transaction_status(order_id="HF-M-12345678", amount=2000, pay_token="p")
        for secret in self.SECRETS:
            self.assertNotIn(secret, str(cm.exception))

    def test_logs_never_contain_secrets(self):
        responses = [resp(200, {"access_token": "TOK-SECRET"}), resp(201, {"payment_url": "https://pay"})]
        with override_settings(**orange_settings(ML)), patch(POST, side_effect=responses):
            with self.assertLogs("subscriptions.services.orange_money", level="DEBUG") as logs:
                initiate()
        text = "\n".join(logs.output)
        for secret in self.SECRETS + ("n" * 64,):
            self.assertNotIn(secret, text)


class SettingsModuleReadsBothFamiliesTests(SimpleTestCase):
    """base.py applique la même règle (processus séparé : le .env local ne doit rien changer)."""

    def load(self, env):
        blank = {k: "" for k in os.environ if k.startswith(("ORANGE_ML_", "ORANGE_MONEY_"))}
        for suffix in SUFFIXES:
            blank[f"ORANGE_ML_{suffix}"] = ""
            blank[f"ORANGE_MONEY_{suffix}"] = ""
        code = (
            "import json; from django.conf import settings as s; "
            "print(json.dumps({k: getattr(s, k) for k in dir(s) if k.startswith('ORANGE_MONEY_')}))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, **blank, **env, "DJANGO_SETTINGS_MODULE": "config.settings.base"},
            cwd=Path(settings.BASE_DIR), capture_output=True, text=True, check=True, timeout=120,
        ).stdout
        return json.loads(out.strip().splitlines()[-1])

    def test_base_settings_follow_the_rule(self):
        self.assertEqual(self.load(ML)["ORANGE_MONEY_MERCHANT_KEY"], "ml-merchant")
        self.assertEqual(self.load(MONEY)["ORANGE_MONEY_MERCHANT_KEY"], "money-merchant")
        self.assertEqual(self.load({**MONEY, **ML})["ORANGE_MONEY_MERCHANT_KEY"], "ml-merchant")
        self.assertEqual(self.load({})["ORANGE_MONEY_MERCHANT_KEY"], "")
        loaded = self.load(ML)
        self.assertEqual((loaded["ORANGE_MONEY_TIMEOUT"], loaded["ORANGE_MONEY_CURRENCY"]), (33, "XAF"))
