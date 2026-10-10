"""Pages publiques par lien privé : consultation et acceptation des documents du programme.

Sécurité : jeton inconnu, expiré ou révoqué = 404 identique ; limite de débit par IP ;
CSRF normal ; ni indexation, ni cache, ni référent ; le jeton n'est jamais journalisé.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.defaults import page_not_found

from core.services import rate_limit
from partners import legal_docs
from partners.models import (
    AccessLinkPurpose,
    AcceptanceDocType,
    PartnerAccessLink,
    PartnerAcceptance,
)
from partners.services.access_links import resolve_token
from partners.services.acceptance import (
    CHECKBOX_MESSAGE,
    accept_document,
    pending_document,
)
from partners.services import verification
from partners.services.attribution import request_ip_hash

RATE_MESSAGE = "Trop de demandes. Réessayez dans quelques minutes."


def _secure(response):
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "no-store, private"
    # « same-origin » et non « no-referrer » : avec no-referrer, le navigateur envoie
    # « Origin: null » sur le POST du formulaire et Django refuse le CSRF (403) meme avec un
    # jeton valide. same-origin n'envoie jamais l'URL (donc le jeton) a un site tiers.
    response["Referrer-Policy"] = "same-origin"
    return response


def _not_found(request):
    from django.http import Http404

    return _secure(page_not_found(request, Http404()))


def _context(request, token, link, partner, **extra):
    doc_type = pending_document(partner) if link.purpose == AccessLinkPurpose.ACCEPT else None
    ctx = {
        "partner": partner,
        "link": link,
        "token_for_url": token,
        "doc_type": doc_type,
        "accepted": list(PartnerAcceptance.objects.filter(partner=partner).order_by("accepted_at")),
        "draft_banner": False,
        "error": "",
    }
    if doc_type:
        ctx.update(
            doc=legal_docs.DOCS[doc_type],
            document_html=legal_docs.render_document(doc_type, partner),
            draft_banner=not legal_docs.is_complete(doc_type),
            is_letter=doc_type == AcceptanceDocType.TRIAL_LETTER,
            cite_label=legal_docs.CITE_SHOP_LABEL,
        )
    ctx.update(extra)
    return ctx


USED_LINK_MESSAGE = (
    "Ce lien a déjà servi à une acceptation. Le document accepté reste consultable ci-dessous."
)


def _final_page(request, acceptance, *, error="", status=200):
    """Page en lecture seule du document accepté, rendue depuis l'enregistrement."""
    url = verification.verify_url(request, acceptance)
    return _secure(
        render(
            request,
            "partners/public/confirmation.html",
            {
                "acceptance": acceptance,
                "partner": acceptance.partner,
                "error": error,
                "seal": verification.seal_context(acceptance),
                "verify_url": url,
                "qr_svg": verification.qr_svg(url),
                "valid": not acceptance.is_invalidated,
            },
            status=status,
        )
    )


@require_GET
def verify_page(request, code: str):
    """Vérification publique d'une acceptation : aucune donnée personnelle, 404 neutre."""
    if rate_limit.partner_link_ip_limited(request):
        return _limited_response()
    acceptance = verification.find_acceptance(code)
    if acceptance is None:
        return _not_found(request)
    return _secure(
        render(request, "partners/public/verify.html", {"s": verification.public_summary(acceptance)})
    )


def _limited_response():
    return _secure(HttpResponse(RATE_MESSAGE, status=429, content_type="text/plain; charset=utf-8"))


@require_GET
def document_page(request, token: str):
    if rate_limit.partner_link_ip_limited(request):
        return _limited_response()
    link = resolve_token(token)
    if link is None:
        return _not_found(request)
    if link.acceptance_id:
        return _final_page(request, link.acceptance)
    return _secure(render(request, "partners/public/document.html", _context(request, token, link, link.partner)))


@require_POST
def document_accept(request, token: str):
    if rate_limit.partner_link_ip_limited(request):
        return _limited_response()
    link = resolve_token(token)
    if link is None:
        return _not_found(request)
    partner = link.partner
    if link.purpose != AccessLinkPurpose.ACCEPT:
        return _secure(HttpResponse("Ce lien est en lecture seule.", status=403))
    if link.acceptance_id:  # un jeton = une acceptation (jamais de blocage sur l'IP)
        return _final_page(request, link.acceptance, error=USED_LINK_MESSAGE, status=409)

    doc_type = pending_document(partner)
    if doc_type is None:
        ctx = _context(request, token, link, partner, error="Aucun document n'est à accepter pour le moment.")
        return _secure(render(request, "partners/public/document.html", ctx))
    if not request.POST.get("accept_terms"):
        return _secure(render(request, "partners/public/document.html", _context(request, token, link, partner, error=CHECKBOX_MESSAGE)))
    optional = {}
    if doc_type == AcceptanceDocType.TRIAL_LETTER:
        optional["cite_shop"] = bool(request.POST.get("cite_shop"))
    try:
        acceptance, created = accept_document(
            partner,
            doc_type,
            signer_name=request.POST.get("signer_name", ""),
            ip_hash=request_ip_hash(request),
            optional_consents=optional,
        )
    except ValidationError as exc:
        ctx = _context(request, token, link, partner, error=" ".join(exc.messages))
        return _secure(render(request, "partners/public/document.html", ctx))

    if not created:  # envoi simultané : l'acceptation existe déjà, pas de doublon
        return _final_page(request, acceptance, error=USED_LINK_MESSAGE, status=409)
    PartnerAccessLink.objects.filter(pk=link.pk, acceptance__isnull=True).update(acceptance=acceptance)
    return _final_page(request, acceptance)
