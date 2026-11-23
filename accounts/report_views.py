"""Page publique « Signaler une boutique » (/signaler/<slug>/), sans compte.

Reponse neutre : le texte ne depend jamais du contenu du signalement, et une
boutique inactive ou inconnue repond 404 comme /s/<slug>/ (rien de plus).
Limite par IP sur toutes les soumissions (core/services/rate_limit.py).
"""

from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.models import SellerProfile
from accounts.report_forms import ShopReportForm
from accounts.services.shop_reports import create_shop_report
from core.services import honeypot, rate_limit

GENERIC_ERROR = "Impossible d'envoyer le signalement pour le moment. Réessaie dans un instant."


@never_cache
@require_http_methods(["GET", "POST"])
def shop_report_view(request: HttpRequest, slug: str) -> HttpResponse:
    shop = (
        SellerProfile.objects.filter(public_slug=(slug or "").strip().lower(), is_active=True)
        .only("id", "public_slug", "business_name")
        .first()
    )
    if shop is None:
        raise Http404

    context = {"shop": shop, "form": ShopReportForm(), "sent": False, "rate_limited": False}

    if request.method == "POST":
        if rate_limit.shop_report_ip_limited(request):
            context["rate_limited"] = True
            return render(request, "accounts/shop_report.html", context, status=429)
        # Rejet anti-bot : message generique, rien n'est enregistre (honeypot.rejection_reason : journaux).
        if honeypot.is_bot_submission(request.POST):
            context["error"] = GENERIC_ERROR
            return render(request, "accounts/shop_report.html", context)
        form = ShopReportForm(request.POST)
        context["form"] = form
        if form.is_valid():
            create_shop_report(
                shop,
                reason=form.cleaned_data["reason"],
                message=form.cleaned_data["message"],
                contact=form.cleaned_data["contact"],
            )
            context["sent"] = True
            context["form"] = ShopReportForm()
    return render(request, "accounts/shop_report.html", context)
