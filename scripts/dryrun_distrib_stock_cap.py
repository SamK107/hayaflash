"""Dry-run F-158 : produits importes (Distrib) dont stock_available > allocated_qty.

LECTURE SEULE — aucune ecriture, aucune transaction d'ecriture. Liste ce qui serait
change si l'on ramenait stock_available a allocated_qty (via adjust_stock :
Product.stock_available + un StockMovement CORRECTION de la difference).

Usage (sur la pile voulue) :
    docker compose -f docker-compose.production.yml exec -T web \
        python manage.py shell < scripts/dryrun_distrib_stock_cap.py
"""
from django.db.models import F, Sum

from distrib.models import ImportedProduct
from orders.models import OrderItem
from products.models import StockMovement

bad = (
    ImportedProduct.objects.select_related("product", "invite")
    .filter(product__stock_available__gt=F("allocated_qty"))
    .order_by("pk")
)

print(f"DRY-RUN F-158 — aucune ecriture. Lignes concernees : {bad.count()}")
for ip in bad:
    p = ip.product
    delta = ip.allocated_qty - p.stock_available
    mv_sum = (
        StockMovement.objects.filter(product=p).aggregate(s=Sum("quantity_change"))["s"] or 0
    )
    n_items = OrderItem.objects.filter(product=p).count()
    print(
        f"- ImportedProduct #{ip.pk} | revendeuse : {ip.invite.display_name} | produit #{p.pk}\n"
        f"    stock_available : {p.stock_available} -> {ip.allocated_qty} (delta {delta:+d})\n"
        f"    StockMovement qui serait cree : CORRECTION {delta:+d}\n"
        f"    controle : somme des StockMovement = {mv_sum} (stock actuel {p.stock_available}) ; "
        f"lignes de commande sur ce produit : {n_items}"
    )
print("FIN — rien n'a ete modifie.")
