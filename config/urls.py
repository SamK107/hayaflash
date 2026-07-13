from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
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
