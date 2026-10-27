"""Vues du grossiste (`/distrib/`). FBV partout ; les regles metier vivent dans `services/`."""

from __future__ import annotations

from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
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
from .models import DistribSettlement
from .services import dashboard
from .services import invites as invite_service
from .services import settlement as settlement_service

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


def _home_context(distributor) -> dict:
    now = timezone.now()
    from .views_orders import auto_confirm_info

    soonest = (
        DistribSettlement.objects.filter(
            distributor=distributor, status__in=settlement_service.OPEN_STATUSES, auto_confirm_at__isnull=False
        )
        .select_related("imported_product__wholesale_product", "invite")
        .order_by("auto_confirm_at")[:5]
    )
    return {
        "distributor": distributor,
        "summary": dashboard.distributor_summary(distributor, now),
        "soonest": [{"line": line, "countdown": auto_confirm_info(line, now)} for line in soonest],
    }


@distributor_required
def home(request):
    return render(request, "distrib/home.html", _home_context(request.distributor))


@distributor_required
def home_fragment(request):
    """Rafraichi par HTMX toutes les 30 s."""
    response = render(request, "distrib/_home_live.html", _home_context(request.distributor))
    response["Cache-Control"] = "private, no-store"
    return response



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
    return render(
        request,
        "distrib/resellers.html",
        {"distributor": distributor, "overview": dashboard.reseller_overview(distributor), "form": form},
    )


@distributor_required
def resellers_fragment(request):
    response = render(
        request,
        "distrib/_resellers_live.html",
        {"overview": dashboard.reseller_overview(request.distributor)},
    )
    response["Cache-Control"] = "private, no-store"
    return response


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


def _wholesalers_context(seller) -> dict:
    return {
        "invites": invite_service.accepted_invites_for(seller),
        "summary": dashboard.reseller_summary(seller),
    }


@reseller_required
def my_wholesalers(request):
    return render(request, "distrib/my_wholesalers.html", _wholesalers_context(request.seller))


@reseller_required
def my_wholesalers_fragment(request):
    response = render(request, "distrib/_wholesalers_live.html", _wholesalers_context(request.seller))
    response["Cache-Control"] = "private, no-store"
    return response
