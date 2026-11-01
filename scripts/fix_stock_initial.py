"""Corrige Product.stock_initial d'UN produit importe (Distrib) — suite F-162 / F-163.

Simulation par defaut ; ecriture seulement avec APPLY=1. Variables d'environnement :
    PRODUCT_ID  (obligatoire)  produit a corriger
    APPLY=1     (optionnel)    ecrire (sinon simulation, aucune ecriture)

Valeur cible = ImportedProduct.allocated_qty, a condition que l'historique la confirme
(somme des StockMovement == stock_available == allocated_qty). ARRET sans rien ecrire si :
le produit n'est pas importe, si une commande (Order ou OrderItem) existe, ou si
l'historique ne confirme pas la cible. Seul stock_initial change : pas de StockMovement
(stock_initial n'est pas journalise), la trace est une entree AuditLog.

Usage (sur la pile voulue, depuis son dossier) :
    docker compose -f docker-compose.production.yml exec -T -e PRODUCT_ID=283 web \
        python manage.py shell < /home/sam/fix_stock_initial.py
    docker compose -f docker-compose.production.yml exec -T -e PRODUCT_ID=283 -e APPLY=1 web \
        python manage.py shell < /home/sam/fix_stock_initial.py
"""
import os

from django.db import transaction
from django.db.models import Sum

from core.models import audit
from distrib.models import ImportedProduct
from orders.models import Order, OrderItem
from products.models import Product, StockMovement


def main():
    raw = os.environ.get("PRODUCT_ID", "")
    apply = os.environ.get("APPLY") == "1"
    if not raw.isdigit():
        print("ARRET : PRODUCT_ID manquant ou invalide. Rien n'a ete modifie.")
        return
    pk = int(raw)
    print(f"CORRECTION stock_initial produit #{pk} — mode {'APPLY (ecriture)' if apply else 'SIMULATION (aucune ecriture)'}")
    with transaction.atomic():
        p = Product.objects.select_for_update().filter(pk=pk).first()
        if p is None:
            print("ARRET : produit introuvable. Rien n'a ete modifie.")
            return
        n_items = OrderItem.objects.filter(product=p).count()
        n_orders = Order.objects.filter(product=p).count()
        n_orders_via_items = Order.objects.filter(items__product=p).distinct().count()
        print(f"Commandes : Order.product={n_orders} ; Order via OrderItem={n_orders_via_items} ; OrderItem={n_items}")
        if n_items or n_orders or n_orders_via_items:
            print("ARRET : des commandes existent sur ce produit — a remonter au mainteneur. Rien n'a ete modifie.")
            return
        ip = ImportedProduct.objects.filter(product=p).first()
        if ip is None:
            print("ARRET : produit non importe (pas d'ImportedProduct). Rien n'a ete modifie.")
            return
        mv_sum = StockMovement.objects.filter(product=p).aggregate(s=Sum("quantity_change"))["s"] or 0
        print(
            f"Produit {p.name!r} : stock_initial={p.stock_initial} ; stock_available={p.stock_available} ; "
            f"allocated_qty={ip.allocated_qty} ; somme des mouvements={mv_sum}"
        )
        target = ip.allocated_qty
        if not (mv_sum == p.stock_available == target):
            print("ARRET : l'historique ne confirme pas la cible (mouvements/stock/allocation differents). Rien n'a ete modifie.")
            return
        if p.stock_initial == target:
            print("Rien a faire : stock_initial est deja correct.")
            return
        print(f"stock_initial : {p.stock_initial} -> {target}")
        if not apply:
            print("SIMULATION — rien n'a ete modifie. Relancer avec APPLY=1 pour ecrire.")
            return
        old = p.stock_initial
        Product.objects.filter(pk=p.pk).update(stock_initial=target)
        audit(
            "products.stock_initial_regularized",
            entity_type="Product",
            entity_id=p.pk,
            old_stock_initial=old,
            new_stock_initial=target,
            imported_product_id=ip.pk,
            finding="F-162/F-163",
        )
    p.refresh_from_db()
    print(f"APPLIQUE : stock_initial = {p.stock_initial} (ancien {old}). AuditLog ecrit.")


main()
