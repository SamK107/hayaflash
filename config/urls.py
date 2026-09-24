from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView

from config.api_urls import health
from core import views as core_views
from core.sitemaps import sitemaps

urlpatterns = [
    path("admin/", admin.site.urls),
    # Les navigateurs demandent /favicon.ico a la racine, quelle que soit la page.
    path("favicon.ico", RedirectView.as_view(url="/static/favicon.ico", permanent=True)),
    # Service worker a la racine : portee "/" (PWA installable + hors ligne).
    path("sw.js", core_views.service_worker, name="service_worker"),
    path(
        "robots.txt",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
        name="robots_txt",
    ),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    # Alias racine : Dockerfile HEALTHCHECK, docker-compose.production.yml et
    # infra/nginx/prod.conf ciblent tous /health/ (pas /api/v1/health/).
    # Sans cet alias, le healthcheck 404 silencieusement (jamais "unhealthy",
    # juste faux — un `docker inspect` ne le detecte pas sans y regarder).
    path("health/", health, name="health"),
    path("api/v1/", include("config.api_urls")),
    path("orders/", include("orders.urls")),
    path("seller/flash-sales/", include("flash_sales.urls")),
    path("seller/flash-sales/", include("products.urls")),
    path("seller/", include("core.seller_urls")),
    path("seller/", include("subscriptions.urls")),
    path("seller/", include("accounts.seller_urls")),
    path("billing/", include("subscriptions.billing_urls")),
    path("", include("analytics.urls")),
    path("", include("core.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass
