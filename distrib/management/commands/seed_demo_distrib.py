"""Donnees de DEMONSTRATION du module Distrib, pour les captures d'une presentation commerciale.

    python manage.py seed_demo_distrib --settings=config.settings.dev [--reset]

Garde-fous :
- refuse de tourner hors developpement local (DEBUG faux, environnement staging/prod, base distante) ;
- ne modifie aucun code, modele ni migration : tout passe par les services existants
  (create_order, advance_delivery, import_product, confirm_paid, releves, versements...) ;
- toutes les donnees demo se reconnaissent a leurs numeros fictifs +223 70 00 00 xx ;
  `--reset` ne supprime que ce qui appartient a ces comptes.

Les dates sont relatives a « maintenant » ; la commande est a relancer (avec --reset) avant chaque
session de captures pour que la vente « en cours » le soit vraiment.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from accounts.models import SellerProfile
from core.choices import SaleCategory
from delivery.models import Delivery
from delivery.services.delivery import advance_delivery, apply_order_action
from distrib.models import (
    AllocationMovement,
    DistribCorrection,
    DistribPayment,
    DistribSettlement,
    DistribStatement,
    Distributor,
    ImportedProduct,
    ResellerInvite,
    ResellerPayout,
    WholesaleProduct,
    WholesaleProductImage,
)
from distrib.services import catalog, ceilings, distributors, invites, statements
from distrib.services import settlement as settlement_service
from distrib.services.allocation import import_product
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, UnhonoredOrder
from orders.services.create_order import create_order
from products.models import FlashSaleProduct, Product, ProductMedia, StockMovement
from products.services.crud import add_product_image, attach_product_to_sale, create_product
from subscriptions.models import Plan, Subscription

DEMO_PASSWORD = "DemoHaya2026!"
DEMO_PHONE_REGEX = r"^\+223700000\d{2}$"  # +223 70 00 00 xx : plage reservee a la demo
DEMO_PHONE_RE = re.compile(DEMO_PHONE_REGEX)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
CATEGORIES = ("habits", "chaussures", "sacs", "parfums")
# Les categories de ventes de la plateforme (SaleCategory) n'ont ni « sacs » ni « parfums » ni « habits » :
# on les range sous la categorie la plus proche. Le decoupage demo reste celui des dossiers d'images.
SALE_CATEGORY = {
    "habits": SaleCategory.MODE,
    "chaussures": SaleCategory.CHAUSSURES,
    "sacs": SaleCategory.MODE,
    "parfums": SaleCategory.BEAUTE,
}
PRICE_RANGE = {"habits": (5000, 20000), "chaussures": (6000, 18000), "sacs": (7000, 25000), "parfums": (4000, 15000)}
# Prix de gros (FCFA) par nom de fichier ; les parfums « cristal or », « ambre coffret noir » et les sacs a main
# en cuir sont en haut de fourchette. Un fichier absent de cette table recoit un prix de repli de sa categorie.
WHOLESALE_PRICES = {
    "abaya-brodee": 12000, "boubou-bazin-brode": 20000, "chemise-lin-homme": 5500,
    "ensemble-tailleur-femme": 17000, "robe-wax-cintree": 8500,
    "baskets-bleu-marine": 9000, "escarpins-bordeaux": 11000, "escarpins-dores": 14000,
    "escarpins-moutarde-chainette": 12500, "mocassins-cuir-homme": 18000,
    "sac-a-main-cuir-camel": 24000, "sac-a-main-cuir-creme": 22000, "sac-a-main-cuir-noir": 25000,
    "sac-bandouliere-beige-cognac": 12000, "sac-trapeze-taupe": 9500,
    "eau-de-parfum-rose": 4500, "parfum-ambre-coffret-noir": 14000, "parfum-cristal-or": 15000,
    "parfum-flacon-noir-or": 8000, "parfum-oriental-ambre": 6500,
}
MARKET_PRICES = {  # (prix catalogue, prix promo) des boutiques hors Distrib
    "creoles-dorees": (6000, 4500), "parure-bijoux-doree": (15000, 11500),
    "montre-doree-chronographe": (25000, 19000), "lunettes-soleil-noir-or": (9000, 6500),
    "ecouteurs-sans-fil": (14000, 10000),
}
_ACCENT_PHRASES = [("sac a main", "sac à main"), ("lunettes soleil", "lunettes de soleil")]
_ACCENT_WORDS = {
    "brodee": "brodée", "brode": "brodé", "cintree": "cintrée", "dores": "dorés", "dorees": "dorées",
    "doree": "dorée", "bandouliere": "bandoulière", "trapeze": "trapèze", "creoles": "créoles",
    "chainette": "chaînette", "ecouteurs": "écouteurs", "creme": "crème",
}
DESCRIPTIONS = {
    "habits": "Pièce soignée, tissu de qualité, coupe flatteuse. Plusieurs tailles disponibles.",
    "chaussures": "Finitions soignées, confortable toute la journée. Plusieurs pointures disponibles.",
    "sacs": "Sac solide aux belles finitions, doublure intérieure et poches pratiques.",
    "parfums": "Fragrance longue tenue, présentée dans un joli flacon. Idéal en cadeau.",
}

# ── Revendeuses (numeros 11 a 15) ─────────────────────────────────────────
# `products` : (categorie, nombre de produits). `ventes` : codes des commandes (voir STATES).
RESELLERS = [
    {
        "key": "awa", "phone": "+22370000011", "person": "Awa Traoré", "shop": "Boutique Awa Style",
        "zone": "Hamdallaye ACI 2000, Bamako", "bio": "Boubous, abayas et tenues de cérémonie. Livraison dans tout Bamako.",
        "products": [("habits", 5)], "category": SaleCategory.MODE, "label": "habits",
        "sales": {"A": "P2 P1 P1 P1 P2 X P1", "B": "P1 P1 P1 F P1", "R": "P1 U1 U1 X", "live": "N N N C C D"},
        "live_title": "Boubous et abayas du week-end", "statement_b": "paid_accepted",
    },
    {
        "key": "fanta", "phone": "+22370000012", "person": "Fanta Keïta", "shop": "Fanta Chaussures",
        "zone": "Badalabougou, Bamako", "bio": "Escarpins, mocassins et sacs en cuir. Retrait ou livraison.",
        "products": [("chaussures", 5), ("sacs", 5)], "category": SaleCategory.CHAUSSURES, "label": "chaussures + sacs",
        "sales": {"A": "P1 P2 P1 P1", "B": "P1 P1 F P1", "live": "N N C X"},
        "live_title": "Escarpins et sacs en cuir", "statement_b": "paid_declared",
    },
    {
        "key": "mariam", "phone": "+22370000013", "person": "Mariam Coulibaly", "shop": "Les Parfums de Mariam",
        "zone": "Kalaban Coura, Bamako", "bio": "Parfums et coffrets cadeaux. Idéal pour les fêtes.",
        "products": [("parfums", 5)], "category": SaleCategory.BEAUTE, "label": "parfums",
        "sales": {"A": "P1 P2 P1 P1", "B": "P1 P1"}, "scheduled": "Coffrets parfums de fin d'année",
        "statement_b": "to_pay",
    },
    {
        "key": "salimata", "phone": "+22370000014", "person": "Salimata Diarra", "shop": "Salimata Mode & Sacs",
        "zone": "Sikasso", "bio": "Tenues et sacs à main, expédition dans tout le Mali.",
        "products": [("habits", 4), ("sacs", 3)], "category": SaleCategory.MODE, "label": "habits + sacs",
        "sales": {"A": "P1 P1 P2 X", "B": "P1 P1", "R": "U1 D1"}, "statement_b": "to_pay",
    },
    {
        "key": "kadiatou", "phone": "+22370000015", "person": "Kadiatou Sangaré", "shop": "Kadiatou Chic",
        "zone": "Ségou", "bio": "Chaussures et parfums, nouveautés chaque semaine.",
        "products": [("chaussures", 4), ("parfums", 3)], "category": SaleCategory.CHAUSSURES, "label": "chaussures + parfums",
        "sales": {"A": "P1 P1 P2", "B": "P1 P1 F P1", "live": "N N C"},
        "live_title": "Escarpins et parfums", "statement_b": "paid_declared",
    },
]
SALE_TITLES = {
    "A": "Vente flash {shop} - semaine passée", "B": "Vente flash {shop} - nouveautés",
    "R": "Vente flash {shop} - hier soir",
}
# Boutiques independantes (hors Distrib) : numeros 21 a 25.
MARKET_SHOPS = [
    {"phone": "+22370000021", "person": "Rama Doumbia", "shop": "Bijoux de Rama", "zone": "Bamako", "category": SaleCategory.MODE,
     "items": ["creoles-dorees", "parure-bijoux-doree"], "orders": "N N N C N N N", "title": "Bijoux dorés à prix flash"},
    {"phone": "+22370000022", "person": "Soumaïla Cissé", "shop": "Montres Soumaïla", "zone": "Bamako", "category": SaleCategory.MODE,
     "items": ["montre-doree-chronographe"], "orders": "N N C N N", "title": "Montres chronographes"},
    {"phone": "+22370000023", "person": "Nènè Diallo", "shop": "Lunettes Chic Bamako", "zone": "Bamako", "category": SaleCategory.MODE,
     "items": ["lunettes-soleil-noir-or"], "orders": "N N N N", "title": "Lunettes de soleil, derniers modèles"},
    {"phone": "+22370000024", "person": "Moussa Sylla", "shop": "Tech Moussa", "zone": "Bamako", "category": SaleCategory.ELECTRONIQUE,
     "items": ["ecouteurs-sans-fil"], "orders": "N C N N N N", "title": "Écouteurs sans fil"},
    {"phone": "+22370000025", "person": "Kadi Maïga", "shop": "Accessoires Kadi", "zone": "Ségou", "category": SaleCategory.MODE,
     "items": ["parure-bijoux-doree", "lunettes-soleil-noir-or", "montre-doree-chronographe"], "orders": "N N N", "title": "Accessoires du jour"},
]
FAILED_INDEX = {"awa": 0, "fanta": 1, "kadiatou": 2}
ADMIN = {"phone": "+22370000099", "person": "Admin Démo"}
DISTRIBUTOR = {"phone": "+22370000001", "person": "Seydou Maïga", "business": "Grossiste Démo Bamako"}
CUSTOMERS = [  # numeros 30 a 45 ; les trois derniers ne servent qu'aux livraisons echouees
    ("Aminata Coulibaly", "+22370000030"), ("Rokia Camara", "+22370000031"), ("Oumou Sidibé", "+22370000032"),
    ("Kadidia Traoré", "+22370000033"), ("Djénéba Doumbia", "+22370000034"), ("Assa Konaté", "+22370000035"),
    ("Bintou Dembélé", "+22370000036"), ("Hawa Samaké", "+22370000037"), ("Nana Diakité", "+22370000038"),
    ("Sira Touré", "+22370000039"), ("Maïmouna Cissé", "+22370000040"), ("Aïssata Bagayoko", "+22370000041"),
]
FAILED_CUSTOMERS = [
    ("Fatoumata Sanogo", "+22370000042"), ("Korotoumou Berthé", "+22370000043"), ("Safiatou Ouologuem", "+22370000044"),
]
ADDRESSES = [
    "Hamdallaye ACI 2000, près de la pharmacie", "Badalabougou, rue 123, porte 45", "Kalaban Coura, derrière le marché",
    "Sogoniko, face à la station", "Magnambougou, Projet, rue 220", "Lafiabougou, rue 301, porte 12",
    "Niamakoro, cité UNICEF", "Faladié, près de l'école", "Torokorobougou, rue 77", "Bamako Coura, près de la mosquée",
]
MARGINS = [1500, 2000, 2500, 1000, 3000]  # marge de revente (FCFA) par produit, entre 1 000 et 3 000
TARGET_COMMISSION_DUE = 6500  # encours de commission laisse a HayaFlash (plafond : 10 000)


def is_demo_phone(phone: str | None) -> bool:
    return bool(phone and DEMO_PHONE_RE.match(phone))


def product_name_from_stem(stem: str) -> str:
    """« sac-a-main-cuir-camel » -> « Sac à main cuir camel » (accents evidents retablis)."""
    text = stem.replace("-", " ").replace("_", " ").strip().lower()
    for old, new in _ACCENT_PHRASES:
        text = re.sub(rf"\b{old}\b", new, text)
    text = " ".join(_ACCENT_WORDS.get(word, word) for word in text.split())
    return text[:1].upper() + text[1:]


def demo_users():
    return get_user_model().objects.filter(phone__regex=DEMO_PHONE_REGEX)


class Command(BaseCommand):
    help = "Remplit la base LOCALE avec des donnees de demonstration du module Distrib (captures commerciales)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Supprime les donnees demo (et seulement elles), puis recree.")
        parser.add_argument("--assets-dir", default=None, help="Dossier des images (defaut : <projet>/demo_assets).")
        parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Prefixe des URL affichees.")

    # ── Point d'entree ────────────────────────────────────────────────────

    def handle(self, *args, **options):
        self.assert_local_dev()
        self.assets = Path(options["assets_dir"] or Path(settings.BASE_DIR) / "demo_assets")
        self.manifest_path = self.assets / "_manifest.json"
        self.base_url = options["base_url"].rstrip("/")

        if options["reset"]:
            self.reset()
        elif demo_users().exists():
            self.stdout.write(self.style.WARNING(
                "Les données démo existent déjà : rien n'a été modifié. Relancez avec --reset pour les recréer."
            ))
            self.print_report(self.load_manifest())
            return

        self.check_assets()
        self.rng = random.Random(20261104)
        self.seq = 0
        # Aucune notification (WhatsApp / SMS) vers les numeros fictifs, aucun Celery requis.
        with mock.patch("notifications.tasks.send_order_confirmation.delay", return_value=None):
            manifest = self.seed()
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.print_report(manifest)

    @staticmethod
    def assert_local_dev() -> None:
        if not settings.DEBUG:
            raise CommandError("Refusé : DEBUG est faux. Cette commande ne tourne qu'en développement local.")
        environment = str(getattr(settings, "ENVIRONMENT", "dev")).lower()
        if environment in ("staging", "prod", "production"):
            raise CommandError(f"Refusé : environnement « {environment} ». Cette commande ne tourne qu'en développement local.")
        db = connection.settings_dict
        host = str(db.get("HOST") or "").lower()
        if "sqlite3" not in str(db.get("ENGINE", "")) and host not in ("", "localhost", "127.0.0.1", "::1"):
            raise CommandError(f"Refusé : la base « {host} » n'est pas la base locale de développement.")

    # ── Images ────────────────────────────────────────────────────────────

    def check_assets(self) -> None:
        self.catalog_images: dict[str, list[Path]] = {}
        for category in CATEGORIES:
            folder = self.assets / "produits" / category
            files = sorted(p for p in folder.glob("*") if p.suffix.lower() in IMAGE_EXTENSIONS) if folder.is_dir() else []
            self.catalog_images[category] = files
            if len(files) < 5:
                self.stdout.write(self.style.WARNING(f"  images « {category} » : {len(files)} sur 5 (les images disponibles sont utilisées)"))
        folder = self.assets / "marche"
        self.market_images = {p.stem: p for p in sorted(folder.glob("*")) if p.suffix.lower() in IMAGE_EXTENSIONS} if folder.is_dir() else {}
        if len(self.market_images) < 5:
            self.stdout.write(self.style.WARNING(f"  images « marche » : {len(self.market_images)} sur 5 (les images disponibles sont utilisées)"))
        if not any(self.catalog_images.values()):
            raise CommandError(f"Aucune image de produit dans {self.assets / 'produits'}. Voir l'étape 0 (copie des images).")
        self._image_cache: dict[Path, bytes] = {}

    def image_file(self, path: Path) -> ContentFile:
        """JPEG reduit (1400 px) : sous la limite de 5 Mo des televersements, rapide a copier."""
        from PIL import Image

        if path not in self._image_cache:
            with Image.open(path) as source:
                image = source.convert("RGB")
                image.thumbnail((1400, 1400))
                buffer = BytesIO()
                image.save(buffer, "JPEG", quality=85)
            self._image_cache[path] = buffer.getvalue()
        return ContentFile(self._image_cache[path], name=f"{path.stem}.jpg")

    # ── Remise a zero (donnees demo seulement) ────────────────────────────

    def reset(self) -> None:
        users = demo_users()
        user_ids = list(users.values_list("pk", flat=True))
        if not user_ids:
            self.stdout.write("Aucune donnée démo à supprimer.")
            return
        sellers = SellerProfile.objects.filter(user_id__in=user_ids)
        with transaction.atomic():
            gros = Distributor.objects.filter(user_id__in=user_ids)
            DistribCorrection.objects.filter(settlement__distributor__in=gros).delete()
            DistribSettlement.objects.filter(distributor__in=gros).delete()
            ResellerPayout.objects.filter(distributor__in=gros).delete()
            DistribStatement.objects.filter(distributor__in=gros).delete()
            DistribPayment.objects.filter(distributor__in=gros).delete()
            AllocationMovement.objects.filter(imported_product__invite__distributor__in=gros).delete()
            ImportedProduct.objects.filter(invite__distributor__in=gros).delete()
            ResellerInvite.objects.filter(distributor__in=gros).delete()
            for image in WholesaleProductImage.objects.filter(wholesale_product__distributor__in=gros):
                self._drop_file(image.image)
            WholesaleProduct.objects.filter(distributor__in=gros).delete()
            gros.delete()

            orders = Order.service_objects.filter(flash_sale__owner__in=sellers)
            UnhonoredOrder.objects.filter(order__in=orders).delete()
            StockMovement.objects.filter(order__in=orders).delete()
            orders.delete()
            for media in ProductMedia.objects.filter(product__owner__in=sellers):
                self._drop_file(media.file)
            for sale in FlashSale.objects.filter(owner__in=sellers):
                self._drop_file(sale.cover_image)
            FlashSaleProduct.objects.filter(flash_sale__owner__in=sellers).delete()
            FlashSale.objects.filter(owner__in=sellers).delete()
            StockMovement.objects.filter(product__owner__in=sellers).delete()
            Product.objects.filter(owner__in=sellers).delete()
            Subscription.objects.filter(seller__in=sellers).delete()
            sellers.delete()
            users.delete()
        self.stdout.write(self.style.SUCCESS("Données démo supprimées."))

    @staticmethod
    def _drop_file(field) -> None:
        try:
            if field:
                field.delete(save=False)
        except Exception:  # un fichier deja absent ne bloque jamais la remise a zero
            pass

    # ── Creation ──────────────────────────────────────────────────────────

    def seed(self) -> dict:
        User = get_user_model()
        self.now = timezone.now()
        local_now = timezone.localtime(self.now)
        self.monday = timezone.make_aware(datetime.combine(local_now.date() - timedelta(days=local_now.weekday()), time.min))

        with transaction.atomic():
            self.admin = User.objects.create_superuser(phone=ADMIN["phone"], password=DEMO_PASSWORD, display_name=ADMIN["person"])
            self.create_distributor()
            self.create_catalog()
            self.create_resellers()
            self.create_sales_and_orders()
            self.create_market()
        # Les releves et versements s'appuient sur des verrous : hors du gros bloc, comme en vrai.
        self.close_statements_and_payouts()
        self.settle_commission()
        return self.build_manifest()

    def create_distributor(self) -> None:
        distributor, _password = distributors.create_distributor(
            phone=DISTRIBUTOR["phone"], display_name=DISTRIBUTOR["person"], business_name=DISTRIBUTOR["business"],
            created_by=self.admin, orange_money_number=DISTRIBUTOR["phone"],
        )
        distributor.user.set_password(DEMO_PASSWORD)
        distributor.user.save(update_fields=["password"])
        self.distributor = distributor
        self.dist_user = distributor.user

    def create_catalog(self) -> None:
        """20 produits de gros (5 par categorie), prix realistes, une photo chacun."""
        self.wholesale: dict[str, list[WholesaleProduct]] = {}
        for category in CATEGORIES:
            low, high = PRICE_RANGE[category]
            files = self.catalog_images[category]
            rows = []
            for index, path in enumerate(files):
                price = WHOLESALE_PRICES.get(path.stem) or int(round((low + (high - low) * (index + 1) / (len(files) + 1)) / 500) * 500)
                product = catalog.create_wholesale_product(
                    distributor=self.distributor, name=product_name_from_stem(path.stem),
                    wholesale_price=price, min_retail_price=price + 1000, stock_total=80,
                    description=DESCRIPTIONS[category], category=SALE_CATEGORY[category],
                )
                catalog.add_wholesale_image(wholesale_product=product, image_file=self.image_file(path))
                rows.append(product)
            self.wholesale[category] = rows
        # Memorise la categorie « demo » (habits / sacs / parfums...) que SaleCategory ne sait pas porter.
        self.demo_category = {wp.pk: category for category, rows in self.wholesale.items() for wp in rows}

    def create_resellers(self) -> None:
        User = get_user_model()
        self.resellers = []
        for r_index, spec in enumerate(RESELLERS):
            user = User.objects.create_user(phone=spec["phone"], password=DEMO_PASSWORD, display_name=spec["person"])
            seller = SellerProfile.objects.create(
                user=user, business_name=spec["shop"], bio=spec["bio"], delivery_zones=spec["zone"], category=spec["category"],
            )
            Subscription.objects.update_or_create(seller=seller, defaults={"plan": Plan.PRO, "expires_at": self.now + timedelta(days=90)})
            invite = invites.invite_reseller(distributor=self.distributor, display_name=spec["person"], phone=spec["phone"])
            invites.answer_invite(invite=invite, user=user, accept=True)
            invite.refresh_from_db()

            imported = []
            for c_index, (category, count) in enumerate(spec["products"]):
                for p_index, wp in enumerate(self.wholesale[category][:count]):
                    margin = MARGINS[(r_index + p_index + c_index) % len(MARGINS)]
                    quantity = 10 + (r_index * 3 + p_index * 2 + c_index) % 6  # 10 a 15
                    imported.append(import_product(
                        invite=invite, wholesale_product=wp, retail_price=int(wp.wholesale_price) + margin,
                        actor=self.dist_user, quantity=quantity,
                    ))
            self.resellers.append({"spec": spec, "user": user, "seller": seller, "invite": invite, "imported": imported, "sales": {}})

    # ── Ventes et commandes ───────────────────────────────────────────────

    def create_sales_and_orders(self) -> None:
        week = timedelta(days=7)
        a_start = self.monday - 2 * week + timedelta(days=2, hours=18)
        b_start = self.monday - week + timedelta(days=1, hours=17)
        r_start = self.now - timedelta(hours=30)
        self.customer_cycle = 0
        for entry in self.resellers:
            spec = entry["spec"]
            products = [i.product for i in entry["imported"]]
            for code, start in (("A", a_start), ("B", b_start), ("R", r_start)):
                if code in spec["sales"]:
                    sale = self.new_sale(entry, SALE_TITLES[code].format(shop=spec["shop"]), products)
                    entry["sales"][code] = sale
                    self.place_orders(entry, sale, products, spec["sales"][code], kind=code, start=start)
                    FlashSale.objects.filter(pk=sale.pk).update(
                        start_time=start, end_time=start + timedelta(hours=2), status=FlashSaleStatus.COMPLETED,
                    )
                    sale.refresh_from_db()
            if "live" in spec["sales"]:
                start = self.now - timedelta(minutes=50)
                sale = self.new_sale(entry, spec["live_title"], products)
                entry["sales"]["live"] = sale
                self.place_orders(entry, sale, products, spec["sales"]["live"], kind="live", start=start)
            if "scheduled" in spec:
                start = self.now + timedelta(hours=20)
                sale = FlashSale.objects.create(
                    owner=entry["seller"], title=spec["scheduled"], description="Ouverture demain : prépare-toi.",
                    start_time=start, end_time=start + timedelta(hours=2), status=FlashSaleStatus.SCHEDULED,
                    delivery_zone=spec["zone"], category=spec["category"],
                )
                self.attach_products(sale, products)
                entry["sales"]["scheduled"] = sale

    def new_sale(self, entry, title, products, *, owner=None, category=None, zone=None, cover=None, start=None) -> FlashSale:
        """Cree la vente DANS une fenetre ouverte (create_order refuse une vente fermee). Les ventes
        terminees sont ensuite replacees dans le passe par create_sales_and_orders."""
        seller = owner or entry["seller"]
        spec = entry["spec"]
        start = start or self.now - timedelta(minutes=50)
        sale = FlashSale.objects.create(
            owner=seller, title=title, description="Quantités limitées. Livraison à Bamako, paiement à la réception.",
            start_time=start, end_time=start + timedelta(hours=2), status=FlashSaleStatus.LIVE,
            delivery_zone=zone or spec.get("zone", ""), category=category or spec.get("category", ""),
            teasers=f"{max(len(products), 1)} modèles · livraison rapide · paiement à la réception",
        )
        if cover is not None:
            sale.cover_image.save(f"{sale.public_slug}.jpg", cover, save=True)
        elif products:
            first_media = ProductMedia.objects.filter(product=products[0]).order_by("order", "pk").first()
            if first_media:
                with first_media.file.open("rb") as fh:
                    sale.cover_image.save(f"{sale.public_slug}.jpg", ContentFile(fh.read()), save=True)
        self.attach_products(sale, products)
        return sale

    @staticmethod
    def attach_products(sale, products, promo=None) -> None:
        for index, product in enumerate(products):
            attach_product_to_sale(flash_sale=sale, product=product, promo_price=(promo or {}).get(product.pk), display_order=index)

    def next_customer(self) -> tuple[str, str]:
        customer = CUSTOMERS[self.customer_cycle % len(CUSTOMERS)]
        self.customer_cycle += 1
        return customer

    def place_orders(self, entry, sale, products, codes: str, *, kind: str, start) -> None:
        """Une commande par code : N nouvelle · C confirmee · D en livraison · U livree (boutique) ·
        P livree et payee · X annulee · F livraison echouee (non honoree). Le chiffre est la quantite."""
        owner_user = entry["user"] if entry else None
        tokens = codes.split()
        for index, token in enumerate(tokens):
            state, quantity = token[0], int(token[1:] or 1)
            product = products[(index + len(entry.get("log", []))) % len(products)]
            if state == "F":  # une cliente differente par boutique : aucun numero n'atteint le seuil de blocage
                customer = FAILED_CUSTOMERS[FAILED_INDEX[entry["spec"]["key"]]]
            else:
                customer = self.next_customer()
            self.seq += 1
            payload = {
                "flash_sale_id": sale.pk, "customer_name": customer[0], "customer_phone": customer[1],
                "client_request_id": f"demo-seed-{self.seq:04d}", "items": [{"product_id": product.pk, "quantity": quantity}],
                "delivery": {"address_text": ADDRESSES[self.seq % len(ADDRESSES)], "geo_method": "manual"},
            }
            order = create_order(payload)
            if kind == "live":
                created = min(start + timedelta(minutes=3 + index * 5), self.now - timedelta(minutes=1))
            else:
                created = start + timedelta(minutes=8 + index * 9)
            self.advance_and_date(entry, order, owner_user, state, created, kind)
            entry.setdefault("log", []).append({"order": order.pk, "state": state})

    def advance_and_date(self, entry, order, owner_user, state, created, kind) -> None:
        """Fait avancer la commande avec les services de la vendeuse, puis la date dans le passe."""
        now = self.now
        cap = lambda moment: min(moment, now - timedelta(minutes=1))  # noqa: E731
        confirm_at = cap(created + (timedelta(minutes=8) if kind == "live" else timedelta(minutes=25)))
        start_at = cap(confirm_at + (timedelta(minutes=10) if kind == "live" else timedelta(minutes=90)))
        delivered_at = cap(start_at + timedelta(minutes=80))
        last = created

        if state == "X":
            apply_order_action(user=owner_user, order_id=order.pk, action="cancel")
            last = cap(created + timedelta(minutes=30))
        elif state in "CDUPF":
            apply_order_action(user=owner_user, order_id=order.pk, action="confirm")
            last = confirm_at
            if state in "DUPF":
                delivery = Delivery.objects.get(order=order)
                advance_delivery(user=owner_user, delivery_id=delivery.pk, action="start_delivery", payload={"assigned_to": "Moussa, livreur"})
                last = start_at
                if state in "UP":
                    advance_delivery(user=owner_user, delivery_id=delivery.pk, action="mark_delivered", payload={"cod_collected": True})
                    last = delivered_at
                elif state == "F":
                    advance_delivery(user=owner_user, delivery_id=delivery.pk, action="mark_failed")
                    last = delivered_at

        Order.service_objects.filter(pk=order.pk).update(created_at=created, updated_at=last)
        Delivery.objects.filter(order_id=order.pk).update(
            scheduled_at=start_at if state in "DUPF" else None,
            delivered_at=delivered_at if state in "UP" else None,
            cod_collected_at=delivered_at if state in "UP" else None,
        )
        UnhonoredOrder.objects.filter(order_id=order.pk).update(created_at=delivered_at)

        # Suivi Distrib : cree/aligne par le service (le signal est coupe quand DISTRIB_ENABLED l'est).
        settlement_service.sync_order(order.pk)
        for line in DistribSettlement.objects.filter(order_id=order.pk):
            fields = {"created_at": created}
            if line.confirmed_at is not None:
                fields["confirmed_at"] = confirm_at
                fields["auto_confirm_at"] = confirm_at + timedelta(hours=self.distributor.auto_confirm_hours)
            DistribSettlement.objects.filter(pk=line.pk).update(**fields)
            line.refresh_from_db()
            if state == "P":
                settlement_service.confirm_paid(
                    line, source=DistribSettlement.ConfirmationSource.DISTRIBUTOR, by=self.dist_user, at=self.paid_moment(kind, delivered_at),
                )
            elif state == "F":
                settlement_service.declare_not_delivered(
                    line, self.dist_user, reason=DistribSettlement.NotDeliveredReason.ABSENT, note="",
                )
                DistribSettlement.objects.filter(pk=line.pk).update(declared_at=delivered_at + timedelta(hours=1))
            if state == "D" and kind == "live" and "receipt_line" not in self.__dict__:
                self.receipt_line = line.pk

    def paid_moment(self, kind, delivered_at):
        """Moment de « Livré et payé » : toujours apres la livraison, jamais dans le futur. La vente
        d'hier soir est confirmee cette semaine, au milieu du temps ecoule depuis lundi 00:00."""
        if kind == "R":
            midpoint = self.monday + (self.now - self.monday) / 2
            return min(max(midpoint, delivered_at + timedelta(minutes=30)), self.now - timedelta(minutes=2))
        return min(delivered_at + timedelta(hours=self.rng.randint(3, 20)), self.now - timedelta(minutes=2))

    # ── Marche : boutiques hors Distrib ───────────────────────────────────

    def create_market(self) -> None:
        User = get_user_model()
        self.market = []
        for m_index, spec in enumerate(MARKET_SHOPS):
            items = [stem for stem in spec["items"] if stem in self.market_images] or list(self.market_images)[:1]
            if not items:
                continue
            user = User.objects.create_user(phone=spec["phone"], password=DEMO_PASSWORD, display_name=spec["person"])
            seller = SellerProfile.objects.create(
                user=user, business_name=spec["shop"], bio="Vente en ligne et livraison rapide.", delivery_zones=spec["zone"], category=spec["category"],
            )
            Subscription.objects.update_or_create(seller=seller, defaults={"plan": Plan.PRO, "expires_at": self.now + timedelta(days=90)})
            products, promo = [], {}
            for stem in items:
                price, promo_price = MARKET_PRICES.get(stem, (10000, 8000))
                product = create_product(owner=seller, name=product_name_from_stem(stem), price=price, stock=20,
                                         description="Qualité vérifiée, livraison rapide.")
                add_product_image(product=product, image_file=self.image_file(self.market_images[stem]))
                products.append(product)
                promo[product.pk] = promo_price
            entry = {"spec": spec, "user": user, "seller": seller, "sales": {}}
            start = self.now - timedelta(minutes=15 + m_index * 9)
            sale = self.new_sale(entry, spec["title"], [], start=start, owner=seller, category=spec["category"], zone=spec["zone"],
                                 cover=self.image_file(self.market_images[items[0]]))
            self.attach_products(sale, products, promo)
            entry["sales"]["live"] = sale
            self.place_orders(entry, sale, products, spec["orders"], kind="live", start=start)
            self.market.append(entry)

    # ── Releves, versements, commission ───────────────────────────────────

    def close_statements_and_payouts(self) -> None:
        """Cloture la semaine d'il y a 15 jours (payee et acceptee), puis la derniere (selon la revendeuse)."""
        statements.close_weekly_statements(now=self.now - timedelta(days=7))
        statements.close_weekly_statements(now=self.now)
        for entry in self.resellers:
            invite = entry["invite"]
            older_period = (self.monday - timedelta(days=14)).date()
            for statement in DistribStatement.objects.filter(invite=invite).order_by("period_start"):
                behaviour = "paid_accepted" if statement.period_start <= older_period else entry["spec"]["statement_b"]
                if behaviour == "to_pay":
                    continue
                payout = statements.declare_paid(statement, self.dist_user, f"DEMOOM{statement.pk:06d}{invite.pk}")
                if behaviour == "paid_accepted":
                    paid_at = statement.closed_at + timedelta(hours=5)
                    ResellerPayout.objects.filter(pk=payout.pk).update(paid_at=paid_at, contest_deadline=paid_at + statements.CONTEST_WINDOW)
                    payout.refresh_from_db()
                    statements.answer_payout(payout, entry["user"], accept=True)
                else:  # paye hier, en attente de la reponse de la revendeuse
                    paid_at = self.now - timedelta(hours=10)
                    ResellerPayout.objects.filter(pk=payout.pk).update(paid_at=paid_at, contest_deadline=paid_at + statements.CONTEST_WINDOW)

    def settle_commission(self) -> None:
        """Regle l'essentiel de la commission a HayaFlash : il ne reste qu'un encours inferieur au plafond."""
        outstanding = ceilings.commission_outstanding(self.distributor)
        if outstanding > TARGET_COMMISSION_DUE:
            amount = int((outstanding - TARGET_COMMISSION_DUE) // 100 * 100)
            DistribPayment.objects.create(
                distributor=self.distributor, amount=Decimal(amount), paid_at=self.now - timedelta(days=2),
                reference="DEMOOMHAYAFLASH", recorded_by=self.admin,
            )

    # ── Sortie : manifeste, rapport ───────────────────────────────────────

    def build_manifest(self) -> dict:
        awa = self.resellers[0]
        live = awa["sales"].get("live")
        statements_qs = DistribStatement.objects.filter(distributor=self.distributor)
        to_pay = statements_qs.filter(status=DistribStatement.Status.TO_PAY).order_by("-amount").first()
        accepted = statements_qs.filter(status=DistribStatement.Status.ACCEPTED).order_by("-amount").first()
        line = DistribSettlement.objects.filter(pk=getattr(self, "receipt_line", None)).select_related("order").first()
        customer = {"phone": line.order.customer_phone, "name": line.order.customer_name, "code": line.receipt_code} if line else None
        mobile, desktop = "mobile", "desktop"
        pages = [
            ("grossiste", desktop, "Tableau de bord grossiste (accueil)", "/distrib/"),
            ("grossiste", desktop, "Catalogue de gros", "/distrib/catalogue/"),
            ("grossiste", desktop, "Liste des revendeuses", "/distrib/revendeurs/"),
            ("grossiste", desktop, "Stock alloué", "/distrib/stock/"),
            ("grossiste", desktop, "Commandes (toutes)", "/distrib/commandes/"),
            ("grossiste", desktop, "Livraisons en cours", "/distrib/commandes/?statut=in_delivery"),
            ("grossiste", desktop, "Livrées et payées", "/distrib/commandes/?statut=paid_confirmed"),
            ("grossiste", desktop, "Pas livrées (non honorées)", "/distrib/commandes/?statut=not_delivered"),
            ("grossiste", desktop, "Relevés et versements de marges", "/distrib/releves/"),
        ]
        if to_pay:
            pages.append(("grossiste", desktop, "Relevé à régler (détail par livraison)", f"/distrib/releves/{to_pay.pk}/"))
        if accepted:
            pages.append(("grossiste", desktop, "Relevé payé et accepté (détail)", f"/distrib/releves/{accepted.pk}/"))
        pages += [
            ("revendeuse", mobile, "Page publique de la boutique", f"/s/{awa['seller'].public_slug}/"),
        ]
        if live:
            pages.append(("revendeuse", mobile, "Vente en cours : lien de partage et QR code", f"/seller/flash-sales/{live.pk}/"))
        pages += [
            ("revendeuse", mobile, "Tableau de bord revendeuse", "/seller/"),
            ("revendeuse", mobile, "Commandes (dashboard LIVE)", "/orders/seller/dashboard/"),
            ("revendeuse", mobile, "Livraisons", "/orders/seller/deliveries/"),
            ("revendeuse", mobile, "Mes grossistes", "/distrib/mes-grossistes/"),
            ("revendeuse", mobile, "Stock reçu du grossiste", f"/distrib/mes-grossistes/{awa['invite'].pk}/"),
            ("revendeuse", mobile, "Mes gains", "/distrib/mes-gains/"),
        ]
        if live:
            pages.append(("cliente", mobile, "Page de vente côté cliente", f"/f/{live.public_slug}/"))
        pages += [
            ("cliente", mobile, "Confirmation de réception (téléphone + code)", "/distrib/confirmer/"),
            ("marche", mobile, "Marché : ventes en direct", "/ventes/"),
        ]
        return {
            "base_url": self.base_url,
            "password": DEMO_PASSWORD,
            "accounts": [
                {"role": "grossiste", "name": DISTRIBUTOR["business"], "phone": DISTRIBUTOR["phone"]},
                *[{"role": "revendeuse", "key": e["spec"]["key"], "name": e["spec"]["shop"], "phone": e["spec"]["phone"], "categories": e["spec"]["label"]} for e in self.resellers],
                *[{"role": "marche", "name": m["spec"]["shop"], "phone": m["spec"]["phone"]} for m in self.market],
                {"role": "admin", "name": ADMIN["person"], "phone": ADMIN["phone"]},
            ],
            "customer": customer,
            "pages": [{"n": i + 1, "actor": a, "device": d, "label": label, "path": p} for i, (a, d, label, p) in enumerate(pages)],
        }

    def load_manifest(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        raise CommandError("Données démo présentes mais manifeste introuvable : relancez avec --reset.")

    def print_report(self, manifest: dict) -> None:
        out = self.stdout.write
        out(self.style.SUCCESS("\nDonnées démo prêtes."))
        out(f"\nIDENTIFIANTS (connexion par téléphone, mot de passe commun : {manifest['password']})")
        for account in manifest["accounts"]:
            extra = f"  [{account['categories']}]" if account.get("categories") else ""
            out(f"  {account['role']:<11} {account['phone']}   {account['name']}{extra}")
        if manifest.get("customer"):
            customer = manifest["customer"]
            out(f"\nCLIENTE DE LA CONFIRMATION : {customer['name']} · {customer['phone']} · code {customer['code']}")
        out(f"\nURL À CAPTURER (dans l'ordre de la présentation, serveur : {manifest['base_url']})")
        for page in manifest["pages"]:
            out(f"  {page['n']:02d}  [{page['actor']:<10} {page['device']:<7}] {page['label']}\n        {manifest['base_url']}{page['path']}")
        out("\nLancer le serveur AVEC le module Distrib activé :")
        out("  DISTRIB_ENABLED=true python manage.py runserver --settings=config.settings.dev")
