"""Controle lecture seule : Product.stock_initial incoherent avec l'historique (suite F-162).

LECTURE SEULE — aucune ecriture. Pour chaque produit, compare stock_initial a une
valeur de reference deduite de l'historique :
  - produit importe (Distrib) : allocated_qty (= allocation initiale + allocations/reprises,
    la meme valeur que _move_stock maintient sur stock_initial) ;
  - autre produit : somme des mouvements INITIAL (les ajustements de stock ne touchent
    pas stock_initial).
Signale aussi les produits dont la somme des StockMovement != stock_available
(controle independant : un stock_available derive est un autre probleme que stock_initial).

Usage (sur la pile voulue) :
    docker compose -f docker-compose.production.yml exec -T web \
        python manage.py shell < scripts/dryrun_stock_initial_consistency.py
"""
from distrib.models import ImportedProduct
from products.models import Product, StockMovement


def main():
    MT = StockMovement.MovementType
    imported_by_product = {
        ip.product_id: ip for ip in ImportedProduct.objects.select_related("invite")
    }
    rows, no_baseline, drift = [], [], []
    for p in Product.objects.order_by("pk").iterator():
        movs = list(StockMovement.objects.filter(product=p).order_by("created_at", "pk"))
        mv_sum = sum(m.quantity_change for m in movs)
        initial_mv = sum(m.quantity_change for m in movs if m.movement_type == MT.INITIAL)
        has_initial = any(m.movement_type == MT.INITIAL for m in movs)
        ip = imported_by_product.get(p.pk)
        if ip is not None:
            expected, basis = ip.allocated_qty, f"allocated_qty (import #{ip.pk})"
        elif has_initial:
            expected, basis = initial_mv, "mouvement INITIAL"
        else:
            no_baseline.append(p)
            expected, basis = None, None
        if expected is not None and p.stock_initial != expected:
            rows.append((p, expected, basis, mv_sum, movs))
        if movs and mv_sum != p.stock_available:
            drift.append((p, mv_sum))
    print("CONTROLE stock_initial — LECTURE SEULE, rien n'est modifie.")
    print(f"Produits examines : {Product.objects.count()}")
    print(f"\n== stock_initial incoherent : {len(rows)} produit(s) ==")
    for p, expected, basis, mv_sum, movs in rows:
        print(
            f"- produit #{p.pk} {p.name!r} (vendeur #{p.owner_id})\n"
            f"    stock_initial = {p.stock_initial} ; stock_available = {p.stock_available}\n"
            f"    valeur probable d'apres l'historique : {expected}  [{basis}]\n"
            f"    somme des mouvements = {mv_sum} ; mouvements : "
            + ", ".join(f"{m.movement_type}{m.quantity_change:+d}" for m in movs)
        )
    print(f"\n== somme des mouvements != stock_available : {len(drift)} produit(s) (info) ==")
    for p, mv_sum in drift:
        print(f"- produit #{p.pk} {p.name!r} : stock_available {p.stock_available} vs mouvements {mv_sum}")
    print(f"\n== sans mouvement INITIAL ni import (non evaluable) : {len(no_baseline)} produit(s) ==")
    print("  ids : " + (", ".join(str(p.pk) for p in no_baseline[:50]) or "-"))
    print("FIN — rien n'a ete modifie.")


main()
