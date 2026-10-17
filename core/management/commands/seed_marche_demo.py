"""Donnees de demo pour montrer /ventes/ (Le Marche) : local ou staging.

    python manage.py seed_marche_demo            # cree la demo
    python manage.py seed_marche_demo --reset    # --clear puis creation (remet la demo « en direct »)
    python manage.py seed_marche_demo --clear    # supprime tout ce qu'elle a cree

Les heures sont relatives au lancement : les comptes a rebours vieillissent, il
suffit de relancer avec --reset.

Garde-fous : refuse si DEBUG=False, sauf si ``HAYAFLASH_ALLOW_DEMO_SEED=1`` ET
qu'aucun hote de production n'est dans ALLOWED_HOSTS. Tout est repere par le
prefixe de telephone vendeur ``DEMO_PHONE_PREFIX`` (comptes) et le prefixe client
``DEMO_CLIENT_PREFIX`` : --clear ne touche rien d'autre.

Boutiques : les categories « enfants » et « accessoires » n'existent pas dans
``SaleCategory`` : elles sont rattachees a « Mode » et « Beauté ».
"""

from __future__ import annotations

import csv
import math
import os
import random
import unicodedata
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.demo_data import ALLOW_ENV_VAR, DEMO_CLIENT_PREFIX, DEMO_PHONE_PREFIX

PRODUCTION_HOSTS = frozenset({"hayaflash.com", "www.hayaflash.com"})

# (nom, categorie, couleur d'avatar)
SHOPS = [
    ("Démo Awa Mode", "mode", "#E63946"),
    ("Démo Fanta Beauté", "beaute", "#C2410C"),
    ("Démo Moussa Tech", "electronique", "#2563EB"),
    ("Démo Saveurs du Mali", "alimentation", "#15803D"),
    ("Démo Souliers Kala", "chaussures", "#7C3AED"),
    ("Démo Petits Pas", "mode", "#0891B2"),            # enfants
    ("Démo Délices de Kayes", "alimentation", "#DB2777"),
    ("Démo Pieds Légers", "chaussures", "#B45309"),
]

# Photos de demo OPTIONNELLES : core/demo_assets/produits/catalogue.csv (absent par defaut :
# aucune photo tierce n'est versionnee, le seed genere ses images avec Pillow). Si present :
# chemin (relatif a ce dossier), categorie, nom affiche, prix FCFA entier ; les images ne sont
# jamais servies ni collectees, elles sont copiees dans media/ comme un upload normal.
DEMO_ASSETS_DIR = Path(__file__).resolve().parents[2] / "demo_assets" / "produits"
CATALOGUE_FILE = "catalogue.csv"

PRODUCTS = {
    "mode": [("Robe wax", 18000), ("Boubou brodé", 25000), ("Chemise bogolan", 12000), ("Pagne 6 yards", 9000), ("Ensemble femme", 22000)],
    "beaute": [("Beurre de karité", 3500), ("Huile de coco", 4000), ("Savon noir", 2500), ("Crème visage", 7500), ("Parfum 50 ml", 15000)],
    "electronique": [("Écouteurs sans fil", 12000), ("Chargeur rapide", 6500), ("Batterie externe", 14000), ("Enceinte Bluetooth", 18000), ("Câble USB-C", 2500)],
    "alimentation": [("Thé à la menthe", 2000), ("Miel local 500 g", 4500), ("Arachides grillées", 1500), ("Jus de bissap", 1000), ("Épices maison", 3000)],
    "maison": [("Set de casseroles", 28000), ("Natte tressée", 8000), ("Lampe solaire", 9500), ("Seau et bassine", 4000), ("Rideau wax", 11000)],
    "chaussures": [("Sandales cuir", 8500), ("Baskets légères", 16000), ("Babouches", 6000), ("Tongs", 2500), ("Mocassins", 19000)],
}
SALE_TITLES = {
    "mode": "Fin de série mode", "beaute": "Soins et beauté", "electronique": "Accessoires high-tech",
    "alimentation": "Saveurs du terroir", "maison": "Déco et cuisine", "chaussures": "Chaussures de saison",
}
QUARTIERS = ["ACI 2000", "Hamdallaye", "Badalabougou", "Lafiabougou", "Magnambougou", "Niamakoro", "Sogoniko", "Kalaban Coura"]
CLIENT_NAMES = ["Awa", "Fatoumata", "Mariam", "Oumou", "Aïssata", "Kadiatou", "Ibrahim", "Moussa", "Seydou", "Bakary"]

