"""
URLs publiques stables pour les callbacks Orange Money.
Prefixe : /billing/
Ces chemins sont enregistres chez Orange Money et ne changent pas entre dev et prod.
"""

from django.urls import path
from . import billing_views

urlpatterns = [
    path("return/", billing_views.billing_return_view, name="billing_return"),
    path("cancel/", billing_views.billing_cancel_view, name="billing_cancel"),
    path(
        "webhook/orange/",
        billing_views.billing_callback_view,
        name="billing_callback_orange",
    ),
]
