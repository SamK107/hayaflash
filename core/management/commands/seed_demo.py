"""
Management command : seed_demo
==============================
Cree (ou remet a zero) les comptes de demonstration HayaFlash.

Architecture reelle
-------------------
  SellerProfile  --(owner)-->  FlashSale  --(flash_sale)-->  Product
  FlashSale      --(orders)-->  Order     --(items)-->        OrderItem

Usage
-----
    python manage.py seed_demo                   # cree si absent, skip si present
    python manage.py seed_demo --reset           # supprime et recree
    python manage.py seed_demo --shop habit      # une seule boutique

Comptes
-------
    +22371111111 / Rama123@  -> ALPHA CHAUSSURES     (FREE)
    +22372222222 / Rama123@  -> LES PLATS DU JOUR    (MEDIUM)
    +22379999999 / Rama123@  -> MONTRE HOMME & FEMME (PRO)
    +22300000004 / Rama123@  -> LUXES & ELEGANCES    (PRO)
"""

from __future__ import annotations

import random
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()

# ---------------------------------------------------------------------------
# Configuration boutiques
# Les produits sont definis au niveau de la boutique et seront crees
# pour chaque vente flash (chaque FlashSale possede sa propre liste de produits).
# ---------------------------------------------------------------------------

SHOPS = {
    "chaussures": {
        "phone": "+22371111111",
        "password": "Rama123@",
        "display_name": "Alpha Chaussures",
        "business_name": "ALPHA CHAUSSURES",
        "bio": "Chaussures de qualite pour homme et femme. Livraison Bamako.",
        "plan": "free",
        "photo_dir": "chaussures",
        "products": [
            {"name": "Basket sport blanche",     "price": 22000, "stock": 8,  "image": "ch1.jpg"},
            {"name": "Chaussure habillee homme", "price": 18000, "stock": 5,  "image": "ch2.jpg"},
            {"name": "Sandale femme coloree",    "price": 9500,  "stock": 15, "image": "ch3.jpg"},
        ],
        "flash_sales": [
            {"title": "Destockage baskets -- 48h chrono", "duration_h": 48, "offset_h": -24},
            {"title": "Vente flash chaussures femme",     "duration_h": 2,  "offset_h": 2},
            {"title": "Soldes fin de saison",             "duration_h": 72, "offset_h": -72},
        ],
    },

    "cuisine": {
        "phone": "+22372222222",
        "password": "Rama123@",
        "display_name": "Les Plats du Jour",
        "business_name": "LES PLATS DU JOUR",
        "bio": "Plats cuisines maison livres chauds. Commandez avant 11h.",
        "plan": "medium",
        "photo_dir": "cuisine",
        "products": [
            {"name": "Thieboudiene poisson",    "price": 3500, "stock": 20, "image": "p1.jpg"},
            {"name": "Poulet yassa riz",         "price": 3000, "stock": 15, "image": "p2.jpg"},
            {"name": "Sauce arachide foutou",   "price": 2500, "stock": 25, "image": "p3.jpg"},
            {"name": "Riz gras mouton",          "price": 4000, "stock": 10, "image": "P4.jpg"},
        ],
        "flash_sales": [
            {"title": "Menu midi -- limite 20 portions", "duration_h": 3,  "offset_h": -2},
            {"title": "Commande groupee vendredi",        "duration_h": 4,  "offset_h": 1},
            {"title": "Special weekend thieboudiene XXL", "duration_h": 6,  "offset_h": 24},
            {"title": "Archive -- Menu de lundi passe",  "duration_h": 3,  "offset_h": -96},
        ],
    },

    "montres": {
        "phone": "+22379999999",
        "password": "Rama123@",
        "display_name": "Montres H&F",
        "business_name": "MONTRE HOMME & FEMME",
        "bio": "Montres de marque et repliques haut de gamme.",
        "plan": "pro",
        "photo_dir": "montres",
        "products": [
            {"name": "Casio G-Shock DW-5600 Noir",       "price": 35000, "stock": 4, "image": "m1.jpg"},
            {"name": "Montre Femme Doree Bracelet Mesh",  "price": 28000, "stock": 6, "image": "M2.jpg"},
            {"name": "Chronographe Homme Noir/Rouge",     "price": 45000, "stock": 3, "image": "M3.jpg"},
            {"name": "Montre Connectee Sport Noire",      "price": 55000, "stock": 5, "image": "M4.jpg"},
        ],
        "flash_sales": [
            {"title": "Vente exclusive montres femme",      "duration_h": 3,  "offset_h": -1},
            {"title": "Collection G-Shock -- stock limite", "duration_h": 24, "offset_h": -20},
            {"title": "Arrivee montres connectees",          "duration_h": 48, "offset_h": 3},
            {"title": "Soldes montres vintage",             "duration_h": 6,  "offset_h": -120},
        ],
    },

    "habit": {
        "phone": "+22300000004",
        "password": "Rama123@",
        "display_name": "Luxes & Elegances",
        "business_name": "LUXES & ELEGANCES",
        "bio": "Mode africaine haut de gamme. Boubous brodes, robes de soiree. Livraison Bamako.",
        "plan": "pro",
        "photo_dir": "habit",
        "products": [
            {"name": "Boubou Grand Bassam brode homme", "price": 45000, "stock": 6, "image": "h1.jpg"},
            {"name": "Robe de soiree en pagne luxe",     "price": 38000, "stock": 4, "image": "h2.jpg"},
            {"name": "Costume 3 pieces homme",           "price": 62000, "stock": 3, "image": "h3.jpg"},
            {"name": "Ensemble pagne tailleur femme",    "price": 28000, "stock": 8, "image": "h4.jpg"},
            {"name": "Kaftan brode or et argent",        "price": 55000, "stock": 5, "image": "h5.jpg"},
        ],
        "flash_sales": [
            {"title": "Collection soiree -- Edition limitee", "duration_h": 6,  "offset_h": -3},
            {"title": "Vente exclusive boubous brodes",        "duration_h": 48, "offset_h": 2},
            {"title": "Arrivee collection kaftans",             "duration_h": 24, "offset_h": -48},
            {"title": "Soldes fin de collection",               "duration_h": 72, "offset_h": -96},
        ],
    },
}

