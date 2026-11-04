"""Captures d'ecran automatiques de la demo Distrib (presentation commerciale grossistes).

A lancer APRES `python manage.py seed_demo_distrib --reset` et serveur local demarre AVEC Distrib :

    DISTRIB_ENABLED=true python manage.py runserver --settings=config.settings.dev
    python scripts/demo_captures.py

Hors du code applicatif : ce script ne touche ni la base ni le code, il ne fait que naviguer.
Il lit le manifeste ecrit par le seed (demo_assets/_manifest.json : comptes, URL, ordre).
  - pages grossiste : ordinateur 1440x900, device_scale_factor=2 ;
  - pages revendeuse, cliente et Marche : iPhone 13 ;
  - page entiere quand elle est longue, apres chargement complet (images comprises) ;
  - sortie : demo_captures/NN-<acteur>-<page>.png.

Prerequis : pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 2.5, "locale": "fr-FR"}
# Decoupage pour un diaporama : une image = un « ecran » lisible. Au-dela, on garde les premiers ecrans.
DESKTOP_SEGMENT_PX, MOBILE_SEGMENT_PX = 640, 844   # hauteur d'un ecran, en pixels CSS
MAX_SEGMENTS = 3
MERGE_RATIO = 1.3          # une page jusqu'a 1,3 ecran reste en une seule image
LOAD_TIMEOUT_MS = 30_000
ALL_IMAGES_LOADED = """() => Array.from(document.images).every((img) => {
    const src = img.getAttribute('src') || '';
    if (!src || src.endsWith('base64,')) return true;  // image remplie plus tard (ex. QR code a la demande)
    return img.complete && img.naturalWidth > 0;
})"""
SCROLL_TO_END = """async () => {
    const step = Math.max(400, window.innerHeight - 100);
    for (let y = 0; y < document.body.scrollHeight; y += step) {
        window.scrollTo(0, y);
        await new Promise((resolve) => setTimeout(resolve, 120));
    }
    window.scrollTo(0, 0);
}"""


HIDE_BOTTOM_SHEETS = """() => {
    // Les panneaux fixes en bas d'ecran (« Etre alerte(e) en premier »...) se retrouvent au milieu d'une capture
    // pleine page. On ne masque que ceux collés au bas de l'ecran, pas les fenetres plein ecran (QR code).
    for (const el of document.querySelectorAll('body *')) {
        const style = getComputedStyle(el);
        if (style.position !== 'fixed' || style.visibility === 'hidden' || style.display === 'none') continue;
        const r = el.getBoundingClientRect();
        if (r.height > 60 && r.top > 0 && r.bottom >= window.innerHeight - 2) el.style.visibility = 'hidden';
    }
}"""


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def server_is_up(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/health/", timeout=8) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except Exception:
        return False


class Shooter:
    def __init__(self, playwright, manifest: dict, base_url: str, out_dir: Path):
        self.manifest = manifest
        self.base_url = base_url
        self.out_dir = out_dir
        self.counter = 0
        self.done: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.browser = playwright.chromium.launch()
        mobile = dict(playwright.devices["iPhone 13"])
        mobile.pop("default_browser_type", None)  # l'appareil est emule dans Chromium
        self.mobile = {**mobile, "locale": "fr-FR", "viewport": {"width": 390, "height": 844}}
        self.contexts: dict[tuple[str, str], object] = {}

    # ── Contextes et connexion ────────────────────────────────────────────

    def context(self, actor: str, device: str):
        key = (actor, device)
        if key not in self.contexts:
            options = DESKTOP if device == "desktop" else self.mobile
            context = self.browser.new_context(service_workers="block", **options)
            context.set_default_timeout(LOAD_TIMEOUT_MS)
            self.contexts[key] = context
            if actor in ("grossiste", "revendeuse"):
                self.login(context, actor)
        return self.contexts[key]

    def phone_for(self, actor: str) -> str:
        wanted = "grossiste" if actor == "grossiste" else "revendeuse"
        return next(a["phone"] for a in self.manifest["accounts"] if a["role"] == wanted)

    def login(self, context, actor: str) -> None:
        page = context.new_page()
        page.goto(f"{self.base_url}/login/", wait_until="load")
        page.fill('input[name="phone"]', self.phone_for(actor))
        page.fill('input[name="password"]', self.manifest["password"])
        with page.expect_navigation():
            page.locator('form button[type="submit"], form input[type="submit"]').first.click()
        if "/login" in page.url:
            raise RuntimeError(f"connexion refusee pour « {actor} »")
        page.close()

    # ── Capture ───────────────────────────────────────────────────────────

    def settle(self, page) -> None:
        """Attend la fin du chargement, y compris les images (dont celles a chargement differe)."""
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass  # rafraichissements HTMX / compte a rebours : le reseau n'est jamais vraiment au repos
        page.evaluate(SCROLL_TO_END)
        page.wait_for_function(ALL_IMAGES_LOADED, timeout=LOAD_TIMEOUT_MS)
        page.evaluate("document.fonts && document.fonts.ready")
        page.wait_for_timeout(500)

    def shoot(self, page, actor: str, label: str, *, desktop: bool = False, viewport_only: bool = False) -> list[str]:
        """Une ou plusieurs images (jusqu'a 3 « ecrans »). Ordinateur : on recadre sur la colonne de contenu
        (l'application est une colonne de 768 px, le reste serait du vide) et on omet l'en-tete vendeur.
        Mobile : largeur de l'ecran exactement (un element trop large ne doit pas deborder sur la capture)."""
        page.evaluate(HIDE_BOTTOM_SHEETS)
        self.counter += 1
        stem = f"{self.counter:02d}-{actor}-{slugify(label)}"
        if viewport_only:
            name = f"{stem}.png"
            page.screenshot(path=str(self.out_dir / name))
            self.done.append(name)
            return [name]
        box = page.evaluate(
            """(desktop) => {
                const sx = window.scrollX, sy = window.scrollY;
                const col = desktop ? document.querySelector('main > div') : null;
                const r = col ? col.getBoundingClientRect() : null;
                return {x: r ? r.left + sx : 0, y: r ? r.top + sy : 0,
                        w: r ? r.width : window.innerWidth,
                        h: r ? r.height : document.documentElement.scrollHeight};
            }""",
            desktop,
        )
        seg = DESKTOP_SEGMENT_PX if desktop else MOBILE_SEGMENT_PX
        height = box["h"]
        if height <= seg * MERGE_RATIO:
            parts = [(0, height)]
        else:
            count = min(MAX_SEGMENTS, -(-int(height) // seg))
            parts = [(i * seg, min(seg, height - i * seg)) for i in range(count)]
        names = []
        for index, (offset, part_height) in enumerate(parts, start=1):
            suffix = f"-{index}sur{len(parts)}" if len(parts) > 1 else ""
            name = f"{stem}{suffix}.png"
            page.screenshot(
                path=str(self.out_dir / name), full_page=True,
                clip={"x": box["x"], "y": box["y"] + offset, "width": box["w"], "height": part_height},
            )
            self.done.append(name)
            names.append(name)
        return names

    def capture(self, entry: dict) -> None:
        actor, label, path = entry["actor"], entry["label"], entry["path"]
        context = self.context(actor, entry["device"])
        page = context.new_page()
        try:
            response = page.goto(f"{self.base_url}{path}", wait_until="load")
            if response is not None and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")
            self.settle(page)
            self.shoot(page, actor, label, desktop=entry["device"] == "desktop")
            if path == "/distrib/confirmer/":
                self.capture_receipt_confirmation(page, actor)
            elif re.fullmatch(r"/seller/flash-sales/\d+/", path):
                self.capture_qr_modal(page, actor)
        except Exception as exc:  # une page en echec n'arrete jamais les suivantes
            self.failed.append((f"{actor} · {label} ({path})", str(exc).splitlines()[0][:160]))
        finally:
            page.close()

    def capture_qr_modal(self, page, actor: str) -> None:
        """Le QR code s'affiche dans une fenetre apres un clic sur « QR Code »."""
        try:
            page.get_by_role("button", name=re.compile("QR Code")).first.click()
            page.wait_for_function(
                "() => { const i = document.querySelector('img[alt=\"QR Code vente flash\"]');"
                " return i && i.complete && i.naturalWidth > 0; }",
                timeout=LOAD_TIMEOUT_MS,
            )
            page.wait_for_timeout(500)
            self.shoot(page, actor, "qr code de la vente", viewport_only=True)
        except Exception as exc:
            self.failed.append((f"{actor} · QR code de la vente", str(exc).splitlines()[0][:160]))

    def capture_receipt_confirmation(self, page, actor: str) -> None:
        """La cliente saisit son telephone et son code : page « J'ai recu ma commande » (sans valider)."""
        customer = self.manifest.get("customer")
        if not customer:
            return
        try:
            local_phone = customer["phone"].removeprefix("+223")
            page.fill('input[name="phone"]', local_phone)
            page.fill('input[name="code"]', customer["code"])
            with page.expect_navigation():
                page.locator('form button[type="submit"]').first.click()
            self.settle(page)
            self.shoot(page, actor, "confirmation de reception")
        except Exception as exc:
            self.failed.append((f"{actor} · confirmation de reception (saisie telephone + code)", str(exc).splitlines()[0][:160]))

    def close(self) -> None:
        for context in self.contexts.values():
            context.close()
        self.browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=str(ROOT / "demo_assets" / "_manifest.json"))
    parser.add_argument("--out", default=str(ROOT / "demo_captures"))
    parser.add_argument("--base-url", default=None, help="Defaut : celui du manifeste (http://127.0.0.1:8000).")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Manifeste introuvable ({manifest_path}). Lancez d'abord : python manage.py seed_demo_distrib --reset")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_url = (args.base_url or manifest["base_url"]).rstrip("/")
    if not server_is_up(base_url):
        print(f"Serveur injoignable sur {base_url}. Lancez : DISTRIB_ENABLED=true python manage.py runserver --settings=config.settings.dev")
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("[0-9][0-9]-*.png"):  # anciennes captures : on repart d'un dossier propre
        old.unlink()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        shooter = Shooter(playwright, manifest, base_url, out_dir)
        try:
            for entry in manifest["pages"]:
                shooter.capture(entry)
        finally:
            shooter.close()

    print(f"\n{len(shooter.done)} capture(s) produite(s) dans {out_dir}")
    for name in shooter.done:
        print(f"  OK   {name}")
    for label, reason in shooter.failed:
        print(f"  ECHEC {label} : {reason}")
    print(f"{len(shooter.failed)} échec(s).")
    return 1 if shooter.failed else 0


if __name__ == "__main__":
    sys.exit(main())
