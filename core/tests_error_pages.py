"""Pages d'erreur personnalisees (templates/404.html, 403.html, 500.html).

Toujours en DEBUG=False : en DEBUG=True Django affiche ses pages techniques
et les templates custom ne sont jamais rendus.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.urls import include, path


def _boom_view(request):
    raise RuntimeError("erreur volontaire (test page 500)")


def _forbidden_view(request):
    raise PermissionDenied


# Urlconf de test : le site reel + deux vues qui levent une exception.
urlpatterns = [
    path("__test__/boom/", _boom_view),
    path("__test__/forbidden/", _forbidden_view),
    path("", include("config.urls")),
]


@override_settings(DEBUG=False)
class NotFoundPageTests(TestCase):
    def test_unknown_url_renders_custom_404(self) -> None:
        response = self.client.get("/cette-url-n-existe-pas/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(
            response, "Cette page n'existe pas ou la vente est terminée", status_code=404
        )
        self.assertContains(response, 'href="/ventes/"', status_code=404)
        self.assertContains(response, 'name="robots" content="noindex"', status_code=404)

    def test_unknown_flash_sale_renders_custom_404(self) -> None:
        response = self.client.get("/f/slug-inexistant/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, 'href="/ventes/"', status_code=404)


@override_settings(DEBUG=False, ROOT_URLCONF="core.tests_error_pages")
class ServerErrorPageTests(TestCase):
    def test_unhandled_exception_renders_custom_500(self) -> None:
        client = Client(raise_request_exception=False)
        response = client.get("/__test__/boom/")
        self.assertEqual(response.status_code, 500)
        self.assertContains(
            response,
            "Un problème est survenu, réessayez dans un instant",
            status_code=500,
        )
        self.assertContains(response, 'href="/ventes/"', status_code=500)


@override_settings(DEBUG=False, ROOT_URLCONF="core.tests_error_pages")
class PermissionDeniedPageTests(TestCase):
    def test_permission_denied_renders_custom_403(self) -> None:
        response = self.client.get("/__test__/forbidden/")
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403.html")
        self.assertContains(
            response, "Vous n'avez pas accès à cette page", status_code=403
        )
