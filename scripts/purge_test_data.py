"""Purge ciblee des donnees de TEST avant le premier grossiste reel (production).

Simulation par defaut ; ecriture seulement avec APPLY=1. Cibles = inventaire du 01/11/2026
(scripts/inventory_before_first_wholesaler.py). Chaque cible est verifiee par son NOM : si la
base a change depuis l'inventaire, le script s'arrete sans rien ecrire.

Ce qui est supprime
  - grossistes #1 et #2 (catalogue, invitations, importations, utilisateurs associes) ;
  - vendeur #3 (boutique, ventes, produits, utilisateur) ;
  - vendeur #1 : SES COMMANDES, VENTES et PRODUITS seulement. Le compte, son abonnement et
    son paiement a tarif special sont CONSERVES (SubscriptionPayment est en CASCADE sur le
    vendeur : supprimer le compte effacerait la trace du test de paiement reel).
Ce qui n'est jamais touche : vendeur #2 (reel, verifie avant/apres), comptes staff,
AuditLog, PaymentTransaction, LedgerEntry. Fichiers (photos, audios) : listes, PAS supprimes.

Arret sans rien ecrire si : un relevé / versement / reglement / paiement Distrib existe, une
commande existe sur un vendeur a supprimer, le nombre de commandes du vendeur #1 differe de
l'attendu, un utilisateur cible est staff, ou le vendeur protege change.

Simulation = les memes suppressions dans une transaction ANNULEE a la fin (aucun signal de
suppression de fichier n'existe dans le projet ; rien n'est ecrit).

Variables : APPLY=1 (ecrire) ; PURGE_SPEC (JSON, pour les tests uniquement).
Usage (depuis le dossier de la pile) :
    docker compose -f docker-compose.production.yml exec -T web \
        python manage.py shell < /home/sam/purge_test_data.py
    docker compose -f docker-compose.production.yml exec -T -e APPLY=1 web \
        python manage.py shell < /home/sam/purge_test_data.py
"""
import json
import os

from django.db import transaction
from django.db.models import ProtectedError

from accounts.models import SellerProfile, User
from core.models import audit
from delivery.models import Delivery
from distrib.models import (
    DistribPayment,
    DistribSettlement,
    DistribStatement,
    Distributor,
    ImportedProduct,
    ResellerInvite,
    ResellerPayout,
    WholesaleProductImage,
    WholesaleProduct,
)
from flash_sales.models import FlashSale
from orders.models import Order, OrderItem
from products.models import Product, ProductMedia
from subscriptions.models import Subscription, SubscriptionPayment

DEFAULT_SPEC = {
    "distributors": {"1": "MARIAM SHOP XL", "2": "BINTA GROSSISTE"},
    "delete_sellers": {"3": "MALADO LUXE"},
    "clean_sellers": {"1": "COMPTOIR DES PRODUITS"},
    "protected_sellers": {"2": "VÉNUS BEAUTÉ"},
    "expected_orders_clean_sellers": {"1": 2},
}


class Stop(Exception):
    """Arret controle : rien n'est ecrit."""


class Rollback(Exception):
    """Fin de simulation : on annule la transaction."""


def _ids(mapping):
    return [int(k) for k in mapping]


def _profile_counts(sp):
    return (
        Product.objects.filter(owner=sp).count(),
        FlashSale.objects.filter(owner=sp).count(),
        Order.objects.filter(flash_sale__owner=sp).count(),
        Subscription.objects.filter(seller=sp).count(),
        SubscriptionPayment.objects.filter(seller=sp).count(),
    )


def _check_names(spec):
    dists = {d.pk: d for d in Distributor.objects.filter(pk__in=_ids(spec["distributors"])).select_related("user")}
    sellers = {}
    for key in ("delete_sellers", "clean_sellers", "protected_sellers"):
        found = {s.pk: s for s in SellerProfile.objects.filter(pk__in=_ids(spec[key])).select_related("user")}
        for k, name in spec[key].items():
            sp = found.get(int(k))
            if sp is None or sp.business_name != name:
                raise Stop(f"{key} #{k} : attendu {name!r}, trouve {getattr(sp, 'business_name', None)!r}.")
        sellers[key] = found
    for k, name in spec["distributors"].items():
        d = dists.get(int(k))
        if d is None or d.business_name != name:
            raise Stop(f"grossiste #{k} : attendu {name!r}, trouve {getattr(d, 'business_name', None)!r}.")
    return dists, sellers


