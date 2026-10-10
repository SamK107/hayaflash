"""Pages d'administration du programme partenaires : réservées au staff.

Même protection que l'espace plateforme (``staff_member_required``) : un anonyme ou
un vendeur reçoit exactement la même réponse que sur /platform-admin/.
"""

from __future__ import annotations

from datetime import datetime, time

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import audit
from partners import legal_docs
from partners.models import (
    AcceptanceInvalidation,
    CommissionEntry,
    OutboundMessage,
    Partner,
    PartnerAccessLink,
    PartnerAcceptance,
    Payout,
    Referral,
)
from partners.services import messages as messages_service
from partners.services import payouts, reporting
from partners.services.access_links import create_link
from partners.services.access_links import revoke as revoke_link
from partners.services.acceptance import accept_document, pending_document, places_left
from partners.services.contract import quarterly_status, release_slot
from partners.services.trial import grant_pro_trial


def _period(request) -> str:
    raw = request.GET.get("period") or request.POST.get("period") or ""
    try:
        payouts.parse_period(raw)
    except ValidationError:
        return reporting.current_period()
    return raw


def _message(exc: ValidationError) -> str:
    return " ".join(exc.messages)


def _back(partner: Partner, period: str):
    return redirect(f"{reverse('partners_detail', args=[partner.pk])}?period={period}")


@staff_member_required
@require_GET
def dashboard(request):
    return render(
        request,
        "partners/dashboard.html",
        {
            "stats": reporting.dashboard_stats(),
            "funnel": reporting.funnel(),
            "alerts": reporting.alerts(),
        },
    )


@staff_member_required
@require_GET
def partner_list(request):
    return render(request, "partners/list.html", {"rows": reporting.partner_rows()})


