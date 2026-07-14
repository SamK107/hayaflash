"""
Management command : seed_demo
==============================
Cree (ou remet a zero) les comptes de demonstration HayaFlash.

Usage
-----
    python manage.py seed_demo                   # cree si absent, skip si present
    python manage.py seed_demo --reset           # supprime et recree
    python manage.py seed_demo --shop habit      # une seule boutique
    python manage.py seed_demo --settings=config.settings.dev

Comptes crees
-------------
    +22371111111 / Rama123@  -> ALPHA CHAUSSURES      (plan FREE)
    +22372222222 / Rama123@  -> LES PLATS DU JOUR     (plan MEDIUM)
    +22379999999 / Rama123@  -> MONTRE HOMME & FEMME  (plan PRO)
    +22300000004 / Rama123@  -> LUXES & ELEGANCES     (plan PRO)

Photos
------
    Les images doivent etre placees dans static/img/demo/<photo_dir>/
    Le champ "image" de chaque produit indique le nom de fichier exact.
    Si le fichier est absent -> le champ reste vide (aucun crash).
"""

from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()

# ---------------------------------------------------------------------------
# Configuration des boutiques
# ---------------------------------------------------------------------------

SHOPS = {
    "chaussures": {
        "phone": "+22371111111",
        "password": "Rama123@",
        "display_name": "Alpha Chaussures",
        "business_name": "ALPHA CHAUSSURES",
        "bio": "Chaussures de qualite pour homme et femme. Livraison partout a Bamako.",
        "plan": "free",
        "photo_dir": "chaussures",
        "products": [
            {
                "name": "Basket sport blanche",
                "price": 22000, "stock": 8,
                "description": "Basket sport coloris blanc, semelle confort, tailles 38-45.",
                "image": "ch1.jpg",
            },
            {
                "name": "Chaussure habillée homme",
                "price": 18000, "stock": 5,
                "description": "Chaussure de ville en cuir verni, idéale pour le bureau ou les cérémonies.",
                "image": "ch2.jpg",
            },
            {
                "name": "Sandale femme colorée",
                "price": 9500, "stock": 15,
                "description": "Sandale légère et tendance, couleurs assorties, pointures 36-42.",
                "image": "ch3.jpg",
            },
        ],
        "flash_sales": [
            {"title": "Déstockage baskets — 48h chrono",  "duration_h": 48, "offset_h": -24},
            {"title": "Vente flash chaussures femme",          "duration_h": 2,  "offset_h": 2},
            {"title": "Soldes fin de saison",                  "duration_h": 72, "offset_h": -72},
        ],
    },

    "cuisine": {
        "phone": "+22372222222",
        "password": "Rama123@",
        "display_name": "Les Plats du Jour",
        "business_name": "LES PLATS DU JOUR",
        "bio": "Plats cuisinés maison livrés chauds. Commandez avant 11h, livraison midi.",
        "plan": "medium",
        "photo_dir": "cuisine",
        "products": [
            {
                "name": "Thiébouдиène poisson",
                "price": 3500, "stock": 20,
                "description": "Thiébouдиène poisson préparé à la bamakoise, avec légumes du jardin. Servi chaud.",
                "image": "p1.jpg",
            },
            {
                "name": "Poulet yassa riz",
                "price": 3000, "stock": 15,
                "description": "Poulet marinée au citron et oignon, accompagné de riz blanc.",
                "image": "p2.jpg",
            },
            {
                "name": "Sauce arachide + foutou",
                "price": 2500, "stock": 25,
                "description": "Sauce arachide onctueuse avec foutou de banane plantain. Plat traditionnel malien.",
                "image": "p3.jpg",
            },
            {
                "name": "Riz gras mouton",
                "price": 4000, "stock": 10,
                "description": "Riz gras préparé au mouton avec épices du marché. Quantité généreuse.",
                "image": "P4.jpg",
            },
        ],
        "flash_sales": [
            {"title": "Menu midi du jour — limité 20 portions", "duration_h": 3,  "offset_h": -2},
            {"title": "Commande groupée vendredi",                 "duration_h": 4,  "offset_h": 1},
            {"title": "Spécial weekend — thiébouдиène XXL",     "duration_h": 6,  "offset_h": 24},
            {"title": "Archive — Menu de lundi passé",              "duration_h": 3,  "offset_h": -96},
        ],
    },

    "montres": {
        "phone": "+22379999999",
        "password": "Rama123@",
        "display_name": "Montres H&F",
        "business_name": "MONTRE HOMME & FEMME",
        "bio": "Montres de marque et répliques haut de gamme. Authentiques ou inspirées, toujours élégantes.",
        "plan": "pro",
        "photo_dir": "montres",
        "products": [
            {
                "name": "Casio G-Shock DW-5600 Noir",
                "price": 35000, "stock": 4,
                "description": "G-Shock iconic, résistante aux chocs et à l'eau 200m. Noir mat, bracelet caoutchouc.",
                "image": "m1.jpg",
            },
            {
                "name": "Montre Femme Dorée Bracelet Mesh",
                "price": 28000, "stock": 6,
                "description": "Montre élégante pour femme, boîtier doré, bracelet mesh milanais. Mouvement quartz.",
                "image": "M2.jpg",
            },
            {
                "name": "Chronographe Homme Noir/Rouge",
                "price": 45000, "stock": 3,
                "description": "Chronographe sportif, cadran noir avec sous-compteurs rouges. Verre saphir.",
                "image": "M3.jpg",
            },
            {
                "name": "Montre Connectée Sport Noire",
                "price": 55000, "stock": 5,
                "description": "Montre connectée : notifications, steps, FC, GPS. Autonomie 7 jours.",
                "image": "M4.jpg",
            },
        ],
        "flash_sales": [
            {"title": "Vente exclusive montres femme",       "duration_h": 3,  "offset_h": -1},
            {"title": "Collection G-Shock — stock limité",  "duration_h": 24, "offset_h": -20},
            {"title": "Arrivée montres connectées",           "duration_h": 48, "offset_h": 3},
            {"title": "Soldes montres vintage",              "duration_h": 6,  "offset_h": -120},
        ],
    },

    "habit": {
        "phone": "+22300000004",
        "password": "Rama123@",
        "display_name": "Luxes & Elegances",
        "business_name": "LUXES & ELEGANCES",
        "bio": "Mode africaine haut de gamme. Boubous brodés, robes de soirée, costumes sur mesure. Livraison Bamako.",
        "plan": "pro",
        "photo_dir": "habit",
        "products": [
            {
                "name": "Boubou Grand Bassam brodé homme",
                "price": 45000, "stock": 6,
                "description": "Boubou 3 pièces en bazin riché, broderie main or, idéal cérémonie et fête.",
                "image": "h1.jpg",
            },
            {
                "name": "Robe de soirée en pagne luxe",
                "price": 38000, "stock": 4,
                "description": "Robe longue en pagne wax premium, coupe ajustée, détail dentelle au col. Couture Bamako.",
                "image": "h2.jpg",
            },
            {
                "name": "Costume 3 pièces homme",
                "price": 62000, "stock": 3,
                "description": "Costume veste + pantalon + gilet, tissu bazin bleu marine, finition brodée. Sur mesure disponible.",
                "image": "h3.jpg",
            },
            {
                "name": "Ensemble pagne tailleur femme",
                "price": 28000, "stock": 8,
                "description": "Ensemble tailleur jupe + haut en pagne wax, coupe moderne, tailles XS-XL.",
                "image": "h4.jpg",
            },
            {
                "name": "Kaftan brodé or & argent",
                "price": 55000, "stock": 5,
                "description": "Kaftan unisexe en soie africaine, broderies fil d'or et argent, taille unique ajustable.",
                "image": "h5.jpg",
            },
        ],
        "flash_sales": [
            {"title": "Collection soirée — Edition limitée",     "duration_h": 6,  "offset_h": -3},
            {"title": "Vente exclusive boubous brodés",           "duration_h": 48, "offset_h": 2},
            {"title": "Arrivée collection kaftans",                "duration_h": 24, "offset_h": -48},
            {"title": "Soldes fin de collection",                   "duration_h": 72, "offset_h": -96},
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

ORDER_STATUSES = ["pending", "confirmed", "out_for_delivery", "delivered", "cancelled"]
STATUS_WEIGHTS = [0.15, 0.20, 0.15, 0.35, 0.15]


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
        parser.add_argument(
            "--reset", action="store_true",
            help="Supprime et recree toutes les donnees demo.",
        )
        parser.add_argument(
            "--shop", choices=list(SHOPS.keys()), default=None,
            help="Traite une seule boutique: " + " | ".join(SHOPS.keys()),
        )

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

    # -----------------------------------------------------------------------

    def _seed_shop(self, key, cfg, reset=False):
        from accounts.models import SellerProfile
        from flash_sales.models import FlashSale, FlashSaleStatus
        from orders.services.create_order import create_order
        from products.models import Product, ProductMedia
        from subscriptions.models import Plan
        from subscriptions.services.limits import get_or_create_subscription

        phone = cfg["phone"]
        BASE_DIR = Path(__file__).resolve().parents[4]
        photo_base = BASE_DIR / "static" / "img" / "demo" / cfg["photo_dir"]

        # 1. User + SellerProfile
        if reset:
            User.objects.filter(phone=phone).delete()
            self.stdout.write("  [DEL] Compte %s supprime" % phone)

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

        # 2. Abonnement
        sub = get_or_create_subscription(profile)
        plan_map = {"free": Plan.FREE, "medium": Plan.MEDIUM, "pro": Plan.PRO}
        plan = plan_map[cfg["plan"]]
        expires = timezone.now() + timedelta(days=365) if plan != Plan.FREE else None
        sub.plan = plan
        sub.expires_at = expires
        sub.save(update_fields=["plan", "expires_at", "updated_at"])
        self.stdout.write("  [PLAN] %s active" % plan.upper())

        # 3. Produits + photos
        for p_data in cfg["products"]:
            product, p_created = Product.objects.get_or_create(
                owner=profile,
                name=p_data["name"],
                defaults={
                    "price": p_data["price"],
                    "stock_available": p_data["stock"],
                    "description": p_data["description"],
                    "is_active": True,
                },
            )
            if p_created:
                self.stdout.write("  [PROD] Cree : %s" % p_data["name"])

                # Injection photo si disponible
                img_filename = p_data.get("image", "")
                img_path = photo_base / img_filename if img_filename else None
                if img_path and img_path.exists():
                    if not ProductMedia.objects.filter(product=product).exists():
                        from django.core.files import File
                        with img_path.open("rb") as f:
                            media = ProductMedia(
                                product=product,
                                media_type=ProductMedia.MediaType.IMAGE,
                                alt_text=p_data["name"],
                            )
                            media.file.save(img_filename, File(f), save=True)
                        self.stdout.write("  [IMG]  Photo injectee : %s" % img_filename)
                else:
                    self.stdout.write("  [IMG]  Pas de photo : %s" % (img_filename or "non defini"))

        products = list(Product.objects.filter(owner=profile))

        # 4. Ventes flash + commandes
        for fs_data in cfg["flash_sales"]:
            now   = timezone.now()
            start = now + timedelta(hours=fs_data["offset_h"])
            end   = start + timedelta(hours=fs_data["duration_h"])

            if end < now:
                status = FlashSaleStatus.CLOSED
            elif start > now:
                status = FlashSaleStatus.SCHEDULED
            else:
                status = FlashSaleStatus.OPEN

            sale, fs_created = FlashSale.objects.get_or_create(
                owner=profile,
                title=fs_data["title"],
                defaults={
                    "start_time": start,
                    "end_time": end,
                    "status": status,
                    "description": "Vente flash -- %s" % cfg["business_name"],
                    "is_public": True,
                },
            )

            if not fs_created:
                self.stdout.write("  [SKIP] Vente deja existante : %s" % fs_data["title"][:45])
                continue

            self.stdout.write("  [VENTE][%s] %s" % (status, fs_data["title"][:45]))

            if status in (FlashSaleStatus.CLOSED, FlashSaleStatus.OPEN):
                n_orders = random.randint(5, 14)
                created_orders = 0
                for _ in range(n_orders):
                    product = random.choice(products)
                    qty = random.randint(1, 2)
                    try:
                        create_order(
                            flash_sale=sale,
                            product=product,
                            quantity=qty,
                            buyer_name=_fake_name(),
                            buyer_phone=_fake_phone(),
                            delivery_address=_fake_address(),
                            notes="",
                        )
                        created_orders += 1
                    except Exception:
                        pass
                self.stdout.write("  [CMD]  %d commandes creees" % created_orders)

        self.stdout.write("  [OK] Boutique %s prete" % cfg["business_name"])
