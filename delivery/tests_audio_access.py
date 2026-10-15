"""E4 : les notes vocales des clients (delivery/audio/) ne sont plus servies par /media/ sans contrôle d'accès.

Elles contiennent la voix et la localisation d'un client. Elles ne sont lisibles que par le vendeur propriétaire de la
livraison, par une vue authentifiée : 404 pour tous les autres (autre vendeur, équipe non propriétaire, anonyme,
livraison inconnue ou sans audio). En développement, `FileResponse` ; en staging et production, `X-Accel-Redirect` vers
une location Nginx interne (`/_protected_media/`), et l'accès direct à `/media/delivery/audio/` est refusé.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import Client, override_settings
from django.urls import reverse

from core.tests_nginx_headers import _blocks
from delivery.models import Delivery
from delivery.tests import DeliveryTestFixture
from orders.models import Order

AUDIO = b"RIFF\x00\x00\x00\x00WEBMfake-audio-bytes"
CONF = Path(settings.BASE_DIR) / "infra" / "nginx" / "prod.conf"


class AudioBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="hf-media-")
        self.addCleanup(shutil.rmtree, self.media, True)
        self.settings_override = override_settings(MEDIA_ROOT=self.media)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        order = Order.service_objects.create(flash_sale=self.sale, customer_name="Client", customer_phone="+22370000009")
        self.delivery = Delivery.objects.create(order=order, address_text="Hamdallaye", cod_amount=1999)
        self.delivery.audio_note.save("note.webm", ContentFile(AUDIO), save=True)
        self.url = reverse("orders:seller_delivery_audio", args=[self.delivery.pk])
        self.owner = Client()
        self.owner.force_login(self.seller_user)

    def get(self, client=None, url=None):
        return (client or self.owner).get(url or self.url)


class AccessControlTests(AudioBase):
    def test_the_owner_seller_can_play_the_note(self):
        resp = self.get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), AUDIO)

    def test_other_seller_gets_a_404(self):
        other = Client()
        other.force_login(self.other_user)
        self.assertEqual(self.get(other).status_code, 404)

    def test_anonymous_gets_a_404_not_a_redirect_to_login(self):
        resp = self.get(Client())
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("Location", resp)

    def test_a_staff_member_who_is_not_the_owner_gets_a_404(self):
        from django.contrib.auth import get_user_model

        staff = get_user_model().objects.create_user(phone="+22379000050", password="x", display_name="Eq", is_staff=True)
        client = Client()
        client.force_login(staff)
        self.assertEqual(self.get(client).status_code, 404)

    def test_unknown_delivery_a_delivery_without_audio_and_a_missing_file_get_a_404(self):
        self.assertEqual(self.get(url=reverse("orders:seller_delivery_audio", args=[uuid4()])).status_code, 404)
        Delivery.objects.filter(pk=self.delivery.pk).update(audio_note="")
        self.assertEqual(self.get().status_code, 404)
        Delivery.objects.filter(pk=self.delivery.pk).update(audio_note="delivery/audio/2026/10/absent.webm")
        self.assertEqual(self.get().status_code, 404)

    def test_only_get_is_accepted(self):
        self.assertEqual(self.owner.post(self.url).status_code, 405)

    def test_a_crafted_file_name_outside_delivery_audio_is_refused(self):
        for name in ("../../etc/passwd", "products/cover.webm", "/etc/passwd", "delivery/audio/../../secret.webm"):
            with self.subTest(name=name):
                Delivery.objects.filter(pk=self.delivery.pk).update(audio_note=name)
                self.assertEqual(self.get().status_code, 404)


class DevelopmentResponseTests(AudioBase):
    def test_headers_in_development(self):
        resp = self.get()
        self.assertEqual(resp["Content-Type"], "audio/webm")
        self.assertEqual(resp["Cache-Control"], "private, no-store")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertTrue(resp["Content-Disposition"].startswith("inline"))
        self.assertNotIn("X-Accel-Redirect", resp)

    def test_content_type_follows_the_extension(self):
        for ext, expected in (("ogg", "audio/ogg"), ("mp3", "audio/mpeg"), ("m4a", "audio/mp4"), ("wav", "audio/wav")):
            with self.subTest(ext=ext):
                self.delivery.audio_note.save(f"n.{ext}", ContentFile(AUDIO), save=True)
                self.assertEqual(self.get()["Content-Type"], expected)


@override_settings(PROTECTED_MEDIA_X_ACCEL_REDIRECT=True)
class ProductionResponseTests(AudioBase):
    def test_the_file_is_served_by_nginx_through_an_internal_location(self):
        resp = self.get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"")  # Django ne lit ni ne diffuse le fichier
        name = self.delivery.audio_note.name
        self.assertTrue(name.startswith("delivery/audio/"))
        self.assertEqual(resp["X-Accel-Redirect"], f"/_protected_media/{name}")
        self.assertEqual(resp["Content-Type"], "audio/webm")
        self.assertEqual(resp["Cache-Control"], "private, no-store")

    def test_a_denied_request_never_sets_the_internal_redirect(self):
        resp = self.get(Client())
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("X-Accel-Redirect", resp)

    def test_the_redirect_target_is_percent_encoded(self):
        self.delivery.audio_note.save("voix client é.webm", ContentFile(AUDIO), save=True)
        header = self.get()["X-Accel-Redirect"]
        self.assertNotIn(" ", header)
        self.assertTrue(header.startswith("/_protected_media/delivery/audio/"))


class TemplateTests(AudioBase):
    def test_the_dashboard_uses_the_protected_url_and_never_the_direct_media_url(self):
        url = reverse("orders:seller_deliveries_list") + f"?flash_sale_id={self.sale.pk}"
        html = self.owner.get(url).content.decode()
        self.assertIn(self.url, html)
        self.assertNotIn("/media/delivery/audio", html)
        self.assertNotIn(self.delivery.audio_note.name, html)


class SettingsTests(AudioBase):
    def test_the_redirect_is_off_in_development_and_tests(self):
        self.assertFalse(settings.PROTECTED_MEDIA_X_ACCEL_REDIRECT)

    def test_base_settings_enable_it_in_staging_and_production(self):
        import json
        import os
        import subprocess
        import sys

        code = "import json; from django.conf import settings as s; print(json.dumps(s.PROTECTED_MEDIA_X_ACCEL_REDIRECT))"
        results = {}
        for env in ("dev", "staging", "prod"):
            out = subprocess.run(
                [sys.executable, "-c", code],
                # Hermétique : staging et production exigent une base (DATABASE_URL), que le .env local fournit mais
                # pas la CI ; aucune connexion n'est ouverte, les réglages sont seulement chargés.
                env={
                    **os.environ,
                    "DJANGO_SETTINGS_MODULE": "config.settings.base",
                    "ENVIRONMENT": env,
                    "DEBUG": "False",
                    "SECRET_KEY": "x" * 40,
                    "DATABASE_URL": "postgres://hf:hf@localhost:5432/hf",
                },
                cwd=settings.BASE_DIR, capture_output=True, text=True, check=True, timeout=120,
            ).stdout
            results[env] = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(results, {"dev": False, "staging": True, "prod": True})


class DirectAccessUrlGuardTests(AudioBase):
    def test_the_development_media_route_refuses_delivery_audio(self):
        from config import urls

        patterns = [str(p.pattern) for p in urls.urlpatterns]
        self.assertTrue(any("delivery/audio" in p for p in patterns), patterns)

    def test_the_direct_media_url_is_not_served_to_anyone(self):
        direct = f"/media/{self.delivery.audio_note.name}"
        self.assertEqual(self.owner.get(direct).status_code, 404)
        self.assertEqual(Client().get(direct).status_code, 404)


class NginxConfigTests(AudioBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.conf = CONF.read_text(encoding="utf-8").replace("\r\n", "\n")
        cls.blocks = dict(_blocks(cls.conf))

    def test_direct_access_to_delivery_audio_is_refused(self):
        body = self.blocks["^~ /media/delivery/audio/"]
        self.assertRegex(body, r"return\s+404\s*;")
        self.assertNotIn("alias", body)

    def test_the_internal_location_serves_the_media_volume_only_for_x_accel(self):
        body = self.blocks["/_protected_media/"]
        self.assertRegex(body, r"^\s*internal;", )
        self.assertIn("alias /srv/media/;", body)
        self.assertIn("access_log off;", body)

    def test_the_internal_location_keeps_the_security_and_cache_headers(self):
        body = self.blocks["/_protected_media/"]
        for header in ("Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
            self.assertIn(header, body, header)
        self.assertRegex(body, r'add_header Content-Security-Policy "default-src \'none\'; sandbox" always;')
        self.assertNotIn("add_header Cache-Control", body)  # celui de Django est conservé : pas de doublon

    def test_the_direct_block_is_a_longer_prefix_than_the_general_media_location(self):
        # Nginx choisit le préfixe le plus long (l'ordre dans le fichier ne compte pas) ; ^~ exclut les regex.
        self.assertIn("/media/", self.blocks)
        self.assertGreater(len("/media/delivery/audio/"), len("/media/"))
        self.assertRegex(self.conf, r"location\s+\^~\s+/media/delivery/audio/")