@staff_member_required
@require_GET
def partner_detail(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    period = _period(request)
    referrals = list(
        Referral.objects.filter(partner=partner)
        .select_related("seller__user")
        .order_by("-attributed_at")
    )
    entries = list(
        CommissionEntry.objects.filter(referral__partner=partner)
        .select_related("referral__seller", "payment", "payout")
        .order_by("-created_at")[:100]
    )
    return render(
        request,
        "partners/detail.html",
        {
            "partner": partner,
            "period": period,
            "referrals": referrals,
            "entries": entries,
            "payouts": list(Payout.objects.filter(partner=partner)),
            "quarterly": quarterly_status(partner),
            "carried_over": payouts.carried_over(partner, period),
            "statement": payouts.statement_text(partner, period),
            "acceptances": list(partner.acceptances.all()),
            "links": list(partner.access_links.all()[:20]),
            "pending_doc": (
                legal_docs.DOCS[d]["label"] if (d := pending_document(partner)) else ""
            ),
            "doc_choices": [(k, v["label"]) for k, v in legal_docs.DOCS.items()],
        },
    )


@staff_member_required
@require_POST
def release(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    try:
        release_slot(partner, actor=request.user)
        messages.success(request, "La place du partenaire est libérée.")
    except ValidationError as exc:
        messages.error(request, _message(exc))
    return _back(partner, _period(request))


@staff_member_required
@require_POST
def validate(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    period = _period(request)
    count = payouts.validate_month(partner, period, actor=request.user)
    messages.success(request, f"{count} commission(s) validée(s) pour {period}.")
    return _back(partner, period)


@staff_member_required
@require_POST
def build_payout(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    period = _period(request)
    try:
        payout = payouts.build_payout(partner, period)
    except ValidationError as exc:
        messages.error(request, _message(exc))
    else:
        if payout is None:
            messages.info(
                request,
                "Aucun versement : le cumul est inférieur au minimum, il est reporté au mois suivant.",
            )
        else:
            messages.success(request, f"Versement de {payouts.fmt(payout.total_fcfa)} FCFA préparé.")
    return _back(partner, period)


@staff_member_required
@require_POST
def mark_paid(request, pk: int):
    payout = get_object_or_404(Payout.objects.select_related("partner"), pk=pk)
    try:
        payouts.mark_paid(payout, request.POST.get("reference", ""), actor=request.user)
        messages.success(request, "Versement marqué comme payé.")
    except ValidationError as exc:
        messages.error(request, _message(exc))
    return _back(payout.partner, payout.period)


def _csv_response(content: str, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@staff_member_required
@require_GET
def csv_partner(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    try:
        return _csv_response(*payouts.partner_csv(partner, request.GET.get("period", "")))
    except ValidationError as exc:
        return HttpResponseBadRequest(_message(exc))


@staff_member_required
@require_GET
def csv_internal(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    try:
        return _csv_response(*payouts.internal_csv(partner, request.GET.get("period", "")))
    except ValidationError as exc:
        return HttpResponseBadRequest(_message(exc))


# ── Contacter un partenaire (WhatsApp prérempli) ──────────────────────────────

@staff_member_required
@require_http_methods(["GET", "POST"])
def contact(request):
    from core.countries import COUNTRIES, DEFAULT_COUNTRY

    prefill_partner = Partner.objects.filter(pk=request.GET.get("partner") or 0).first()
    key = request.POST.get("template_key") or request.GET.get("template") or "invitation_essai"
    if key not in messages_service.TEMPLATES:
        key = "invitation_essai"
    initial = {
        "country": DEFAULT_COUNTRY.calling_code,
        "phone_national": "",
        "first_name": "",
        "shop_name": "",
        "message": messages_service.TEMPLATES[key],
    }
    if prefill_partner is not None:
        initial["first_name"] = prefill_partner.name
        initial["shop_name"] = prefill_partner.shop_name
        for country in sorted(COUNTRIES, key=lambda c: -len(c.calling_code)):
            if prefill_partner.phone.startswith(country.dial):
                initial["country"] = country.calling_code
                initial["phone_national"] = prefill_partner.phone[len(country.dial):]
                break
    result = error = None
    if request.method == "POST":
        initial.update(
            country=request.POST.get("country", ""),
            phone_national=request.POST.get("phone_national", ""),
            first_name=request.POST.get("first_name", ""),
            shop_name=request.POST.get("shop_name", ""),
            message=request.POST.get("message", ""),
        )
        preview = request.POST.get("action") == "preview"
        try:
            result = messages_service.prepare(
                staff=request.user,
                country=initial["country"],
                national=initial["phone_national"],
                first_name=initial["first_name"],
                shop_name=initial["shop_name"],
                template_key=key,
                text=initial["message"],
                link_builder=lambda token: messages_service.partner_page_url(request, token),
                preview=preview,
            )
        except ValidationError as exc:
            error = _message(exc)
        else:
            result.preview = preview
    return render(
        request,
        "partners/contact.html",
        {
            "countries": COUNTRIES,
            "templates": [(k, messages_service.LABELS[k]) for k in messages_service.TEMPLATES],
            "template_key": key,
            "form": initial,
            "result": result,
            "error": error,
            "max_length": messages_service.MAX_LENGTH,
            "prefill_partner": prefill_partner,
        },
    )


@staff_member_required
@require_GET
def message_list(request):
    return render(
        request,
        "partners/messages.html",
        {"messages_list": OutboundMessage.objects.select_related("partner", "created_by")[:200]},
    )


@staff_member_required
@require_GET
def message_detail(request, pk: int):
    message = get_object_or_404(OutboundMessage.objects.select_related("partner", "created_by"), pk=pk)
    return render(request, "partners/message_detail.html", {"message": message})


# ── Documents : acceptations, liens privés, acceptation écrite ────────────────

def _acceptance_filters(request):
    from partners.models import AcceptanceDocType, AcceptanceMethod, PartnerAcceptance

    qs = PartnerAcceptance.objects.select_related("partner").order_by("-accepted_at")
    doc_type = request.GET.get("doc_type", "")
    if doc_type in AcceptanceDocType.values:
        qs = qs.filter(doc_type=doc_type)
    version = request.GET.get("version", "")
    if version and len(version) <= 10:
        qs = qs.filter(doc_version=version)
    method = request.GET.get("method", "")
    if method in AcceptanceMethod.values:
        qs = qs.filter(method=method)
    return qs, {"doc_type": doc_type, "version": version, "method": method}


@staff_member_required
@require_GET
def documents(request):
    from partners.models import AcceptanceDocType, AcceptanceMethod, PartnerAcceptance

    qs, filters = _acceptance_filters(request)
    pending = []
    for partner in Partner.objects.exclude(status__in=["ended", "slot_released"]).order_by("name"):
        doc_type = pending_document(partner)
        if doc_type:
            partner.pending_doc = legal_docs.DOCS[doc_type]["label"]
            pending.append(partner)
    return render(
        request,
        "partners/documents.html",
        {
            "acceptances": list(qs[:500]),
            "pending": pending,
            "filters": filters,
            "doc_types": AcceptanceDocType.choices,
            "methods": AcceptanceMethod.choices,
            "versions": sorted(set(PartnerAcceptance.objects.values_list("doc_version", flat=True))),
        },
    )


@staff_member_required
@require_GET
def document_detail(request, pk: int):
    from partners.models import PartnerAcceptance

    acceptance = get_object_or_404(PartnerAcceptance.objects.select_related("partner"), pk=pk)
    return render(request, "partners/document_detail.html", {"acceptance": acceptance})


@staff_member_required
@require_GET
def documents_csv(request):
    qs, _ = _acceptance_filters(request)
    header = [
        "Partenaire", "Document", "Version", "Date", "Nom saisi", "Méthode",
        "Référence de l'acceptation écrite", "Empreinte IP", "Empreinte du texte",
    ]
    rows = [
        [
            a.partner.name,
            a.get_doc_type_display(),
            a.doc_version,
            timezone.localtime(a.accepted_at).strftime("%d/%m/%Y %H:%M"),
            a.signer_name,
            a.get_method_display(),
            a.manual_reference,
            a.ip_hash,
            a.text_sha256,
        ]
        for a in qs[:5000]
    ]
    return _csv_response(payouts._csv(header, rows), "hayaflash-interne-documents.csv")


@staff_member_required
@require_GET
def brief(request):
    return render(
        request,
        "partners/brief.html",
        {"brief_html": legal_docs.render_brief(places=places_left()), "status": legal_docs.BRIEF_STATUS},
    )


@staff_member_required
@require_POST
def link_create(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    _, token = create_link(partner, "view")
    audit("partner.link_created", entity_type="Partner", entity_id=partner.pk, actor=request.user, purpose="view")
    url = request.build_absolute_uri(reverse("partner_doc_page", args=[token]))
    response = render(request, "partners/link_created.html", {"partner": partner, "url": url})
    response["Cache-Control"] = "no-store, private"
    return response


@staff_member_required
@require_POST
def link_revoke(request, pk: int):
    link = get_object_or_404(PartnerAccessLink.objects.select_related("partner"), pk=pk)
    revoke_link(link)
    audit("partner.link_revoked", entity_type="Partner", entity_id=link.partner_id, actor=request.user)
    messages.success(request, "Lien révoqué.")
    return _back(link.partner, _period(request))


@staff_member_required
@require_POST
def written_acceptance(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    back = _back(partner, _period(request))
    try:
        day = datetime.strptime(request.POST.get("accepted_on", ""), "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Date invalide : utilisez le format AAAA-MM-JJ.")
        return back
    if day > timezone.localdate():
        messages.error(request, "La date d'acceptation ne peut pas être dans le futur.")
        return back
    doc_type = request.POST.get("doc_type", "")
    if doc_type not in legal_docs.DOCS:
        messages.error(request, "Choisissez un document.")
        return back
    try:
        _, created = accept_document(
            partner,
            doc_type,
            signer_name=partner.name,
            method="written_manual",
            manual_reference=request.POST.get("reference", ""),
            accepted_at=timezone.make_aware(datetime.combine(day, time(12, 0))),
        )
    except ValidationError as exc:
        messages.error(request, _message(exc))
        return back
    if created:
        messages.success(request, "Acceptation écrite enregistrée.")
    else:
        messages.info(request, "Cette version du document est déjà acceptée.")
    return back


@staff_member_required
@require_POST
def offer_pro(request, pk: int):
    partner = get_object_or_404(Partner, pk=pk)
    try:
        sub = grant_pro_trial(partner, request.user)
    except ValidationError as exc:
        messages.error(request, _message(exc))
    else:
        messages.success(
            request, f"Plan Pro offert jusqu'au {timezone.localtime(sub.expires_at):%d/%m/%Y}."
        )
    return _back(partner, _period(request))


@staff_member_required
@require_POST
def document_invalidate(request, pk: int):
    acceptance = get_object_or_404(PartnerAcceptance, pk=pk)
    reason = (request.POST.get("reason") or "").strip()
    back = redirect("partners_document_detail", pk=acceptance.pk)
    if not reason:
        messages.error(request, "Indiquez le motif (interne) de l'invalidation.")
        return back
    if AcceptanceInvalidation.objects.filter(acceptance=acceptance).exists():
        messages.error(request, "Cette acceptation est déjà invalidée.")
        return back
    AcceptanceInvalidation.objects.create(acceptance=acceptance, reason=reason, invalidated_by=request.user)
    audit(
        "partner.document_invalidated",
        entity_type="Partner",
        entity_id=acceptance.partner_id,
        actor=request.user,
        acceptance_id=acceptance.pk,
    )
    messages.success(request, "Acceptation invalidée. Rien n'a été supprimé.")
    return back