def _guards(spec, dists, sellers):
    dist_ids = list(dists)
    for label, model in (
        ("releves", DistribStatement), ("versements", ResellerPayout),
        ("reglements", DistribSettlement), ("paiements commission", DistribPayment),
    ):
        n = model.objects.filter(distributor_id__in=dist_ids).count()
        if n:
            raise Stop(f"{n} {label} Distrib existent sur les grossistes cibles.")
    for sp in sellers["delete_sellers"].values():
        n = (
            Order.objects.filter(flash_sale__owner=sp).count()
            + Order.objects.filter(product__owner=sp).count()
            + OrderItem.objects.filter(product__owner=sp).count()
        )
        if n:
            raise Stop(f"vendeur #{sp.pk} : {n} commande(s)/ligne(s) existent.")
        if SubscriptionPayment.objects.filter(seller=sp).exists():
            raise Stop(f"vendeur #{sp.pk} : un paiement d'abonnement existe (CASCADE).")
    for k, expected in spec["expected_orders_clean_sellers"].items():
        sp = sellers["clean_sellers"][int(k)]
        n = Order.objects.filter(flash_sale__owner=sp).count()
        if n != expected:
            raise Stop(f"vendeur #{k} : {n} commande(s) au lieu de {expected} attendues.")
        stray = OrderItem.objects.filter(product__owner=sp).exclude(order__flash_sale__owner=sp).count()
        stray += Order.objects.filter(product__owner=sp).exclude(flash_sale__owner=sp).count()
        if stray:
            raise Stop(f"vendeur #{k} : {stray} commande(s) d'une AUTRE boutique portent sur ses produits.")
    users = {d.user for d in dists.values()} | {s.user for s in sellers["delete_sellers"].values()}
    protected_users = {s.user_id for s in sellers["protected_sellers"].values()}
    for u in users:
        if u.is_staff or u.is_superuser:
            raise Stop(f"utilisateur #{u.pk} est staff : jamais supprime.")
        if u.pk in protected_users:
            raise Stop(f"utilisateur #{u.pk} appartient au vendeur protege.")
        other = SellerProfile.objects.filter(user=u).exclude(pk__in=_ids(spec["delete_sellers"]))
        if other.exists():
            raise Stop(f"utilisateur #{u.pk} a une autre boutique.")
    return users


def _files(dists, sellers):
    del_sellers = list(sellers["delete_sellers"].values())
    clean_sellers = list(sellers["clean_sellers"].values())
    owners = del_sellers + clean_sellers
    names = []
    names += [m.file.name for m in ProductMedia.objects.filter(product__owner__in=owners) if m.file]
    names += [p.description_audio.name for p in Product.objects.filter(owner__in=owners) if p.description_audio]
    names += [s.cover_image.name for s in FlashSale.objects.filter(owner__in=owners) if s.cover_image]
    names += [s.description_audio.name for s in FlashSale.objects.filter(owner__in=owners) if s.description_audio]
    names += [d.audio_note.name for d in Delivery.objects.filter(order__flash_sale__owner__in=owners) if d.audio_note]
    names += [i.image.name for i in WholesaleProductImage.objects.filter(wholesale_product__distributor__in=dists.values()) if i.image]
    imported = ImportedProduct.objects.filter(invite__distributor__in=dists.values()).values_list("product_id", flat=True)
    names += [m.file.name for m in ProductMedia.objects.filter(product_id__in=list(imported)) if m.file]
    names += [sp.avatar.name for sp in del_sellers if sp.avatar]
    return sorted(set(n for n in names if n))


def _say(step, result):
    total, per_model = result
    detail = ", ".join(f"{k.split('.')[-1]}={v}" for k, v in sorted(per_model.items()) if v) or "rien"
    print(f"  {step} : {total} ligne(s) ({detail})")
    return per_model