# Ventes en direct : (boutique, fin dans N min, duree min, % vendu cible, nb produits)
LIVE_SALES = [(0, 4, 120, 85, 4), (4, 12, 105, 62, 5), (3, 45, 90, 38, 3), (2, 100, 120, 21, 4)]
# Terminees recemment : (boutique, finie il y a N min, duree min)
ENDED_SALES = [(7, 10, 120), (6, 50, 90), (5, 100, 100)]
# Poids des commandes par heure (0 = derniere heure) : pics et creux.
HOUR_WEIGHTS = [9, 5, 2, 1.5, 6, 3]
HISTORY_HOURS = (6, 4)  # vente historique de chaque boutique : de -6 h a -4 h


def load_catalogue(directory: Path | None = None) -> tuple[list[dict], list[str]]:
    """Lit ``catalogue.csv`` : ``(lignes valides, avertissements)``.

    Ligne ignoree (avec avertissement) si la categorie n'est pas une valeur de
    ``SaleCategory``, si le prix n'est pas un entier > 0, si l'image est absente
    ou hors du dossier. Fichier absent : liste vide (le seed utilise alors les
    images generees avec Pillow).
    """
    from core.choices import SaleCategory

    directory = Path(directory or DEMO_ASSETS_DIR)
    csv_path = directory / CATALOGUE_FILE
    if not csv_path.is_file():
        return [], []
    valid_categories = {value for value, _label in SaleCategory.choices}
    rows, warnings = [], []
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            try:
                path = (directory / row["chemin"].strip()).resolve()
                category = row["categorie"].strip()
                name = row["nom"].strip()
                price = int(row["prix"].strip())
            except (KeyError, AttributeError, ValueError):
                warnings.append(f"catalogue.csv ligne {line_no} : ligne illisible, ignoree.")
                continue
            if category not in valid_categories:
                warnings.append(f"catalogue.csv ligne {line_no} : categorie inconnue « {category} », ignoree.")
            elif price <= 0 or not name:
                warnings.append(f"catalogue.csv ligne {line_no} : nom ou prix invalide, ignoree.")
            elif directory.resolve() not in path.parents or not path.is_file():
                warnings.append(f"catalogue.csv ligne {line_no} : image introuvable, ignoree.")
            else:
                rows.append({"path": path, "category": category, "name": name, "price": price})
    return rows, warnings


