"""QR codes du programme partenaires (bibliothèque ``qrcode``), générés à la volée.

Un seul réglage pour tous les QR : correction d'erreur M, marge de 4 modules, noir sur blanc.
Utilisé par la vérification publique (``verification.qr_svg``) et par le QR du lien de
recommandation (``/r/<code>/``) téléchargeable depuis la fiche partenaire. Rien n'est stocké.
"""

from __future__ import annotations

import io
import math
import re

import qrcode
import qrcode.image.svg
from django.urls import reverse

from partners.models import Partner, PartnerPhase, PartnerStatus

BORDER_MODULES = 4  # marge blanche minimale imposée par la norme
MIN_PNG_SIDE = 1000  # pixels
SVG_SIDE = 1000  # pixels, à l'ouverture du fichier SVG (il reste redimensionnable)


def make_qr(url: str) -> qrcode.QRCode:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=BORDER_MODULES
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr


def referral_url(request, partner: Partner) -> str:
    """URL absolue du lien de recommandation : le domaine vient de la requête (hôte validé par
    ALLOWED_HOSTS), le chemin ne contient que le code."""
    return request.build_absolute_uri(reverse("partner_referral_link", args=[partner.code]))


def png_bytes(url: str) -> bytes:
    """PNG noir sur blanc d'au moins 1000 px de côté (modules de taille entière)."""
    qr = make_qr(url)
    modules = len(qr.get_matrix())
    qr.box_size = math.ceil(MIN_PNG_SIDE / modules)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def svg_document(url: str) -> str:
    """Fichier SVG autonome : fond blanc explicite, marge incluse, taille 1000 px par défaut."""
    svg = make_qr(url).make_image(image_factory=qrcode.image.svg.SvgPathImage).to_string(encoding="unicode")
    svg = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg)
    root = re.match(r"<svg[^>]*>", svg).group(0)
    side = re.search(r'viewBox="0 0 (\d+) \d+"', root).group(1)
    sized = re.sub(r'\s(?:width|height)="[^"]*"', "", root).replace(
        "<svg", f'<svg width="{SVG_SIDE}" height="{SVG_SIDE}"', 1
    )
    background = f'<rect x="0" y="0" width="{side}" height="{side}" fill="#fff"/>'
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + sized + background + svg[len(root):]


def file_name(partner: Partner, fmt: str) -> str:
    """``hayaflash-<code>.png|svg`` : le code seul, jamais de nom ni de téléphone."""
    return f"hayaflash-{partner.code}.{fmt}"


def unavailable_reason(partner: Partner) -> str:
    """Message clair si le lien du partenaire ne peut pas être diffusé, sinon chaîne vide.

    Même règle que l'attribution (``accepts_new_referrals``) : un QR vers un lien qui
    n'attribuerait plus personne ne doit pas être affiché en live."""
    if partner.accepts_new_referrals:
        return ""
    if partner.status == PartnerStatus.PAUSED:
        return "Ce partenaire est en pause : son lien ne reçoit plus d'inscriptions, le QR n'est pas disponible."
    if partner.status == PartnerStatus.SLOT_RELEASED:
        return "La place de ce partenaire est libérée : son lien est fermé, le QR n'est pas disponible."
    if partner.status == PartnerStatus.ENDED:
        return "Ce partenaire est terminé : son lien est fermé, le QR n'est pas disponible."
    if partner.status == PartnerStatus.ACTIVE and partner.phase in (PartnerPhase.CONTRACT, PartnerPhase.TRIAL):
        return "Le contrat ou l'essai de ce partenaire est expiré : son lien est fermé, le QR n'est pas disponible."
    return "Ce partenaire n'a pas encore de contrat ni d'essai en cours : le QR sera disponible à ce moment-là."
