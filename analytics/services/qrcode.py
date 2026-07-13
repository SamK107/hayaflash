from __future__ import annotations

import base64
from io import BytesIO

import qrcode
from qrcode.image.pure import PyPNGImage

from analytics.services.share_links import flash_sale_public_path, get_public_base_url


def generate_flash_sale_qr_b64(flash_sale, request=None) -> str:
    """
    Génère un QR Code pour l'URL publique d'une vente flash.
    Retourne l'image encodée en base64 (PNG) pour affichage direct via data URI.
    """
    path = flash_sale_public_path(flash_sale.public_slug)
    base_url = get_public_base_url(request)
    url = f"{base_url}{path}"

    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PyPNGImage)

    buffer = BytesIO()
    img.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode()
