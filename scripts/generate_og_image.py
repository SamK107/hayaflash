"""Genere l'image de partage par defaut (Open Graph / Twitter), 1200x630.

    python scripts/generate_og_image.py [chemin/police-grasse.ttf]

Utilisee par base.html (bloc og_meta) pour les pages sans image specifique :
home, /ventes/, pages legales, et en image par defaut de /f/<slug>/ et /s/<slug>/.

Design : fond anthracite #1A1A2E (comme le hero de la home), logo
static/img/brand/logo-dark.png, accroche de la home en blanc + rouge flash
#FF4D2E, bandeau « Ventes flash · Mali » en lime #F9F871.

Pillow ne lit ni le SVG ni le .woff2 vendorises : il faut une police TTF/OTF
grasse, passee en argument ou trouvee parmi les polices systeme ci-dessous.
Aucune police n'est telechargee.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "static" / "img" / "brand" / "logo-dark.png"
OUT = ROOT / "static" / "img" / "og-default.png"

W, H = 1200, 630
BG = (26, 26, 46)  # #1A1A2E
WHITE = (255, 255, 255)
FLASH = (255, 77, 46)  # #FF4D2E
LIME = (249, 248, 113)  # #F9F871

FONT_CANDIDATES = [
    "C:/Windows/Fonts/seguibl.ttf",  # Segoe UI Black
    "C:/Windows/Fonts/ariblk.ttf",  # Arial Black
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _find_font(argv: list[str]) -> str:
    candidates = argv[1:2] + FONT_CANDIDATES
    for path in candidates:
        if Path(path).is_file():
            return path
    sys.exit("Aucune police TTF/OTF grasse trouvee : passez-en une en argument.")


def _centered(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> None:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    draw.text(((W - (right - left)) / 2 - left, y), text, font=font, fill=fill)


def main(argv: list[str]) -> None:
    font_path = _find_font(argv)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    logo = Image.open(LOGO).convert("RGBA")
    logo_w = 760
    logo = logo.resize((logo_w, round(logo.height * logo_w / logo.width)), Image.LANCZOS)
    img.paste(logo, ((W - logo_w) // 2, 90), logo)

    title = ImageFont.truetype(font_path, 64)
    small = ImageFont.truetype(font_path, 26)
    _centered(draw, 330, "Programmez. Vendez.", title, WHITE)
    _centered(draw, 410, "Haya s'occupe du reste.", title, FLASH)
    _centered(draw, 535, "VENTES FLASH · MALI", small, LIME)

    # Palette reduite : PNG net et leger (< 150 Ko), aplats de couleur.
    img.quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(OUT, optimize=True)
    print(f"{OUT} ({OUT.stat().st_size // 1024} Ko, police {font_path})")


if __name__ == "__main__":
    main(sys.argv)
