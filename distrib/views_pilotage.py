"""Pilotage HayaFlash (`/distrib/pilotage/`, reserve au staff)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import render

from .access import staff_required
from .forms import DistributorCreateForm
from .models import Distributor
from .services.distributors import create_distributor


@staff_required
def pilotage_home(request):
    distributors = Distributor.objects.select_related("user").annotate(
        reseller_count=Count("invites", distinct=True),
        product_count=Count("wholesale_products", distinct=True),
    )
    return render(request, "distrib/pilotage/home.html", {"distributors": distributors})


@staff_required
def pilotage_distributor_create(request):
    form = DistributorCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            distributor, temporary_password = create_distributor(
                phone=data["phone_e164"],
                display_name=data["display_name"],
                business_name=data["business_name"],
                created_by=request.user,
                orange_money_number=data.get("orange_money_e164", ""),
                commission_rate=data["commission_rate"],
                pilot_until=data.get("pilot_until"),
            )
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
        else:
            # Pas de redirection : le mot de passe provisoire n'est montre qu'ici, une seule fois.
            response = render(
                request,
                "distrib/pilotage/distributor_created.html",
                {"distributor": distributor, "temporary_password": temporary_password},
            )
            response["Cache-Control"] = "no-store"
            return response
    return render(request, "distrib/pilotage/distributor_form.html", {"form": form})
