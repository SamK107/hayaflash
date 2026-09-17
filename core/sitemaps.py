"""
Sitemap XML pour l'indexation des pages publiques HayaFlash.

Ne couvre que les URLs vraiment publiques et destinées à l'indexation :
- accueil marketing
- calendrier public des ventes (/ventes/)
- pages publiques vente flash (/f/<slug>/ — canonique, cf. templates/analytics/flash_sale_public.html)
- pages publiques vendeur (/s/<slug>/)

Ne référence PAS /ventes/<slug>/ (flash_sales/public_detail.html) : cette page
duplique /f/<slug>/ et pointe déjà vers elle via <link rel="canonical">
(voir templates/flash_sales/public_detail.html) — l'indexer en plus créerait
du contenu dupliqué.
"""

from __future__ import annotations

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = "daily"

    def items(self):
        return ["home", "flash_sale_calendar"]

    def location(self, item):
        return reverse(item)


class FlashSaleSitemap(Sitemap):
    changefreq = "hourly"  # stock/statut change vite pendant une vente live

    def items(self):
        # Seules les ventes visibles publiquement méritent d'être indexées —
        # une vente terminée/annulée n'a plus d'intérêt pour un moteur de
        # recherche et sa page affiche un état "vente terminée".
        return FlashSale.objects.filter(
            status__in=[FlashSaleStatus.LIVE, FlashSaleStatus.SCHEDULED]
        ).order_by("-start_time")

    def location(self, item):
        return reverse("public_flash_sale", kwargs={"slug": item.public_slug})

    def lastmod(self, item):
        return item.updated_at

    def priority(self, item):
        return 0.9 if item.status == FlashSaleStatus.LIVE else 0.6


class SellerSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return SellerProfile.objects.filter(is_active=True)

    def location(self, item):
        return reverse("public_seller", kwargs={"slug": item.public_slug})

    def lastmod(self, item):
        return item.updated_at


sitemaps = {
    "static": StaticViewSitemap,
    "flash_sales": FlashSaleSitemap,
    "sellers": SellerSitemap,
}
