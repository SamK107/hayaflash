"""D8 / D14 : staging non indexable, www -> domaine nu, HSTS prudent.

- Staging (hote non production) : robots.txt interdit tout, sans sitemap, et chaque
  reponse porte ``X-Robots-Tag: noindex, nofollow``.
- Production : comportement inchange (robots.txt avec sitemap, aucun X-Robots-Tag).
- www.hayaflash.com -> https://hayaflash.com en 301, chemin et requete conserves.
- HSTS : ni includeSubDomains ni preload, duree raisonnable.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from core.tests_security_settings import _import_prod_with


class StagingNoIndexTests(TestCase):
    @override_settings(SITE_NOINDEX=True)
    def test_robots_interdit_tout_et_n_annonce_pas_de_sitemap(self):
        resp = self.client.get("/robots.txt")
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp["Content-Type"])
        self.assertIn("User-agent: *", body)
        self.assertIn("Disallow: /\n", body + "\n")
        self.assertNotIn("Allow: /", body.replace("Disallow", ""))
        self.assertNotIn("Sitemap", body)

    @override_settings(SITE_NOINDEX=True)
    def test_chaque_reponse_porte_x_robots_tag(self):
        for url in ("/", "/robots.txt", "/cgu/", "/health/", "/page-inexistante/", "/ventes/"):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp["X-Robots-Tag"], "noindex, nofollow")

    @override_settings(SITE_NOINDEX=False)
    def test_production_robots_inchange(self):
        resp = self.client.get("/robots.txt")
        body = resp.content.decode()
        self.assertIn("Allow: /", body)
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("Sitemap:", body)
        self.assertIn("/sitemap.xml", body)

    @override_settings(SITE_NOINDEX=False)
    def test_production_sans_x_robots_tag(self):
        for url in ("/", "/robots.txt", "/health/"):
            with self.subTest(url=url):
                self.assertNotIn("X-Robots-Tag", self.client.get(url))


# Reglage derive de l'hote (prod.py importe avec un environnement factice).
def test_hote_de_staging_est_noindex_par_defaut(monkeypatch):
    mod = _import_prod_with(monkeypatch, ALLOWED_HOSTS="staging.hayaflash.com,localhost")
    assert mod.SITE_NOINDEX is True


@pytest.mark.parametrize("hosts", ["hayaflash.com,www.hayaflash.com,localhost", "hayaflash.com", ".hayaflash.com", "*"])
def test_hote_de_production_n_est_jamais_noindex(monkeypatch, hosts):
    mod = _import_prod_with(monkeypatch, ALLOWED_HOSTS=hosts)
    assert mod.SITE_NOINDEX is False


def test_noindex_explicite_refuse_sur_un_hote_de_production(monkeypatch):
    with pytest.raises(ImproperlyConfigured, match="HAYAFLASH_NOINDEX"):
        _import_prod_with(monkeypatch, ALLOWED_HOSTS="hayaflash.com", HAYAFLASH_NOINDEX="1")


def test_noindex_desactivable_explicitement_sur_un_hote_de_test(monkeypatch):
    mod = _import_prod_with(monkeypatch, ALLOWED_HOSTS="staging.hayaflash.com", HAYAFLASH_NOINDEX="0")
    assert mod.SITE_NOINDEX is False


def test_settings_staging_est_noindex():
    import importlib
    import os
    import sys

    saved = dict(os.environ), {n: m for n, m in sys.modules.items() if n.startswith("config.settings.")}
    try:
        os.environ.update(
            ENVIRONMENT="staging", SECRET_KEY="k", ALLOWED_HOSTS="staging.example",
            REDIS_URL="redis://localhost:6379/1", DATABASE_URL="postgres://u:p@localhost:5432/d",
            SENTRY_DSN="", DEBUG="false",
        )
        for n in ("config.settings.staging", "config.settings.base"):
            sys.modules.pop(n, None)
        assert importlib.import_module("config.settings.staging").SITE_NOINDEX is True
    finally:
        for n in [n for n in sys.modules if n.startswith("config.settings.")]:
            if n not in saved[1]:
                del sys.modules[n]
        sys.modules.update(saved[1])
        os.environ.clear()
        os.environ.update(saved[0])


class WwwRedirectTests(TestCase):
    REDIRECTS = {"www.hayaflash.com": "hayaflash.com"}

    @override_settings(CANONICAL_HOST_REDIRECTS=REDIRECTS, ALLOWED_HOSTS=["hayaflash.com", "www.hayaflash.com"])
    def test_www_redirige_en_301_vers_le_domaine_nu_en_https(self):
        resp = self.client.get("/f/ma-vente/?src=wa&ref=abc", HTTP_HOST="www.hayaflash.com")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "https://hayaflash.com/f/ma-vente/?src=wa&ref=abc")

    @override_settings(CANONICAL_HOST_REDIRECTS=REDIRECTS, ALLOWED_HOSTS=["hayaflash.com", "www.hayaflash.com"])
    def test_la_racine_et_les_hotes_en_majuscules_sont_geres(self):
        resp = self.client.get("/", HTTP_HOST="WWW.HayaFlash.com")
        self.assertEqual((resp.status_code, resp["Location"]), (301, "https://hayaflash.com/"))

    @override_settings(CANONICAL_HOST_REDIRECTS=REDIRECTS, ALLOWED_HOSTS=["hayaflash.com", "www.hayaflash.com"])
    def test_le_domaine_nu_n_est_pas_redirige(self):
        resp = self.client.get("/robots.txt", HTTP_HOST="hayaflash.com")
        self.assertEqual(resp.status_code, 200)

    @override_settings(CANONICAL_HOST_REDIRECTS={}, ALLOWED_HOSTS=["testserver", "www.hayaflash.com"])
    def test_sans_reglage_aucune_redirection(self):
        resp = self.client.get("/robots.txt", HTTP_HOST="www.hayaflash.com")
        self.assertEqual(resp.status_code, 200)

    @override_settings(CANONICAL_HOST_REDIRECTS=REDIRECTS, ALLOWED_HOSTS=["hayaflash.com"])
    def test_hote_non_declare_reste_refuse(self):
        resp = self.client.get("/", HTTP_HOST="www.hayaflash.com")
        self.assertEqual(resp.status_code, 400)


def test_prod_redirige_www_vers_le_domaine_nu(monkeypatch):
    mod = _import_prod_with(monkeypatch, ALLOWED_HOSTS="hayaflash.com,www.hayaflash.com")
    assert mod.CANONICAL_HOST_REDIRECTS == {"www.hayaflash.com": "hayaflash.com"}


def test_hsts_sans_sous_domaines_ni_preload(monkeypatch):
    mod = _import_prod_with(monkeypatch, ALLOWED_HOSTS="hayaflash.com,www.hayaflash.com")
    assert mod.SECURE_HSTS_INCLUDE_SUBDOMAINS is False
    assert mod.SECURE_HSTS_PRELOAD is False
    assert 2_592_000 <= mod.SECURE_HSTS_SECONDS <= 31_536_000
    assert "security.W005" in mod.SILENCED_SYSTEM_CHECKS and "security.W021" in mod.SILENCED_SYSTEM_CHECKS


def test_nginx_du_conteneur_n_envoie_ni_preload_ni_includesubdomains():
    from pathlib import Path

    conf = (Path(__file__).resolve().parent.parent / "infra/nginx/prod.conf").read_text(encoding="utf-8")
    hsts = [ln for ln in conf.splitlines() if "Strict-Transport-Security" in ln and not ln.strip().startswith("#")]
    assert hsts
    for line in hsts:
        assert "preload" not in line and "includeSubDomains" not in line
