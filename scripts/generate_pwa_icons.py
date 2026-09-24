"""Genere les icones PWA acheteur et vendeur, nettes jusqu'a 1024 px.

    python scripts/generate_pwa_icons.py

Pourquoi 1024 px : sur Android 12+, l'ecran de demarrage affiche l'icone maskable
a ~240 dp, soit 700-850 px sur un telephone recent. Avec seulement 512 px, Android
l'agrandissait -> rendu flou. Eclair = trace vectoriel de static/img/brand/bolt.svg,
rendu en sur-echantillonnage x4 (bords lisses).

Design (valide le 24/09, "option A nette") : identique a l'existant.
- Acheteur : degrade diagonal #FF792E -> #FF4D2E, eclair blanc.
- Vendeur  : fond bleu nuit #1A1A2E, eclair en degrade du logo (#FFC24A -> #FF8A2B -> #FF4D2E).
Eclair un peu plus present dans l'icone maskable (44 % de la hauteur au lieu de ~39 %).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
BOLT = [(38, 4), (12, 36), (29, 36), (24, 60), (52, 26), (35, 26)]  # viewBox 64x64, hauteur 56
SS = 4  # sur-echantillonnage

BUYER_BG = ((255, 121, 46), (255, 77, 46))  # degrade diagonal du fond
SELLER_BG = (26, 26, 46)  # #1A1A2E
# Degrade de l'eclair du logo (bolt.svg : objectBoundingBox (0,0) -> (0.35,1))
LOGO_STOPS = [(0.0, (255, 194, 74)), (0.55, (255, 138, 43)), (1.0, (255, 77, 46))]

MASKABLE_BOLT = 0.44
ANY_BOLT = 0.48
APPLE_BOLT = 0.47
ANY_RADIUS = 0.22


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _stops(t: float):
    for (t0, c0), (t1, c1) in zip(LOGO_STOPS, LOGO_STOPS[1:]):
        if t <= t1:
            return _lerp(c0, c1, (t - t0) / (t1 - t0))
    return LOGO_STOPS[-1][1]


def _small_then_big(big: int, color_at) -> Image.Image:
    # Degrade calcule sur une petite image puis agrandi (rapide, sans artefact visible).
    n = 256
    small = Image.new("RGB", (n, n))
    px = small.load()
    for y in range(n):
        for x in range(n):
            px[x, y] = color_at(x / (n - 1), y / (n - 1))
    return small.resize((big, big), Image.BICUBIC)


def _background(big: int, app: str) -> Image.Image:
    if app == "buyer":
        return _small_then_big(big, lambda u, v: _lerp(*BUYER_BG, (u + v) / 2))
    return Image.new("RGB", (big, big), SELLER_BG)


def _bolt_points(big: int, ratio: float):
    k = ratio * big / 56
    return [(big / 2 + (x - 32) * k, big / 2 + (y - 32) * k) for x, y in BOLT]


def _draw_bolt(img: Image.Image, big: int, ratio: float, app: str) -> None:
    pts = _bolt_points(big, ratio)
    if app == "buyer":
        ImageDraw.Draw(img).polygon(pts, fill=(255, 255, 255))
        return
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    # Projection sur le vecteur (0.35, 1) en coordonnees de la boite de l'eclair.
    grad = _small_then_big(
        big, lambda u, v: _stops(max(0.0, min(1.0, (u * 0.35 + v) / (0.35 ** 2 + 1))))
    ).resize((max(1, round(w)), max(1, round(h))), Image.BICUBIC)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    layer = Image.new("RGB", img.size)
    layer.paste(grad, (round(x0), round(y0)))
    img.paste(layer, (0, 0), mask)


def maskable(size: int, app: str, ratio: float = MASKABLE_BOLT) -> Image.Image:
    """Carre plein (Android le decoupe : rond, squircle...)."""
    big = size * SS
    img = _background(big, app)
    _draw_bolt(img, big, ratio, app)
    return img.resize((size, size), Image.LANCZOS)


def any_icon(size: int, app: str) -> Image.Image:
    """Carre a coins arrondis sur fond transparent (ordinateur, navigateurs)."""
    big = size * SS
    img = _background(big, app)
    _draw_bolt(img, big, ANY_BOLT, app)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=round(ANY_RADIUS * big), fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out.resize((size, size), Image.LANCZOS)


# Noms de fichiers historiques (references par les manifests / templates).
FILES = {
    "buyer": {"any": "icon-buyer-{s}.png", "maskable": "icon-buyer-maskable-{s}.png", "apple": "apple-touch-icon-buyer.png"},
    "seller": {"any": "icon-{s}.png", "maskable": "icon-seller-maskable-{s}.png", "apple": "apple-touch-icon.png"},
}


def main() -> None:
    for app, names in FILES.items():
        for size in (192, 512, 1024):
            maskable(size, app).save(IMG / names["maskable"].format(s=size), optimize=True)
            any_icon(size, app).save(IMG / names["any"].format(s=size), optimize=True)
        # iOS : icone pleine (iOS arrondit lui-meme les coins)
        maskable(180, app, ratio=APPLE_BOLT).save(IMG / names["apple"], optimize=True)
    print("Icones acheteur + vendeur generees dans", IMG)


if __name__ == "__main__":
    main()
