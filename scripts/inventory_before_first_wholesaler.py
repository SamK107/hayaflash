"""Inventaire avant le premier grossiste : qu'y a-t-il en base, compte par compte ?

LECTURE SEULE — aucune ecriture, aucune suppression. Sert a reperer les donnees de test
(fictives) a retirer ou a desactiver avant d'enregistrer le premier grossiste reel.
Les telephones sont masques (4 derniers chiffres) ; aucun secret n'est affiche.

Usage (sur la pile voulue, depuis son dossier) :
    docker compose -f docker-compose.production.yml exec -T web \
        python manage.py shell < /home/sam/inventory_before_first_wholesaler.py
"""
from collections import Counter

from accounts.models import SellerProfile, User
from core.models import AuditLog
from delivery.models import Delivery
from distrib.models import (
    DistribPayment,
    DistribSettlement,
    DistribStatement,
    Distributor,
    ImportedProduct,
    ResellerInvite,
    ResellerPayout,
    WholesaleProduct,
)
from flash_sales.models import FlashSale
from orders.models import Order, OrderItem
from payments.models import LedgerEntry, PaymentTransaction
from products.models import Product
from subscriptions.models import Subscription, SubscriptionPayment


def mask(phone):
    p = str(phone or "")
    return f"***{p[-4:]}" if len(p) > 4 else (p or "-")


def by_status(qs, field="status"):
    return ", ".join(f"{k}={v}" for k, v in sorted(Counter(qs.values_list(field, flat=True)).items())) or "-"


def section(title):
    print(f"\n=== {title} ===")


def sellers():
    section("VENDEURS (SellerProfile)")
    for sp in SellerProfile.objects.select_related("user").order_by("pk"):
        u = sp.user
        sales = FlashSale.objects.filter(owner=sp)
        orders = Order.objects.filter(flash_sale__owner=sp)
        sub = Subscription.objects.filter(seller=sp).first()
        print(
            f"- vendeur #{sp.pk} {sp.seller_code} | {u.display_name!r} | tel {mask(u.phone)} | "
            f"boutique {sp.business_name!r} | inscrit {u.date_joined:%Y-%m-%d} | staff={u.is_staff} | actif={u.is_active}\n"
            f"    produits={Product.objects.filter(owner=sp).count()} | ventes={sales.count()} ({by_status(sales)}) | "
            f"commandes={orders.count()} ({by_status(orders)}) | livraisons={Delivery.objects.filter(order__flash_sale__owner=sp).count()} | "
            f"plan={getattr(sub, 'plan', '-')} | paiements abonnement={SubscriptionPayment.objects.filter(seller=sp).count()}"
        )
    no_profile = User.objects.filter(seller_profile__isnull=True)
    print(f"\nComptes sans boutique : {no_profile.count()}")
    for u in no_profile.order_by("pk"):
        print(f"- user #{u.pk} {u.display_name!r} | tel {mask(u.phone)} | staff={u.is_staff} | superuser={u.is_superuser} | actif={u.is_active}")


def distrib():
    section("DISTRIB")
    for d in Distributor.objects.select_related("user").order_by("pk"):
        print(
            f"- grossiste #{d.pk} {d.business_name!r} | user #{d.user_id} tel {mask(d.user.phone)} | actif={d.is_active} | "
            f"suspendu={d.is_suspended} | cree {d.created_at:%Y-%m-%d}\n"
            f"    catalogue={WholesaleProduct.objects.filter(distributor=d).count()} | invites={ResellerInvite.objects.filter(distributor=d).count()} "
            f"({by_status(ResellerInvite.objects.filter(distributor=d))}) | releves={DistribStatement.objects.filter(distributor=d).count()} | "
            f"versements={ResellerPayout.objects.filter(distributor=d).count()} | reglements lignes={DistribSettlement.objects.filter(distributor=d).count()} | "
            f"paiements commission={DistribPayment.objects.filter(distributor=d).count()}"
        )
    print("\nRevendeurs invites :")
    for i in ResellerInvite.objects.select_related("distributor", "seller").order_by("pk"):
        print(
            f"- invite #{i.pk} {i.display_name!r} tel {mask(i.phone)} -> grossiste #{i.distributor_id} | {i.status} | "
            f"boutique liee {i.seller_id or '-'} | importations={ImportedProduct.objects.filter(invite=i).count()}"
        )
    print("\nProduits importes :")
    for ip in ImportedProduct.objects.select_related("product", "invite").order_by("pk"):
        print(
            f"- import #{ip.pk} produit #{ip.product_id} {ip.product.name!r} | revendeur invite #{ip.invite_id} | "
            f"alloue={ip.allocated_qty} | stock={ip.product.stock_available} | reglements={DistribSettlement.objects.filter(imported_product=ip).count()}"
        )


def orders_and_money():
    section("COMMANDES, PAIEMENTS, JOURNAUX")
    print(f"Commandes : {Order.objects.count()} ({by_status(Order.objects.all())}) | lignes={OrderItem.objects.count()} | livraisons={Delivery.objects.count()}")
    for o in Order.objects.select_related("flash_sale").order_by("pk")[:40]:
        print(f"- commande #{o.pk} | vente #{o.flash_sale_id} | {o.status} | {o.total_amount} FCFA | tel {mask(o.customer_phone)} | {o.created_at:%Y-%m-%d}")
    print(f"Paiements abonnement : {SubscriptionPayment.objects.count()} ({by_status(SubscriptionPayment.objects.all())}) | dont tarif special={SubscriptionPayment.objects.filter(is_special_price=True).count()}")
    print(f"PaymentTransaction={PaymentTransaction.objects.count()} | LedgerEntry={LedgerEntry.objects.count()} | AuditLog={AuditLog.objects.count()}")


def ventes_et_produits():
    section("VENTES ET PRODUITS (40 plus recents)")
    for s in FlashSale.objects.select_related("owner").order_by("-pk")[:40]:
        print(f"- vente #{s.pk} {s.title!r} | vendeur #{s.owner_id} | {s.status} | cree {s.created_at:%Y-%m-%d} | commandes={Order.objects.filter(flash_sale=s).count()}")
    for p in Product.objects.select_related("owner").order_by("-pk")[:40]:
        print(f"- produit #{p.pk} {p.name!r} | vendeur #{p.owner_id} | actif={p.is_active} | stock={p.stock_available}/{p.stock_initial} | commandes={OrderItem.objects.filter(product=p).count()}")


def main():
    print("INVENTAIRE — LECTURE SEULE, rien n'est modifie.")
    for fn in (sellers, distrib, ventes_et_produits, orders_and_money):
        try:
            fn()
        except Exception as exc:  # inventaire : un champ different ne doit pas masquer le reste
            print(f"\n[!] section {fn.__name__} interrompue : {type(exc).__name__}: {exc}")
    print("\nFIN — rien n'a ete modifie.")


main()
