"""Donnees de demo pour tester /ventes/ (Le Marche) en local.

    python manage.py seed_marche_demo            # cree la demo
    python manage.py seed_marche_demo --clear    # supprime tout ce qu'elle a cree

Refuse de tourner si DEBUG=False. Tout est repere par le prefixe de telephone
``DEMO_PHONE_PREFIX`` (comptes vendeurs) : --clear ne touche rien d'autre.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

DEMO_PHONE_PREFIX = "+22379990"
# (nom, categorie, telephone)
SHOPS = [
    ("Demo Awa Mode", "mode", DEMO_PHONE_PREFIX + "001"),
    ("Demo Fanta Beaute", "beaute", DEMO_PHONE_PREFIX + "002"),
    ("Demo Moussa Tech", "electronique", DEMO_PHONE_PREFIX + "003"),
]
ORDER_COUNT = 10
IN_TRANSIT_COUNT = 3


class Command(BaseCommand):
    help = "Cree (ou supprime avec --clear) des donnees de demo pour /ventes/. DEBUG uniquement."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--clear", action="store_true", help="Supprime les donnees de demo.")

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_marche_demo refuse de tourner avec DEBUG=False.")
        if options["clear"]:
            self._clear()
        else:
            self._create()

    # ── Suppression ───────────────────────────────────────────────────
    def _clear(self) -> None:
        from accounts.models import SellerProfile
        from flash_sales.models import FlashSale
        from orders.models import Order
        from products.models import Product

        User = get_user_model()
        users = User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX)
        sellers = SellerProfile.objects.filter(user__in=users)
        with transaction.atomic():
            # Ordre impose par les FK PROTECT : commandes (livraisons et lignes
            # en cascade) -> ventes -> produits -> boutiques -> comptes.
            Order.service_objects.filter(flash_sale__owner__in=sellers).delete()
            FlashSale.objects.filter(owner__in=sellers).delete()
            Product.objects.filter(owner__in=sellers).delete()
            sellers.delete()
            deleted = users.delete()[0]
        self.stdout.write(self.style.SUCCESS(f"Demo supprimee ({deleted} comptes et dependances)."))

    # ── Creation ──────────────────────────────────────────────────────
    def _create(self) -> None:
        from accounts.models import SellerProfile
        from delivery.models import Delivery
        from flash_sales.models import FlashSale, FlashSaleStatus
        from orders.models import Order, OrderItem, OrderStatus
        from products.models import FlashSaleProduct, Product

        User = get_user_model()
        if User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists():
            raise CommandError("La demo existe deja : lance d'abord --clear.")

        now = timezone.now()
        with transaction.atomic():
            sellers = []
            for name, category, phone in SHOPS:
                user = User.objects.create_user(phone=phone, password=None, display_name=name)
                sellers.append(
                    SellerProfile.objects.create(user=user, business_name=name, category=category)
                )

            def sale(owner, title, start, end, status, stock):
                s = FlashSale.objects.create(
                    owner=owner, title=title, start_time=now + start, end_time=now + end, status=status
                )
                p = Product.objects.create(
                    owner=owner, name=title, stock_available=stock, stock_initial=20,
                    price=Decimal(5000),
                )
                FlashSaleProduct.objects.create(flash_sale=s, product=p)
                return s, p

            live, live_product = sale(
                sellers[0], "Demo robes wax", timedelta(minutes=-20), timedelta(minutes=40),
                FlashSaleStatus.LIVE, 12,
            )
            sale(
                sellers[1], "Demo soins visage", timedelta(minutes=30), timedelta(hours=1, minutes=30),
                FlashSaleStatus.SCHEDULED, 20,
            )
            ended, ended_product = sale(
                sellers[2], "Demo ecouteurs", timedelta(hours=-2), timedelta(hours=-1),
                FlashSaleStatus.COMPLETED, 0,
            )

            # ~10 commandes sur 2 boutiques (vente en direct + vente terminee) dans
            # la derniere heure ; les 3 premieres livraisons sont IN_TRANSIT.
            for i in range(ORDER_COUNT):
                sale_obj, product = (live, live_product) if i % 2 == 0 else (ended, ended_product)
                order = Order.service_objects.create(
                    flash_sale=sale_obj, customer_name=f"Client demo {i + 1}",
                    customer_phone=f"+2237888{i:04d}", status=OrderStatus.PENDING,
                    client_request_id=f"demo-marche-{i}", total_amount=product.price,
                )
                Order.service_objects.filter(pk=order.pk).update(
                    created_at=now - timedelta(minutes=5 + i * 5)
                )
                OrderItem.objects.create(
                    order=order, product=product, product_name_snapshot=product.name,
                    price_snapshot=product.price, quantity=1,
                )
                if i < IN_TRANSIT_COUNT:
                    Order.service_objects.filter(pk=order.pk).update(status=OrderStatus.OUT_FOR_DELIVERY)
                    Delivery.objects.create(
                        order=order, address_text="Demo, Bamako", cod_amount=product.price,
                        status=Delivery.Status.IN_TRANSIT,
                    )

        self.stdout.write(self.style.SUCCESS(
            f"Demo creee : {len(SHOPS)} boutiques, 3 ventes, {ORDER_COUNT} commandes "
            f"dont {IN_TRANSIT_COUNT} en livraison. Ouvre /ventes/ ; supprime avec --clear."
        ))