# ---------------------------------------------------------------------------
# Donnees fictives clients
# ---------------------------------------------------------------------------

PRENOMS = ["Aminata", "Fatoumata", "Mariam", "Kadiatou", "Bintou",
           "Mamadou", "Ibrahim", "Moussa", "Oumar", "Seydou", "Boubacar"]
NOMS    = ["Diallo", "Traore", "Kone", "Coulibaly", "Keita",
           "Sangare", "Sidibe", "Doumbia", "Bagayoko", "Samake"]
ZONES   = ["Badalabougou", "Hamdallaye ACI", "Medina Coura", "Lafiabougou",
           "Kalaban Coura", "Niamakoro", "Magnambougou", "Banconi", "Faladie"]

CLOSED_STATUSES = ["pending", "confirmed", "out_for_delivery", "delivered", "cancelled"]
CLOSED_WEIGHTS  = [0.10, 0.15, 0.10, 0.50, 0.15]


def _fake_phone():
    return "+2237%d" % random.randint(1000000, 9999999)


def _fake_name():
    return "%s %s" % (random.choice(PRENOMS), random.choice(NOMS))


def _fake_address():
    return "%s, Bamako" % random.choice(ZONES)


# ---------------------------------------------------------------------------
# Commande
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Cree ou remet a zero les comptes de demonstration HayaFlash."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Supprime et recree toutes les donnees demo.")
        parser.add_argument("--shop", choices=list(SHOPS.keys()), default=None,
                            help="Boutique cible: " + " | ".join(SHOPS.keys()))

    def handle(self, *args, **options):
        reset  = options["reset"]
        target = options["shop"]
        shops_to_seed = {target: SHOPS[target]} if target else SHOPS

        for key, cfg in shops_to_seed.items():
            self.stdout.write("\n" + "=" * 55)
            self.stdout.write("  Boutique : %s" % cfg["business_name"])
            self.stdout.write("  Plan     : %s" % cfg["plan"].upper())
            self.stdout.write("=" * 55)
            self._seed_shop(key, cfg, reset=reset)

        self.stdout.write(self.style.SUCCESS("\nSeed termine avec succes."))

    def _seed_shop(self, key, cfg, reset=False):
        from accounts.models import SellerProfile
        from flash_sales.models import FlashSale, FlashSaleStatus
        from products.models import Product, ProductMedia
        from subscriptions.models import Plan
        from subscriptions.services.limits import get_or_create_subscription

        phone = cfg["phone"]
        BASE_DIR = Path(__file__).resolve().parents[4]
        photo_base = BASE_DIR / "static" / "img" / "demo" / cfg["photo_dir"]

        # ── 1. User ─────────────────────────────────────────────────────────
        if reset:
            # FlashSale.owner est PROTECT : un simple User.delete() plante des
            # que des ventes existent encore (bloque la cascade SellerProfile).
            # On supprime d'abord les commandes puis les ventes de ce vendeur.
            from orders.models import Order

            profile = SellerProfile.objects.filter(user__phone=phone).first()
            if profile is not None:
                sale_ids = list(
                    FlashSale.objects.filter(owner=profile).values_list("pk", flat=True)
                )
                Order.service_objects.filter(flash_sale_id__in=sale_ids).delete()
                Product.objects.filter(flash_sale_id__in=sale_ids).delete()
                FlashSale.objects.filter(owner=profile).delete()

            User.objects.filter(phone=phone).delete()
            self.stdout.write("  [DEL] Compte supprime : %s" % phone)

        user, created = User.objects.get_or_create(
            phone=phone,
            defaults={"display_name": cfg["display_name"], "is_phone_verified": True},
        )
        if created:
            user.set_password(cfg["password"])
            user.save()
            self.stdout.write("  [NEW] User cree : %s" % phone)
        else:
            self.stdout.write("  [SKIP] User existant : %s" % phone)

        profile, _ = SellerProfile.objects.get_or_create(
            user=user,
            defaults={"business_name": cfg["business_name"], "bio": cfg["bio"]},
        )

        # ── 2. Abonnement ───────────────────────────────────────────────────
        sub = get_or_create_subscription(profile)
        plan_map = {"free": Plan.FREE, "medium": Plan.MEDIUM, "pro": Plan.PRO}
        plan = plan_map[cfg["plan"]]
        expires = timezone.now() + timedelta(days=365) if plan != Plan.FREE else None
        sub.plan = plan
        sub.expires_at = expires
        sub.save(update_fields=["plan", "expires_at", "updated_at"])
        self.stdout.write("  [PLAN] %s active" % plan.upper())

        # ── 3. Ventes flash + produits + commandes ──────────────────────────
        for fs_data in cfg["flash_sales"]:
            now   = timezone.now()
            start = now + timedelta(hours=fs_data["offset_h"])
            end   = start + timedelta(hours=fs_data["duration_h"])

            if end < now:
                status = FlashSaleStatus.CLOSED
            elif start > now:
                status = FlashSaleStatus.SCHEDULED
            else:
                status = FlashSaleStatus.LIVE

            sale, fs_created = FlashSale.objects.get_or_create(
                owner=profile,
                title=fs_data["title"],
                defaults={
                    "start_time": start,
                    "end_time": end,
                    "status": status,
                    "description": "Vente flash -- %s" % cfg["business_name"],
                },
            )

            if not fs_created:
                self.stdout.write("  [SKIP] Vente existante : %s" % fs_data["title"][:50])
                continue

            self.stdout.write("  [VENTE][%s] %s" % (status, fs_data["title"][:50]))

            # Creer les produits lies a cette vente flash
            products_for_sale = []
            for i, p_data in enumerate(cfg["products"]):
                product = Product.objects.create(
                    flash_sale=sale,
                    name=p_data["name"],
                    price=Decimal(str(p_data["price"])),
                    stock_initial=p_data["stock"],
                    stock_available=p_data["stock"],
                    is_active=True,
                    display_order=i,
                )
                products_for_sale.append(product)

                # Injection photo
                img_filename = p_data.get("image", "")
                img_path = photo_base / img_filename if img_filename else None
                if img_path and img_path.exists():
                    from django.core.files import File
                    with img_path.open("rb") as f:
                        media = ProductMedia(
                            product=product,
                            media_type=ProductMedia.MediaType.IMAGE,
                            alt_text=p_data["name"],
                        )
                        media.file.save(img_filename, File(f), save=True)

            self.stdout.write("  [PROD] %d produits crees" % len(products_for_sale))

            # Creer des commandes selon le statut de la vente
            if status == FlashSaleStatus.LIVE:
                self._create_orders_via_service(sale, products_for_sale, n=random.randint(5, 10))
            elif status == FlashSaleStatus.CLOSED:
                self._create_orders_direct(sale, products_for_sale, n=random.randint(8, 15))
            # SCHEDULED -> pas de commandes

        self.stdout.write("  [OK] Boutique %s prete" % cfg["business_name"])

    # ── Commandes via le service (ventes OPEN) ──────────────────────────────

    def _create_orders_via_service(self, sale, products, n):
        from orders.services.create_order import create_order

        count = 0
        for _ in range(n):
            product = random.choice(products)
            qty = random.randint(1, 2)
            try:
                create_order({
                    "flash_sale_id": sale.id,
                    "customer_name": _fake_name(),
                    "customer_phone": _fake_phone(),
                    "client_request_id": str(uuid.uuid4()),
                    "items": [{"product_id": product.id, "quantity": qty}],
                    "delivery": {"address_text": _fake_address()},
                })
                count += 1
            except Exception:
                pass
        self.stdout.write("  [CMD]  %d commandes via service (OPEN)" % count)

    # ── Commandes directes (ventes CLOSED — historique) ─────────────────────

    def _create_orders_direct(self, sale, products, n):
        from django.db.models import F

        from delivery.models import Delivery
        from orders.models import Order, OrderItem
        from products.models import Product

        # Statut commande -> statut livraison le plus proche (pas de mapping direct
        # dans advance_delivery() pour "cancelled" : on la traite comme un echec).
        status_to_delivery = {
            "pending": Delivery.Status.PENDING,
            "confirmed": Delivery.Status.PENDING,
            "out_for_delivery": Delivery.Status.IN_TRANSIT,
            "delivered": Delivery.Status.DELIVERED,
            "cancelled": Delivery.Status.FAILED,
        }

        count = 0
        for _ in range(n):
            product = random.choice(products)
            qty = random.randint(1, 3)
            if product.stock_available < qty:
                continue
            status = random.choices(CLOSED_STATUSES, weights=CLOSED_WEIGHTS, k=1)[0]
            total = Decimal(str(product.price)) * qty
            delivered = status == "delivered"
            try:
                order = Order.service_objects.create(
                    flash_sale=sale,
                    product=product,
                    customer_name=_fake_name(),
                    customer_phone=_fake_phone(),
                    client_request_id=str(uuid.uuid4()),
                    status=status,
                    total_amount=total,
                )
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name_snapshot=product.name,
                    price_snapshot=product.price,
                    quantity=qty,
                )
                Product.objects.filter(pk=product.pk).update(
                    stock_available=F("stock_available") - qty
                )
                product.stock_available -= qty
                Delivery.objects.create(
                    order=order,
                    address_text=_fake_address(),
                    status=status_to_delivery[status],
                    assigned_to=_fake_name()
                    if status in ("out_for_delivery", "delivered")
                    else "",
                    delivered_at=timezone.now() if delivered else None,
                    cod_amount=total,
                    cod_collected=delivered,
                    cod_collected_at=timezone.now() if delivered else None,
                )
                count += 1
            except Exception:
                pass
        self.stdout.write("  [CMD]  %d commandes directes (CLOSED)" % count)
