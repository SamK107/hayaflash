"""Outils de test partages : comptes SANS profil vendeur (accounts/access.py).

Nom volontairement hors du motif test*.py : ce module n'est pas collecte
comme suite de tests, il est importe par les tests de chaque app.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages

from accounts.access import NO_PROFILE_STAFF_MESSAGE


class NoSellerProfileMixin:
    """A melanger avec django.test.TestCase.

    self.staff : compte staff sans boutique ; self.plain : compte connecte
    ni staff ni vendeur. Aucun des deux ne doit jamais obtenir une 500 sur
    une page vendeur.
    """

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.staff = User.objects.create_user(
            phone="+22390000001", password="x", display_name="Admin", is_staff=True
        )
        self.plain = User.objects.create_user(
            phone="+22390000002", password="x", display_name="Sans boutique"
        )

    def _call(self, user, url, method):
        self.client.force_login(user)
        return getattr(self.client, method)(url)

    def assert_staff_redirected_to_pilotage(self, url, method="get"):
        resp = self._call(self.staff, url, method)
        self.assertRedirects(resp, "/platform-admin/", fetch_redirect_response=False)
        self.assertIn(
            NO_PROFILE_STAFF_MESSAGE, [str(m) for m in get_messages(resp.wsgi_request)]
        )

    def assert_plain_redirected_to_seller_home(self, url, method="get"):
        resp = self._call(self.plain, url, method)
        self.assertRedirects(resp, "/seller/", fetch_redirect_response=False)
        # /seller/ explique la situation au lieu de boucler vers /login/.
        page = self.client.get("/seller/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Ce compte n'a pas de boutique")

    def assert_no_profile_redirects(self, url, method="get"):
        self.assert_staff_redirected_to_pilotage(url, method)
        self.assert_plain_redirected_to_seller_home(url, method)

    def assert_forbidden_not_500(self, url, method="get"):
        """Fragments HTMX / appels AJAX : 403 explicite, jamais 500."""
        for user in (self.staff, self.plain):
            resp = self._call(user, url, method)
            self.assertEqual(resp.status_code, 403, (user.phone, url))
