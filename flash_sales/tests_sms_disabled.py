"""F-81 / F-88 (D3) : aucune promesse de SMS au lancement, envoi inactif par defaut.

Le code d'envoi reste en place mais ne s'execute que si SMS_NOTIFICATIONS_ENABLED
est vrai. « M'alerter » reste honnete : c'est la vendeuse qui previent sur WhatsApp.
"""

from __future__ import annotations

from unittest.mock import patch

from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from flash_sales.models import FlashSaleStatus, SaleInterest
from flash_sales.tasks import send_pending_sale_reminders
from flash_sales.tests_alertes import AlertFixture
from notifications.models import Notification
from notifications.services import sms as sms_service
from notifications.tasks import send_order_confirmation, send_sale_reminder
from subscriptions.models import Plan, PlanConfig
from subscriptions.services.plans import get_features, invalidate_plan_cache


def _no_sms(html: str) -> bool:
    return "SMS" not in html and " sms " not in html.lower()


class NoSmsPromiseInPagesTests(AlertFixture):
    """Aucune page ne mentionne le SMS (pages publiques, legales, espace vendeur)."""

    def test_pages_publiques_et_legales(self):
        waiting = self.make_sale(start_in_h=3)
        ended = self.make_sale(status=FlashSaleStatus.CLOSED, start_in_h=-3, duration_h=1)
        live = self.make_sale(status=FlashSaleStatus.LIVE, start_in_h=-1, duration_h=3)
        pages = {
            "attente": self.page(waiting),
            "terminee": self.page(ended),
            "en direct": self.page(live),
        }
        for name in ("home", "legal_privacy", "legal_terms", "legal_notice"):
            cache.clear()
            pages[name] = self.client.get(reverse(name)).content.decode()
        for label, html in pages.items():
            with self.subTest(page=label):
                self.assertTrue(_no_sms(html), f"promesse de SMS dans la page « {label} »")

    def test_calendrier_public_et_espace_vendeur(self):
        self.make_sale(start_in_h=3)
        cache.clear()
        calendar = self.client.get("/ventes/").content.decode()
        self.assertTrue(_no_sms(calendar))
        self.client.force_login(self.user)
        for url in (reverse("seller_settings"), reverse("subscriptions:subscription")):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertTrue(_no_sms(resp.content.decode()), url)

    def test_m_alerter_dit_que_la_vendeuse_previent_sur_whatsapp(self):
        html = self.page(self.make_sale(start_in_h=3))
        self.assertIn("vous préviendra sur WhatsApp dès l'ouverture", html)


class PlanFeaturesTests(TestCase):
    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)

    def test_le_plan_pro_ne_promet_plus_de_sms(self):
        for plan in (Plan.FREE, Plan.MEDIUM, Plan.PRO):
            with self.subTest(plan=plan):
                self.assertFalse(any("SMS" in f for f in get_features(plan)))

    def test_la_migration_retire_la_ligne_et_garde_le_reste(self):
        from importlib import import_module

        mig = import_module("subscriptions.migrations.0010_retire_promesse_sms")
        PlanConfig.objects.filter(plan=Plan.PRO).update(
            features=["Tableau de bord LIVE temps réel", mig.PHRASE, "Support prioritaire WhatsApp"]
        )
        mig.retirer(django_apps, None)
        self.assertEqual(
            PlanConfig.objects.get(plan=Plan.PRO).features,
            ["Tableau de bord LIVE temps réel", "Support prioritaire WhatsApp"],
        )
        mig.retirer(django_apps, None)  # idempotente
        self.assertEqual(len(PlanConfig.objects.get(plan=Plan.PRO).features), 2)


@override_settings(SMS_NOTIFICATIONS_ENABLED=False)
class SmsInactiveByDefaultTests(AlertFixture):
    def test_send_sms_n_appelle_aucune_passerelle(self):
        with override_settings(ORANGE_SMS_API_KEY="k", ORANGE_SMS_BASE_URL="https://sms.example"), patch(
            "notifications.services.sms.requests.post"
        ) as post:
            self.assertFalse(sms_service.send_sms("+22370000001", "bonjour"))
        post.assert_not_called()

    def test_reglage_actif_reprend_l_envoi(self):
        with override_settings(
            SMS_NOTIFICATIONS_ENABLED=True, ORANGE_SMS_API_KEY="k", ORANGE_SMS_BASE_URL="https://sms.example"
        ), patch("notifications.services.sms.requests.post") as post:
            self.assertTrue(sms_service.send_sms("+22370000001", "bonjour"))
        post.assert_called_once()

    def test_les_rappels_automatiques_ne_font_aucun_appel_reseau(self):
        sale = self.make_sale(start_in_h=0.5)
        SaleInterest.objects.create(flash_sale=sale, phone="+22370000099", name="Inscrite")
        with patch("notifications.tasks.send_sale_reminder") as reminder:
            send_pending_sale_reminders()
        reminder.assert_not_called()
        self.assertFalse(SaleInterest.objects.get().reminded_at)
        self.assertEqual(Notification.objects.count(), 0)

    def test_confirmation_de_commande_ne_stocke_aucune_notification(self):
        send_order_confirmation(1)
        self.assertEqual(Notification.objects.count(), 0)

    def test_rappel_individuel_retourne_faux_sans_trace(self):
        sale = self.make_sale(start_in_h=0.5)
        self.assertFalse(send_sale_reminder(sale.pk, "+22370000099"))
        self.assertEqual(Notification.objects.count(), 0)

    def test_valeur_par_defaut_du_reglage_hors_tests(self):
        """Sans la variable d'environnement, les SMS sont inactifs (processus neuf)."""
        import os
        import subprocess
        import sys

        from django.conf import settings

        env = {k: v for k, v in os.environ.items() if k != "SMS_NOTIFICATIONS_ENABLED"}
        env["PYTHON_DOTENV_DISABLED"] = "1"
        out = subprocess.run(
            [sys.executable, "-I", "-c",
             "import sys; sys.path.insert(0, %r); import config.settings.base as b; print(b.SMS_NOTIFICATIONS_ENABLED)"
             % str(settings.BASE_DIR)],
            env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(out.stdout.strip().splitlines()[-1], "False", out.stderr)
