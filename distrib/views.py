"""Vues du grossiste (`/distrib/`). FBV partout ; les regles metier vivent dans `services/`."""

from __future__ import annotations

from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .access import (
    distributor_required,
    feature_required,
    get_distributor_or_none,
    reseller_required,
)
from .forms import ResellerInviteForm
from .models import ResellerInvite
from .services import invites as invite_service

HOME_URL = "/distrib/"


def safe_next(request) -> str | None:
    """`?next=` limite aux pages de ce module (pas de redirection ouverte)."""
    candidate = request.GET.get("next", "")
    if "\\" in candidate or not candidate.startswith("/distrib/"):
        return None
    if url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return None


@feature_required
def connexion(request):
    """Entree dediee `/distrib/connexion/` (spec §5.1).

    La connexion existante (`/login/?next=...`) ignore `next` pour un utilisateur DEJA
    connecte (il atterrit sur `/seller/`) : on court-circuite ce cas ici, sans toucher a
    `core`. Un compte sans boutique ni role n'est jamais renvoye vers une page qui plante.
    """
    target = safe_next(request) or HOME_URL
    if not request.user.is_authenticated:
        return redirect(f"/login/?next={quote(target, safe='/')}")
    if get_distributor_or_none(request.user) is not None or safe_next(request):
        return redirect(target)
    return render(request, "distrib/not_distributor.html", status=403)


@distributor_required
def home(request):
    return render(request, "distrib/home.html", {"distributor": request.distributor})



# ── Revendeurs du grossiste (invitations) ─────────────────────────────────


def _errors_text(exc: ValidationError) -> str:
    return " ".join(exc.messages)


@distributor_required
def resellers(request):
    distributor = request.distributor
    form = ResellerInviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            invite_service.invite_reseller(
                distributor=distributor,
                display_name=form.cleaned_data["display_name"],
                phone=form.cleaned_data["phone_e164"],
            )
        except ValidationError as exc:
            form.add_error(None, _errors_text(exc))
        else:
            messages.success(request, "Invitation enregistrée. Le revendeur la verra sur son tableau de bord.")
            return redirect("distrib:resellers")
    invites = distributor.invites.select_related("seller")
    return render(
        request,
        "distrib/resellers.html",
        {"distributor": distributor, "invites": invites, "form": form},
    )


@distributor_required
@require_POST
def reseller_revoke(request, pk: int):
    # Cloisonnement : un grossiste ne touche que ses propres invitations.
    invite = get_object_or_404(ResellerInvite, pk=pk, distributor=request.distributor)
    try:
        invite_service.revoke_invite(invite=invite, actor=request.user)
    except ValidationError as exc:
        messages.error(request, _errors_text(exc))
    else:
        messages.success(
            request,
            f"{invite.display_name} est révoqué : plus de nouvelles importations. Les commandes en cours restent suivies.",
        )
    return redirect("distrib:resellers")


# ── Cote revendeur : consentement et « Mes grossistes » ───────────────────


@reseller_required
def invitation(request, pk: int):
    # Une invitation n'est visible que par le titulaire du numero invite.
    invite = get_object_or_404(
        ResellerInvite.objects.select_related("distributor"), pk=pk, phone=request.user.phone
    )
    if request.method == "POST":
        decision = request.POST.get("decision")
        if decision not in ("accept", "decline"):
            return redirect("distrib:invitation", pk=invite.pk)
        try:
            invite_service.answer_invite(invite=invite, user=request.user, accept=decision == "accept")
        except ValidationError as exc:
            messages.error(request, _errors_text(exc))
            return redirect("seller_home")
        if decision == "accept":
            messages.success(request, f"Vous êtes rattaché à {invite.distributor.business_name}.")
            return redirect("distrib:my_wholesalers")
        messages.info(request, "Invitation refusée. Rien n'est partagé.")
        return redirect("seller_home")
    return render(
        request,
        "distrib/invitation.html",
        {"invite": invite, "distributor": invite.distributor, "answerable": invite.status == ResellerInvite.Status.INVITED},
    )


@reseller_required
def my_wholesalers(request):
    accepted = invite_service.accepted_invites_for(request.seller)
    return render(request, "distrib/my_wholesalers.html", {"invites": accepted})
