"""Middlewares de hote : redirection www -> domaine nu, et staging non indexable (D8/D14)."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpResponsePermanentRedirect


class CanonicalHostMiddleware:
    """Redirige en 301 les hotes listes dans CANONICAL_HOST_REDIRECTS vers l'hote canonique.

    Garde le chemin et la requete (``/f/abc/?src=wa`` reste intact). Toujours vers
    https : la production n'est servie qu'en HTTPS. Inactif si le reglage est vide
    (dev, tests, staging). L'hote reste soumis a ALLOWED_HOSTS (``get_host``).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        redirects = getattr(settings, "CANONICAL_HOST_REDIRECTS", None)
        if redirects:
            host = request.get_host().split(":")[0].lower()
            target = redirects.get(host)
            if target:
                return HttpResponsePermanentRedirect(f"https://{target}{request.get_full_path()}")
        return self.get_response(request)


class NoIndexMiddleware:
    """Ajoute ``X-Robots-Tag: noindex, nofollow`` a toute reponse quand SITE_NOINDEX est vrai."""

    HEADER = "X-Robots-Tag"
    VALUE = "noindex, nofollow"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(settings, "SITE_NOINDEX", False):
            response[self.HEADER] = self.VALUE
        return response