class Command(BaseCommand):
    help = "Cree (ou supprime avec --clear / --reset) des donnees de demo pour /ventes/."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--clear", action="store_true", help="Supprime les donnees de demo.")
        parser.add_argument("--reset", action="store_true", help="--clear puis creation.")

    def handle(self, *args, **options) -> None:
        self._check_allowed()
        if options["clear"] and options["reset"]:
            raise CommandError("Choisis --clear ou --reset, pas les deux.")
        if options["clear"]:
            self._clear()
            return
        if options["reset"]:
            self._clear()
        self._create()

    # ── Garde-fous ────────────────────────────────────────────────────
    @staticmethod
    def _production_host_present() -> bool:
        for host in settings.ALLOWED_HOSTS:
            h = host.strip().lower()
            if h == "*" or h.lstrip(".") in PRODUCTION_HOSTS:
                return True
        return False

    def _check_allowed(self) -> None:
        if settings.DEBUG:
            return
        if os.environ.get(ALLOW_ENV_VAR) != "1":
            raise CommandError(
                "seed_marche_demo refuse de tourner avec DEBUG=False. "
                f"Sur un staging : définis {ALLOW_ENV_VAR}=1."
            )
        if self._production_host_present():
            raise CommandError(
                "seed_marche_demo refuse de tourner : ALLOWED_HOSTS contient un hôte de production "
                "(hayaflash.com, www.hayaflash.com, .hayaflash.com ou *)."
            )

    # ── Suppression ───────────────────────────────────────────────────
    def _clear(self) -> None:
        from accounts.models import SellerProfile
        from flash_sales.models import FlashSale
        from orders.models import Order
        from core.services.thumbnails import delete_thumbnails
        from products.models import Product, ProductMedia

        User = get_user_model()
        users = User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX)
        sellers = SellerProfile.objects.filter(user__in=users)
        with transaction.atomic():
            # Ordre impose par les FK PROTECT : commandes (livraisons et lignes
            # en cascade) -> ventes -> produits -> boutiques -> comptes.
            Order.service_objects.filter(flash_sale__owner__in=sellers).delete()
            FlashSale.objects.filter(owner__in=sellers).delete()
            for media in ProductMedia.objects.filter(product__owner__in=sellers):
                if media.file:
                    delete_thumbnails(media.file)
                    media.file.delete(save=False)
            Product.objects.filter(owner__in=sellers).delete()
            for seller in sellers:
                if seller.avatar:
                    seller.avatar.delete(save=False)
            sellers.delete()
            deleted = users.delete()[0]
        self.stdout.write(self.style.SUCCESS(f"Démo supprimée ({deleted} objets, comptes inclus)."))

    # ── Creation ──────────────────────────────────────────────────────
    @staticmethod
    def _product_image(name: str, index: int) -> ContentFile:
        """JPEG 600x450 : fond colore, forme propre au produit, nom du produit (sans reseau)."""
        from PIL import Image, ImageDraw, ImageFont

        palette = ["#E63946", "#2563EB", "#15803D", "#7C3AED", "#C2410C", "#0891B2", "#DB2777", "#B45309"]
        bg = palette[index % len(palette)]
        accent = palette[(index + 3) % len(palette)]
        img = Image.new("RGB", (600, 450), bg)
        draw = ImageDraw.Draw(img)
        shape = index % 5
        light = "#FFFFFF"
        if shape == 0:
            draw.ellipse((170, 50, 430, 310), fill=accent, outline=light, width=6)
        elif shape == 1:
            draw.rounded_rectangle((150, 60, 450, 300), radius=40, fill=accent, outline=light, width=6)
        elif shape == 2:
            draw.polygon([(300, 40), (460, 310), (140, 310)], fill=accent, outline=light)
        elif shape == 3:
            draw.polygon([(300, 40), (450, 175), (300, 310), (150, 175)], fill=accent, outline=light)
        else:
            for k in range(5):
                draw.rectangle((120 + k * 70, 70, 160 + k * 70, 300), fill=accent if k % 2 else light)
        font = ImageFont.load_default(size=40)
        # La police integree de Pillow n'a pas les accents : on les retire (image seulement).
        name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        words, lines, line = name.split(), [], ""
        for w in words:
            trial = (line + " " + w).strip()
            if draw.textlength(trial, font=font) > 520 and line:
                lines.append(line)
                line = w
            else:
                line = trial
        lines.append(line)
        y = 335
        for text in lines[:2]:
            width = draw.textlength(text, font=font)
            draw.text(((600 - width) / 2, y), text, fill=light, font=font)
            y += 48
        buf = BytesIO()
        img.save(buf, "JPEG", quality=85)
        return ContentFile(buf.getvalue())

    @staticmethod
    def _avatar(name: str, color: str) -> ContentFile:
        """PNG carre : couleur unie + initiales (aucun telechargement)."""
        from PIL import Image, ImageDraw, ImageFont

        words = name.replace("Démo ", "").split()
        initials = "".join(w[0] for w in words[:2]).upper()
        img = Image.new("RGB", (256, 256), color)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=110)
        box = draw.textbbox((0, 0), initials, font=font)
        draw.text(
            ((256 - (box[2] - box[0])) / 2 - box[0], (256 - (box[3] - box[1])) / 2 - box[1]),
            initials, fill="#FFFFFF", font=font,
        )
        buf = BytesIO()
        img.save(buf, "PNG")
        return ContentFile(buf.getvalue())

    def _create(self) -> None:
        from accounts.models import SellerProfile
        from delivery.models import Delivery
        from flash_sales.market_stats import compute_market_stats
        from flash_sales.models import FlashSale, FlashSaleStatus
        from orders.models import Order, OrderItem, OrderStatus
        from products.models import FlashSaleProduct, Product, ProductMedia

        User = get_user_model()
        if User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists():
            raise CommandError("La démo existe déjà : relance avec --reset (ou --clear).")

        rng = random.Random(20261017)  # deterministe : meme demo a chaque lancement
        now = timezone.now()
        local_now = timezone.localtime(now)
        minute = timedelta(minutes=1)
        hour = timedelta(hours=1)

        stats = {"sales": 0, "orders": 0}
        # (vente, [(produit, capacite)], debut, fin, quantite a vendre)
        plans: list[tuple] = []

        with transaction.atomic():
            sellers = []
            for i, (name, category, color) in enumerate(SHOPS):
                user = User.objects.create_user(
                    phone=f"{DEMO_PHONE_PREFIX}{i + 1:03d}", password=None, display_name=name
                )
                seller = SellerProfile(user=user, business_name=name, category=category)
                seller.avatar.save(f"demo-{i + 1}.png", self._avatar(name, color), save=False)
                seller.save()
                sellers.append(seller)

            catalogue, catalogue_warnings = load_catalogue()
            photo_pool: dict[str, list[dict]] = {}
            for entry in catalogue:
                photo_pool.setdefault(entry["category"], []).append(entry)
            shops_per_category: dict[str, int] = {}
            for _name, category, _color in SHOPS:
                shops_per_category[category] = shops_per_category.get(category, 0) + 1
            # Une vente ne prend qu'une part des photos de sa categorie (reparties
            # entre les boutiques et les ventes) ; le reste est complete par Pillow.
            photo_cap = {
                cat: math.ceil(len(photos) / shops_per_category.get(cat, 1))
                for cat, photos in photo_pool.items()
            }
            stats["photos"] = 0

            def pick_products(category: str, n_products: int) -> list[dict]:
                pool = photo_pool.get(category, [])
                chosen = [pool.pop(0) for _ in range(min(n_products, photo_cap.get(category, 0), len(pool)))]
                taken = {c["name"] for c in chosen}
                fallback = [(name, price) for name, price in PRODUCTS[category] if name not in taken]
                for name, price in rng.sample(fallback, n_products - len(chosen)):
                    chosen.append({"path": None, "category": category, "name": name, "price": price})
                return chosen

            def make_sale(shop, title, start, end, status, n_products, pct=None, sold_range=(0, 0)):
                seller = sellers[shop]
                sale = FlashSale.objects.create(
                    owner=seller, title=title, start_time=start, end_time=end, status=status,
                    delivery_zone="Bamako",
                )
                linked = []
                for display_order, entry in enumerate(pick_products(SHOPS[shop][1], n_products)):
                    cap = rng.randint(12, 30)
                    product = Product.objects.create(
                        owner=seller, name=entry["name"], price=Decimal(entry["price"]),
                        stock_initial=cap, stock_available=cap,
                    )
                    FlashSaleProduct.objects.create(
                        flash_sale=sale, product=product, display_order=display_order
                    )
                    media = ProductMedia(
                        product=product, media_type=ProductMedia.MediaType.IMAGE, order=0,
                        alt_text=entry["name"],
                    )
                    if entry["path"] is not None:
                        # Copie dans media/ comme un upload (redimensionnement 1600 px dans save()).
                        media.file.save(
                            f"demo-{entry['path'].stem}-{product.pk}{entry['path'].suffix}",
                            ContentFile(entry["path"].read_bytes()), save=False,
                        )
                        stats["photos"] += 1
                    else:
                        media.file.save(
                            f"demo-{product.pk}.jpg", self._product_image(entry["name"], product.pk), save=False
                        )
                    media.save()
                    linked.append((product, cap))
                total = sum(c for _, c in linked)
                target = round(total * pct / 100) if pct is not None else round(total * rng.uniform(*sold_range))
                plans.append((sale, linked, start, end, target))
                stats["sales"] += 1

            for shop, ends_in, duration, pct, n_products in LIVE_SALES:
                end = now + ends_in * minute
                make_sale(
                    shop, SALE_TITLES[SHOPS[shop][1]], end - duration * minute, end,
                    FlashSaleStatus.LIVE, n_products, pct=pct,
                )
            for shop, ended_ago, duration in ENDED_SALES:
                end = now - ended_ago * minute
                make_sale(
                    shop, f"{SALE_TITLES[SHOPS[shop][1]]} — terminée", end - duration * minute, end,
                    FlashSaleStatus.COMPLETED, 3, sold_range=(0.7, 1.0),
                )
            # A venir : dans 20 min, « ce soir », demain (sans commandes).
            tonight = local_now.replace(hour=20, minute=0, second=0, microsecond=0)
            if tonight < now + 2 * hour:
                tonight = now + 2 * hour + 15 * minute
            tomorrow = (local_now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
            for shop, start in ((1, now + 20 * minute), (6, tonight), (7, tomorrow)):
                make_sale(
                    shop, f"{SALE_TITLES[SHOPS[shop][1]]} — à venir", start, start + 90 * minute,
                    FlashSaleStatus.SCHEDULED, 4,
                )

            # Historique (invisible : fini depuis plus de 2 h) : porte les commandes anciennes.
            for shop in range(len(SHOPS)):
                make_sale(
                    shop, f"{SALE_TITLES[SHOPS[shop][1]]} (hier soir)",
                    now - HISTORY_HOURS[0] * hour, now - HISTORY_HOURS[1] * hour,
                    FlashSaleStatus.COMPLETED, 3, sold_range=(0.6, 0.9),
                )

            # ── Commandes : quantites planifiees par vente, horodatees dans sa fenetre ──
            seq = 0

            def draw_time(start, end):
                lo, hi = max(start, now - 6 * hour), min(end, now)
                buckets, weights = [], []
                for b in range(6):
                    b_lo, b_hi = max(lo, now - (b + 1) * hour), min(hi, now - b * hour)
                    if b_hi > b_lo:
                        buckets.append((b_lo, b_hi))
                        weights.append(HOUR_WEIGHTS[b] * (b_hi - b_lo).total_seconds() / 3600)
                if not buckets:
                    return None
                b_lo, b_hi = rng.choices(buckets, weights=weights)[0]
                return b_lo + (b_hi - b_lo) * rng.random()

            def pick_status(age: timedelta) -> str:
                r = rng.random()
                if age < 15 * minute:
                    return OrderStatus.PENDING if r < 0.7 else OrderStatus.CONFIRMED
                if age < hour:
                    if r < 0.45:
                        return OrderStatus.CONFIRMED
                    return OrderStatus.OUT_FOR_DELIVERY if r < 0.85 else OrderStatus.DELIVERED
                return OrderStatus.OUT_FOR_DELIVERY if r < 0.06 else OrderStatus.DELIVERED

            def make_order(sale, product, qty, created, status):
                nonlocal seq
                seq += 1
                total = product.price * qty
                order = Order.service_objects.create(
                    flash_sale=sale, customer_name=f"{rng.choice(CLIENT_NAMES)} (démo)",
                    customer_phone=f"{DEMO_CLIENT_PREFIX}{seq:04d}", status=status,
                    client_request_id=f"demo-marche-{seq}", total_amount=total,
                )
                Order.service_objects.filter(pk=order.pk).update(created_at=created, updated_at=created)
                OrderItem.objects.create(
                    order=order, product=product, product_name_snapshot=product.name,
                    price_snapshot=product.price, quantity=qty,
                )
                d_status = {
                    OrderStatus.OUT_FOR_DELIVERY: Delivery.Status.IN_TRANSIT,
                    OrderStatus.DELIVERED: Delivery.Status.DELIVERED,
                }.get(status, Delivery.Status.PENDING)
                delivery = Delivery.objects.create(
                    order=order, address_text=f"{rng.choice(QUARTIERS)}, Bamako",
                    cod_amount=total, status=d_status,
                )
                if d_status == Delivery.Status.IN_TRANSIT:
                    delivery.assigned_to = "Livreur démo"
                    delivery.scheduled_at = min(now, created + 10 * minute)
                elif d_status == Delivery.Status.DELIVERED:
                    delivered_at = min(now, created + rng.randint(30, 90) * minute)
                    delivery.delivered_at = delivered_at
                    delivery.cod_collected = True
                    delivery.cod_collected_at = delivered_at
                delivery.save()
                stats["orders"] += 1

            for sale, linked, start, end, target in plans:
                remaining = {p.pk: cap for p, cap in linked}
                sold = {p.pk: 0 for p, _ in linked}
                n_valid = 0
                while target > 0 and any(v > 0 for v in remaining.values()):
                    created = draw_time(start, end)
                    if created is None:
                        break
                    product = rng.choice([p for p, _ in linked if remaining[p.pk] > 0])
                    qty = min(rng.choice([1, 1, 2, 3]), target, remaining[product.pk])
                    make_order(sale, product, qty, created, pick_status(now - created))
                    remaining[product.pk] -= qty
                    sold[product.pk] += qty
                    target -= qty
                    n_valid += 1
                # Quelques annulees : le stock reste intact (comme dans l'application).
                for _ in range(max(1, round(n_valid * 0.04)) if n_valid else 0):
                    created = draw_time(start, end)
                    if created is not None:
                        make_order(sale, linked[0][0], 1, created, OrderStatus.CANCELLED)
                for product, cap in linked:
                    Product.objects.filter(pk=product.pk).update(stock_available=cap - sold[product.pk])

        for warning in catalogue_warnings:
            self.stdout.write(self.style.WARNING(warning))
        indices = compute_market_stats(now)
        masked = [k for k in ("orders_last_hour", "deliveries_in_transit", "sparkline", "top_categories") if not indices[k]]
        self.stdout.write(self.style.SUCCESS(
            f"Démo créée : {len(SHOPS)} boutiques, {stats['sales']} ventes "
            f"({len(LIVE_SALES)} en direct, 3 à venir, {len(ENDED_SALES)} terminées récemment, "
            f"{len(SHOPS)} historiques), {stats['orders']} commandes, {stats['photos']} produits avec une vraie photo. "
            "Supprime tout avec : python manage.py seed_marche_demo --clear"
        ))
        if masked:
            self.stdout.write(self.style.WARNING(
                "Indices encore masqués (normal juste après minuit) : " + ", ".join(masked)
            ))