def _delete_all(spec, dists, sellers, users):
    summary = {}

    def run(step, qs):
        per = _say(step, qs.delete())
        for k, v in per.items():
            summary[k] = summary.get(k, 0) + v

    dist_ids = list(dists)
    imported_products = list(
        ImportedProduct.objects.filter(invite__distributor_id__in=dist_ids).values_list("product_id", flat=True)
    )
    run("produits importes (et leurs importations)", Product.objects.filter(pk__in=imported_products))
    run("catalogue de gros", WholesaleProduct.objects.filter(distributor_id__in=dist_ids))
    run("revendeurs invites", ResellerInvite.objects.filter(distributor_id__in=dist_ids))
    run("grossistes", Distributor.objects.filter(pk__in=dist_ids))
    del_ids = [s.pk for s in sellers["delete_sellers"].values()]
    run("ventes des vendeurs supprimes", FlashSale.objects.filter(owner_id__in=del_ids))
    run("produits des vendeurs supprimes", Product.objects.filter(owner_id__in=del_ids))
    run("boutiques supprimees", SellerProfile.objects.filter(pk__in=del_ids))
    clean_ids = [s.pk for s in sellers["clean_sellers"].values()]
    run("commandes des vendeurs nettoyes", Order.objects.filter(flash_sale__owner_id__in=clean_ids))
    run("ventes des vendeurs nettoyes", FlashSale.objects.filter(owner_id__in=clean_ids))
    run("produits des vendeurs nettoyes", Product.objects.filter(owner_id__in=clean_ids))
    run("utilisateurs", User.objects.filter(pk__in=[u.pk for u in users]))
    return summary


def main():
    apply = os.environ.get("APPLY") == "1"
    spec = json.loads(os.environ["PURGE_SPEC"]) if os.environ.get("PURGE_SPEC") else DEFAULT_SPEC
    print(f"PURGE DES DONNEES DE TEST — mode {'APPLY (ecriture)' if apply else 'SIMULATION (aucune ecriture)'}")
    try:
        with transaction.atomic():
            dists, sellers = _check_names(spec)
            users = _guards(spec, dists, sellers)
            protected_before = {k: _profile_counts(sp) for k, sp in sellers["protected_sellers"].items()}
            clean_keep_before = {
                k: (Subscription.objects.filter(seller=sp).count(), SubscriptionPayment.objects.filter(seller=sp).count())
                for k, sp in sellers["clean_sellers"].items()
            }
            print("Gardes : OK (aucun releve/versement/reglement/paiement Distrib, aucune commande sur les vendeurs supprimes).")
            files = _files(dists, sellers)
            summary = _delete_all(spec, dists, sellers, users)
            for k, sp in sellers["protected_sellers"].items():
                if _profile_counts(sp) != protected_before[k]:
                    raise Stop(f"le vendeur protege #{k} a change : annule.")
            for k, sp in sellers["clean_sellers"].items():
                after = (Subscription.objects.filter(seller=sp).count(), SubscriptionPayment.objects.filter(seller=sp).count())
                if after != clean_keep_before[k]:
                    raise Stop(f"abonnement/paiement du vendeur #{k} perdu : annule.")
            print("Verifications : vendeur protege inchange ; abonnement et paiement du vendeur nettoye conserves.")
            if files:
                print(f"Fichiers orphelins ({len(files)}) — NON supprimes, a effacer a la main si voulu :")
                for name in files:
                    print(f"  - {name}")
            if not apply:
                raise Rollback()
            audit(
                "platform.test_data_purged",
                entity_type="Platform",
                entity_id=0,
                deleted={k.split(".")[-1]: v for k, v in summary.items()},
                files_left=len(files),
            )
    except Stop as exc:
        print(f"ARRET : {exc} Rien n'a ete modifie.")
        return
    except ProtectedError as exc:
        print(f"ARRET : suppression bloquee par une liaison protegee ({exc.args[0][:160]}). Rien n'a ete modifie.")
        return
    except Rollback:
        print("SIMULATION — rien n'a ete modifie. Relancer avec APPLY=1 pour ecrire.")
        return
    print("APPLIQUE : donnees de test supprimees, AuditLog ecrit.")


main()
