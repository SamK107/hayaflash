from datetime import timedelta

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import FlashSale
from .services.ordering import live_now_q, upcoming_q


SOON_WINDOW = timedelta(hours=1)
UPCOMING_LIMIT = 40
_WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def _calendar_groups(now):
    """Ventes en cours + programmees, regroupees pour l'affichage en liste.

    Groupes (dans l'ordre) : "live" (fin la plus proche d'abord), "soon"
    (debut dans moins d'1 h), "today", "tomorrow", puis un groupe par date.
    Selection par l'heure (live_now_q / upcoming_q) : une vente terminee
    n'apparait jamais, meme si Celery ne l'a pas fermee.
    """
    base = FlashSale.objects.select_related("owner").only(
        "title", "public_slug", "start_time", "end_time", "category", "status",
        "owner__business_name", "owner__category", "owner__avatar",
    )
    live = list(base.filter(live_now_q(now)).order_by("end_time"))
    upcoming = list(base.filter(upcoming_q(now)).order_by("start_time")[:UPCOMING_LIMIT])

    groups = []
    if live:
        groups.append({"key": "live", "label": "En direct", "sales": live})
    today = timezone.localtime(now).date()
    buckets: dict = {}
    for sale in upcoming:
        if sale.start_time - now <= SOON_WINDOW:
            key, label = "soon", "Bientôt"
        else:
            day = timezone.localtime(sale.start_time).date()
            if day == today:
                key, label = "today", "Aujourd’hui"
            elif day == today + timedelta(days=1):
                key, label = "tomorrow", "Demain"
            else:
                key, label = day.isoformat(), f"{_WEEKDAYS[day.weekday()]} {day:%d/%m}"
        buckets.setdefault(key, {"key": key, "label": label, "sales": []})["sales"].append(sale)
    groups.extend(buckets.values())  # insertion = ordre chronologique
    return groups


def public_flash_sale_calendar(request):
    """Page publique : ventes en cours et programmees, en liste compacte.

    Requete HTMX (rafraichissement periodique / quand un compte a rebours
    franchit une limite) -> seulement la liste.
    """
    groups = _calendar_groups(timezone.now())
    template = (
        "flash_sales/partials/_calendar_list.html"
        if request.headers.get("HX-Request")
        else "flash_sales/public_calendar.html"
    )
    return render(request, template, {"groups": groups})


def public_flash_sale_detail(request, slug):
    """Ancienne page /ventes/<slug>/ : redirige vers la page officielle /f/<slug>/.

    Doublon (CLAUDE.md point 14) qui affichait l'etat d'apres le statut brut
    ("EN DIRECT", prix, bouton Commander sur une vente terminee depuis des
    semaines). /f/<slug>/ porte le SEO complet et gere en direct / programmee /
    terminee. 301 : les anciens liens partages continuent de fonctionner.
    """
    sale = get_object_or_404(FlashSale, public_slug=slug)
    return redirect("public_flash_sale", slug=sale.public_slug, permanent=True)
