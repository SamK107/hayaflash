"""Import, allocation et reprise de stock (spec §5.3, §15.6).

Les produits sont crees par les services `products` existants, APPELES sans etre modifies.
Pour le stock d'un produit EXISTANT, `products.services.crud.adjust_stock` n'est PAS utilise : il ne
verrouille pas la ligne et fixe une valeur absolue lue en memoire (voir distrib/README.md § b). On
verrouille donc ici (`select_for_update`), on borne sous verrou, on ecrit en `F()` et on laisse un
`StockMovement(CORRECTION)` comme le fait le service existant.

Chaque operation est atomique : stock, `allocated_qty` et journal bougent ensemble ou pas du tout.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from core.models import audit
from distrib.models import (
    AllocationMovement,
    ImportedProduct,
    ResellerInvite,
    WholesaleProduct,
)
from distrib.services import ceilings
from distrib.services.catalog import available_qty
from products.models import Product, StockMovement
from products.services.crud import add_product_image, create_product

logger = logging.getLogger(__name__)


# ── Regles communes ───────────────────────────────────────────────────────


def _whole_positive(value, label: str) -> int:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValidationError(f"{label} : valeur invalide.") from exc
    if amount != amount.to_integral_value() or amount <= 0:
        raise ValidationError(f"{label} doit être un nombre entier supérieur à 0.")
    return int(amount)


def _assert_new_stock_allowed(invite: ResellerInvite) -> None:
    """Conditions pour une NOUVELLE importation ou allocation (jamais pour une reprise)."""
    distributor = invite.distributor
    if not distributor.is_active:
        raise ValidationError("Ce grossiste n'est plus actif.")
    if distributor.is_suspended:
        raise ValidationError(
            "Le compte du grossiste est suspendu : les nouvelles importations et allocations sont bloquées."
        )
    if invite.status != ResellerInvite.Status.ACCEPTED or invite.seller_id is None:
        raise ValidationError("Ce revendeur n'est plus rattaché à ce grossiste.")
    reason = ceilings.allocation_block_reason(distributor, invite)
    if reason:
        raise ValidationError(reason)


def sold_qty(imported: ImportedProduct) -> int:
    """Unites sorties du stock de la boutique (vendues ou reservees, hors annulations)."""
    return max(0, imported.allocated_qty - imported.product.stock_available)


# ── Import ────────────────────────────────────────────────────────────────


def _copy_images(*, wholesale_product: WholesaleProduct, product: Product) -> None:
    """Copie les fichiers (jamais partages) en `ProductMedia`. Best-effort : une photo
    manquante sur le disque ne bloque pas l'import (meme philosophie que l'audio de livraison)."""
    for index, source in enumerate(wholesale_product.images.all()):
        try:
            source.image.open("rb")
            try:
                content = source.image.read()
            finally:
                source.image.close()
            name = source.image.name.rsplit("/", 1)[-1]
            add_product_image(product=product, image_file=ContentFile(content, name=name), order=index)
        except Exception:
            logger.exception("distrib: photo %s non copiee vers le produit %s", source.pk, product.pk)


def import_product(
    *,
    invite: ResellerInvite,
    wholesale_product: WholesaleProduct,
    retail_price,
    actor=None,
    quantity: int = 0,
) -> ImportedProduct:
    """Cree dans la boutique du revendeur un produit lie au catalogue de gros.

    La quantite est fixee par le GROSSISTE (spec §5.3, reglage V1) : l'import cree le produit
    avec le stock alloue (0 par defaut) et le grossiste alloue ensuite via `allocate`.
    `quantity > 0` n'est utilise que pour une allocation initiale decidee par le grossiste.
    """
    retail = _whole_positive(retail_price, "Le prix de vente")
    if wholesale_product.distributor_id != invite.distributor_id:
        raise ValidationError("Ce produit n'appartient pas à ce grossiste.")
    if quantity < 0:
        raise ValidationError("La quantité ne peut pas être négative.")

    with transaction.atomic():
        wp = WholesaleProduct.objects.select_for_update().get(pk=wholesale_product.pk)
        invite = ResellerInvite.objects.select_related("distributor", "seller").get(pk=invite.pk)
        _assert_new_stock_allowed(invite)
        if not wp.is_active:
            raise ValidationError("Ce produit n'est plus proposé par le grossiste.")
        if retail < wp.min_retail_price:
            raise ValidationError(
                "Le prix de vente ne peut pas être inférieur au minimum du grossiste "
                f"({int(wp.min_retail_price)} FCFA)."
            )
        if ImportedProduct.objects.filter(wholesale_product=wp, invite=invite).exists():
            raise ValidationError("Ce produit est déjà dans votre boutique.")
        if quantity > available_qty(wp):
            raise ValidationError(f"Il ne reste que {available_qty(wp)} unité(s) disponible(s).")

        product = create_product(
            owner=invite.seller,
            name=wp.name,
            price=retail,
            stock=quantity,
            description=wp.description,
        )
        _copy_images(wholesale_product=wp, product=product)
        imported = ImportedProduct.objects.create(
            wholesale_product=wp, invite=invite, product=product, allocated_qty=quantity
        )
        if quantity:
            AllocationMovement.objects.create(
                imported_product=imported, quantity_change=quantity,
                reason="Allocation initiale", created_by=actor,
            )
        audit(
            "distrib.product_imported",
            entity_type="ImportedProduct",
            entity_id=imported.pk,
            actor=actor,
            product_id=product.pk,
            wholesale_product_id=wp.pk,
            quantity=quantity,
        )
    return imported


# ── Allocation et reprise ─────────────────────────────────────────────────


def allocate(*, imported: ImportedProduct, quantity, actor=None, reason: str = "") -> ImportedProduct:
    """Alloue `quantity` unites de plus au revendeur (jamais au-dela du disponible grossiste)."""
    qty = _whole_positive(quantity, "La quantité")
    with transaction.atomic():
        # Ordre de verrouillage fixe (catalogue puis produit) pour eviter les verrous croises.
        wp = WholesaleProduct.objects.select_for_update().get(pk=imported.wholesale_product_id)
        imported = ImportedProduct.objects.select_related("invite__distributor", "invite__seller").get(
            pk=imported.pk
        )
        Product.objects.select_for_update().get(pk=imported.product_id)
        _assert_new_stock_allowed(imported.invite)
        available = available_qty(wp)
        if qty > available:
            raise ValidationError(
                f"Il ne reste que {available} unité(s) disponible(s) chez vous : impossible d'en allouer {qty}."
            )
        _move_stock(imported=imported, delta=qty, actor=actor, reason=reason or "Allocation par le grossiste")
    imported.refresh_from_db()
    return imported


def take_back(*, imported: ImportedProduct, quantity, actor=None, reason: str = "") -> ImportedProduct:
    """Reprend des unites NON VENDUES : au plus le stock encore disponible dans la boutique.

    Toujours possible (grossiste suspendu, revendeur revoque ou plafond depasse compris)."""
    qty = _whole_positive(quantity, "La quantité")
    with transaction.atomic():
        WholesaleProduct.objects.select_for_update().get(pk=imported.wholesale_product_id)
        imported = ImportedProduct.objects.get(pk=imported.pk)
        product = Product.objects.select_for_update().get(pk=imported.product_id)
        limit = min(product.stock_available, imported.allocated_qty)
        if qty > limit:
            raise ValidationError(
                f"Seulement {max(limit, 0)} unité(s) non vendue(s) à reprendre : le reste est déjà commandé."
            )
        _move_stock(imported=imported, delta=-qty, actor=actor, reason=reason or "Reprise par le grossiste")
    imported.refresh_from_db()
    return imported


def _move_stock(*, imported: ImportedProduct, delta: int, actor, reason: str) -> None:
    """Ecrit stock boutique, `allocated_qty`, mouvement de stock et journal. Verrous deja poses."""
    now = timezone.now()
    if delta > 0:
        Product.objects.filter(pk=imported.product_id).update(
            stock_available=F("stock_available") + delta,
            stock_initial=F("stock_initial") + delta,
            updated_at=now,
        )
    else:
        Product.objects.filter(pk=imported.product_id).update(
            stock_available=F("stock_available") + delta,
            stock_initial=Greatest(F("stock_initial") + delta, 0),
            updated_at=now,
        )
    ImportedProduct.objects.filter(pk=imported.pk).update(allocated_qty=F("allocated_qty") + delta)
    StockMovement.objects.create(
        product_id=imported.product_id,
        quantity_change=delta,
        movement_type=StockMovement.MovementType.CORRECTION,
        notes=reason,
    )
    AllocationMovement.objects.create(
        imported_product=imported, quantity_change=delta, reason=reason, created_by=actor
    )
    audit(
        "distrib.stock_allocated" if delta > 0 else "distrib.stock_taken_back",
        entity_type="ImportedProduct",
        entity_id=imported.pk,
        actor=actor,
        quantity=abs(delta),
    )


# ── Lecture : alertes de prix minimum (§5.3) ──────────────────────────────


def imports_below_minimum(distributor):
    """Produits importes dont le prix catalogue de la boutique est passe sous le minimum.
    Alerte seulement (pas de blocage en V1) ; affichee par les tableaux de bord en P8."""
    return ImportedProduct.objects.filter(
        invite__distributor=distributor, product__price__lt=F("wholesale_product__min_retail_price")
    ).select_related("product", "wholesale_product", "invite")
