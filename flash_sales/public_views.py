from datetime import timedelta

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from analytics.services.market import get_market_snapshot
from core.choices import SaleCategory

from .market_stats import get_market_stats
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


def _ago_label(minutes: int) -> str:
    if minutes < 1:
        return "Terminée à l’instant"
    if minutes < 60:
        return f"Terminée il y a {minutes} min"
    h, m = divmod(minutes, 60)
    return f"Terminée il y a {h} h" + (f" {m:02d}" if m else "")


def _market_context(now):
    """Contexte du Marche : groupes, stats par vente, bandeau, etat calme.

    Les ventes viennent de ``_calendar_groups`` (2 requetes) ; les agregats
    (commandes, % vendu, ventes terminees) du snapshot cache 30 s.
    """
    snapshot = get_market_snapshot(now)
    groups = _calendar_groups(now)
    live = next((g["sales"] for g in groups if g["key"] == "live"), [])
    for sale in live:
        sale.market = snapshot["sales"].get(sale.pk, {})

    # Etat calme : aucune vente en direct -> la prochaine vente en vedette
    # (retiree de sa liste pour ne pas apparaitre deux fois).
    hero = None
    if not live and groups:
        first = groups[0]
        hero = first["sales"].pop(0)
        if not first["sales"]:
            groups.pop(0)

    ticker = [{"sale": s, "live": True} for s in live]
    if hero is not None and hero.start_time - now <= SOON_WINDOW:
        ticker.append({"sale": hero, "live": False})
    for group in groups:
        if group["key"] == "soon":
            ticker.extend({"sale": s, "live": False} for s in group["sales"])

    ended = []
    for item in snapshot["recently_ended"]:
        minutes = max(0, int((now - item["end_time"]).total_seconds() // 60))
        ended.append({**item, "ago": _ago_label(minutes)})

    # Puces de filtre : categories presentes parmi les ventes affichees.
    present = {s.effective_category for g in groups for s in g["sales"]}
    if hero is not None:
        present.add(hero.effective_category)
    present.update(item["category"] for item in ended)
    categories = [(v, label) for v, label in SaleCategory.choices if v in present]

    return {
        "stats": get_market_stats(now),
        "groups": groups,
        "hero": hero,
        "ticker": ticker,
        "ended": ended,
        "categories": categories,
        "category_slugs": " ".join(v for v, _ in categories),
        "has_live": bool(live),
        # Cartes avec bouton « M'alerter » : a venir, vedette, terminees.
        "has_alert_cards": bool(hero or ended or any(g["key"] != "live" for g in groups)),
        "has_anything": bool(groups or hero or ended or live),
    }


def public_flash_sale_calendar(request):
    """Le Marche HayaFlash : ventes en direct, a venir et recemment terminees.

    Requete HTMX (rafraichissement 30 s / quand un compte a rebours franchit
    une limite / retour sur l'onglet) -> seulement la liste. En-tetes de cache
    inchanges : la liste n'est jamais mise en cache navigateur.
    """
    context = _market_context(timezone.now())
    template = (
        "flash_sales/partials/_calendar_list.html"
        if request.headers.get("HX-Request")
        else "flash_sales/public_calendar.html"
    )
    return render(request, template, context)


def public_flash_sale_detail(request, slug):
    """Ancienne page /ventes/<slug>/ : redirige vers la page officielle /f/<slug>/.

    Doublon (CLAUDE.md point 14) qui affichait l'etat d'apres le statut brut
    ("EN DIRECT", prix, bouton Commander sur une vente terminee depuis des
    semaines). /f/<slug>/ porte le SEO complet et gere en direct / programmee /
    terminee. 301 : les anciens liens partages continuent de fonctionner.
    """
    sale = get_object_or_404(FlashSale, public_slug=slug)
    return redirect("public_flash_sale", slug=sale.public_slug, permanent=True)
