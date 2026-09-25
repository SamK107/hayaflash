"""API DRF pour la page "Publication rapide" (gestion en masse des produits
d'une vente flash, catalogue reutilisable entre ventes).

Toutes les routes sont montees sous
`/api/v1/flash-sales/<flash_sale_pk>/products/...` (voir config/api_urls.py)
et n'exposent que les donnees du vendeur authentifie (ownership verifiee via
SellerOwnershipMixin) -- DEFAULT_PERMISSION_CLASSES=IsAuthenticated et le
throttling global (config/settings/base.py) s'appliquent deja.
"""

from __future__ import annotations

import re

from django.db import transaction
from django.db.models import Prefetch, Q
from django.db.models.deletion import ProtectedError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from core.models import audit

from .mixins import SellerOwnershipMixin
from .models import FlashSaleProduct, Product, ProductMedia
from .serializers import (
    FlashSaleProductBulkUpdateSerializer,
    FlashSaleProductSerializer,
    ProductCatalogSerializer,
)
from .services.crud import (
    add_product_image,
    adjust_stock,
    attach_product_to_sale,
    create_product,
)

def _normalize_filename_match(value: str) -> str:
    """Normalise un nom de produit OU un nom de fichier (sans extension)
    pour la comparaison d'auto-rattachement : minuscules, espaces/underscores/
    tirets/espaces multiples tous ramenes a un seul espace. Beaucoup d'OS et
    de telephones remplacent les espaces par `_` ou `-` en enregistrant une
    photo (ex. "carte noir.jpg" -> "carte_noir.jpg") ; sans ca, le
    rattachement automatique echoue silencieusement pour des noms pourtant
    "identiques" du point de vue de l'utilisateur.
    """
    value = value.strip().lower()
    value = re.sub(r"[\s_-]+", " ", value)
    return value.strip()


MAX_BULK_IMAGES = 30
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 Mo -- coherent avec FILE_UPLOAD_MAX_MEMORY_SIZE


class FlashSaleProductViewSet(SellerOwnershipMixin, viewsets.ViewSet):
    """Pas de ModelViewSet classique : les operations sont des actions
    metier (catalog / bulk-update / duplicate-from / bulk-upload-images)
    plutot que du CRUD REST generique sur FlashSaleProduct."""

    def _sale(self, flash_sale_pk):
        return self.get_owned_flash_sale(flash_sale_pk)

    @action(detail=False, methods=["get"], url_path="catalog")
    def catalog(self, request, flash_sale_pk=None):
        """GET .../catalog/ -- catalogue complet du vendeur + etat actuel
        de cette vente, pour pre-remplir la grille Publication rapide."""
        seller = self.get_seller_profile()
        sale = self._sale(flash_sale_pk)

        # Prefetch explicite le plus-recent-d'abord : la grille n'affiche que
        # `media[0]` comme vignette, donc si un produit a plusieurs photos
        # historiques (ordering par defaut du modele = `order` croissant,
        # instable en cas d'egalite), on veut deterministiquement la plus
        # recemment ajoutee plutot qu'une photo potentiellement obsolete.
        media_prefetch = Prefetch(
            "media", queryset=ProductMedia.objects.order_by("-created_at", "-id")
        )
        links_qs = (
            FlashSaleProduct.objects.filter(flash_sale=sale)
            .select_related("product")
            .prefetch_related(
                Prefetch(
                    "product__media",
                    queryset=ProductMedia.objects.order_by("-created_at", "-id"),
                )
            )
            .order_by("display_order", "-created_at")
        )
        linked_product_ids = list(links_qs.values_list("product_id", flat=True))

        catalog_qs = Product.objects.filter(owner=seller).prefetch_related(media_prefetch)
        include_archived = request.query_params.get("include_archived") in ("1", "true", "True")
        if not include_archived:
            # Un produit masque (is_active=False -- "n'existe plus"/"pas
            # encore pret a lancer") n'encombre plus la grille par defaut :
            # c'etait la source de confusion (produits perimes noyant la
            # liste). On garde neanmoins visibles ceux deja lies a CETTE
            # vente, meme masques entretemps, pour ne pas faire disparaitre
            # une ligne deja selectionnee sans explication.
            catalog_qs = catalog_qs.filter(
                Q(is_active=True) | Q(pk__in=linked_product_ids)
            )
        catalog_qs = catalog_qs.order_by("-created_at")

        return Response(
            {
                "catalog": ProductCatalogSerializer(
                    catalog_qs, many=True, context={"request": request}
                ).data,
                "flash_sale_products": FlashSaleProductSerializer(
                    links_qs, many=True, context={"request": request}
                ).data,
                "existing_product_ids": list(
                    links_qs.values_list("product_id", flat=True)
                ),
            }
        )

    @action(detail=False, methods=["post"], url_path="bulk-update")
    def bulk_update(self, request, flash_sale_pk=None):
        """POST .../bulk-update/ -- cree/met a jour en une fois les lignes
        de la grille (produits existants du catalogue et/ou nouveaux
        produits), avec prix promo, stock et ordre propres a cette vente.
        Transaction atomique : soit tout passe, soit rien n'est ecrit.
        """
        seller = self.get_seller_profile()
        sale = self._sale(flash_sale_pk)

        payload = FlashSaleProductBulkUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        mutations = payload.validated_data["mutations"]

        created_count = 0
        updated_count = 0
        errors: list[dict] = []
        touched_link_ids: list[int] = []
        results: list[dict] = []  # {index, product_id} par mutation reussie,
        # dans l'ordre d'envoi -- permet au front de retrouver l'id du
        # produit nouvellement cree pour lui attacher une photo en attente
        # (upload groupe -> nouvelle ligne, cf. FlashSaleProductViewSet.bulk_upload_images).

        try:
            with transaction.atomic():
                for index, mutation in enumerate(mutations):
                    try:
                        product_new = mutation.get("product_new")
                        if product_new:
                            product = create_product(
                                owner=seller,
                                name=product_new["name"],
                                description=product_new.get("description", ""),
                                price=product_new["price"],
                                stock=product_new["stock"],
                                unit=product_new.get("unit", "piece"),
                            )
                            created_count += 1
                        else:
                            product = Product.objects.get(
                                pk=mutation["product_id"], owner=seller
                            )
                            new_stock = mutation.get("stock")
                            if new_stock is not None:
                                adjust_stock(
                                    product=product, new_stock_available=new_stock
                                )
                            updated_count += 1

                        fsp = attach_product_to_sale(
                            flash_sale=sale,
                            product=product,
                            promo_price=mutation.get("promo_price"),
                            display_order=mutation.get("display_order", 0),
                            is_active=mutation.get("is_active", True),
                        )
                        touched_link_ids.append(fsp.pk)
                        results.append({"index": index, "product_id": product.pk})

                        audit(
                            "flashsaleproduct.bulk_update",
                            entity_type="FlashSaleProduct",
                            entity_id=fsp.pk,
                            actor=request.user,
                            request=request,
                            operation="create" if product_new else "update",
                            product_id=product.pk,
                            flash_sale_id=sale.pk,
                            is_admin_action=request.user.is_staff,
                            acting_for_seller_id=seller.pk,
                        )
                    except Product.DoesNotExist:
                        errors.append(
                            {
                                "index": index,
                                "product_id": mutation.get("product_id"),
                                "error": "Produit introuvable pour ce vendeur.",
                            }
                        )
                    except Exception as exc:  # validation metier (create_product, etc.)
                        errors.append(
                            {
                                "index": index,
                                "product_id": mutation.get("product_id"),
                                "error": str(exc),
                            }
                        )

                if errors:
                    # Aucune mutation partielle : une ligne en erreur annule
                    # tout le lot (comportement explicite, pas de succes
                    # partiel silencieux sur une operation groupee).
                    raise _BulkValidationFailed(errors)
        except _BulkValidationFailed:
            return Response(
                {
                    "detail": "Certaines lignes sont invalides, aucune modification enregistrée.",
                    "errors": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        links = FlashSaleProduct.objects.filter(pk__in=touched_link_ids).select_related(
            "product"
        )
        return Response(
            {
                "created_count": created_count,
                "updated_count": updated_count,
                "results": results,
                "flash_sale_products": FlashSaleProductSerializer(
                    links, many=True, context={"request": request}
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="duplicate-from")
    def duplicate_from(self, request, flash_sale_pk=None):
        """POST .../duplicate-from/ {"previous_sale_id": N} -- reprend la
        liste de produits (+ prix promo) d'une vente precedente du meme
        vendeur comme point de depart pour la vente courante."""
        seller = self.get_seller_profile()
        sale = self._sale(flash_sale_pk)

        previous_sale_id = request.data.get("previous_sale_id")
        if not previous_sale_id:
            return Response(
                {"detail": "previous_sale_id est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        previous_sale = self.get_owned_flash_sale(previous_sale_id)
        if previous_sale.pk == sale.pk:
            return Response(
                {"detail": "Impossible de dupliquer une vente sur elle-même."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        with transaction.atomic():
            previous_links = FlashSaleProduct.objects.filter(
                flash_sale=previous_sale, is_active=True
            ).select_related("product")
            for link in previous_links:
                fsp, was_created = FlashSaleProduct.objects.get_or_create(
                    flash_sale=sale,
                    product=link.product,
                    defaults={
                        "promo_price": link.promo_price,
                        "display_order": link.display_order,
                        "is_active": True,
                    },
                )
                if was_created:
                    created.append(fsp.pk)

            audit(
                "flashsale.duplicate_products",
                entity_type="FlashSale",
                entity_id=sale.pk,
                actor=request.user,
                request=request,
                from_sale_id=previous_sale.pk,
                count=len(created),
                is_admin_action=request.user.is_staff,
                acting_for_seller_id=seller.pk,
            )

        links = FlashSaleProduct.objects.filter(flash_sale=sale).select_related("product")
        return Response(
            {
                "duplicated_count": len(created),
                "flash_sale_products": FlashSaleProductSerializer(
                    links, many=True, context={"request": request}
                ).data,
            }
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="assign-image",
        parser_classes=[MultiPartParser, FormParser],
    )
    def assign_image(self, request, flash_sale_pk=None):
        """POST .../assign-image/ (multipart: `file` + `product_id`) --
        attache une photo a UN produit precis du catalogue, sans passer par
        le matching de nom de fichier. Utilise par le bouton photo de
        chaque ligne de la grille : c'est le filet de secours quand
        l'auto-assignation par nom (bulk-upload-images) ne trouve pas de
        correspondance."""
        seller = self.get_seller_profile()
        self._sale(flash_sale_pk)  # verifie juste l'ownership de la vente

        product_id = request.data.get("product_id")
        file = request.FILES.get("file")
        if not product_id or not file:
            return Response(
                {"detail": "product_id et file sont requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            product = Product.objects.get(pk=product_id, owner=seller)
        except Product.DoesNotExist:
            return Response(
                {"detail": "Produit introuvable pour ce vendeur."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if file.size > MAX_IMAGE_BYTES:
            return Response(
                {"detail": "Fichier > 5 Mo."}, status=status.HTTP_400_BAD_REQUEST
            )
        if not (file.content_type or "").startswith("image/"):
            return Response(
                {"detail": "Type de fichier non-image."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Remplace toute photo existante plutot que d'en empiler une nouvelle :
        # la grille n'affiche qu'une seule vignette par ligne (media[0]), donc
        # accumuler plusieurs ProductMedia avec le meme `order=0` rendait le
        # choix de "la" photo affichee ambigu/instable (une ancienne pouvait
        # masquer la nouvelle apres rafraichissement de la page).
        ProductMedia.objects.filter(product=product).delete()
        media = add_product_image(product=product, image_file=file, order=0)
        return Response(
            {
                "media_id": media.pk,
                "product_id": product.pk,
                "url": request.build_absolute_uri(media.file.url)
                if media.file
                else None,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-upload-images",
        parser_classes=[MultiPartParser, FormParser],
    )
    def bulk_upload_images(self, request, flash_sale_pk=None):
        """POST .../bulk-upload-images/ (multipart, champ `files` +
        optionnel `product_order`) -- upload groupe d'images produits.

        Deux mecanismes d'auto-assignation, dans cet ordre :
        1. Nom de fichier (convention: <nom-du-produit>.jpg) -- pratique
           quand les fichiers sont deja bien nommes, mais peu fiable en
           pratique (photos prises directement au telephone -> IMG_1234.jpg).
        2. Position -- `product_order` est la liste ordonnee des product_id
           actuellement affiches dans la grille (envoyee par le front),
           reproduisant l'ordre dans lequel le vendeur a pris/depose ses
           photos. Les fichiers non rattaches par le nom sont assignes dans
           cet ordre aux produits qui n'ont pas encore de photo -- aucun
           renommage de fichier requis, c'est le mecanisme principal recommande.

        Le redimensionnement passe par le hook existant sur
        ProductMedia.save() (core.services.image_optimize), pas de logique
        dupliquee ici."""
        import json
        import os

        seller = self.get_seller_profile()
        self._sale(flash_sale_pk)  # verifie juste l'ownership de la vente

        files = request.FILES.getlist("files")
        if not files:
            return Response(
                {"detail": "Aucun fichier reçu (champ 'files')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(files) > MAX_BULK_IMAGES:
            return Response(
                {"detail": f"Maximum {MAX_BULK_IMAGES} fichiers par envoi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_order = request.data.get("product_order")
        ordered_ids: list[int] = []
        if raw_order:
            try:
                ordered_ids = [int(pid) for pid in json.loads(raw_order)]
            except (ValueError, TypeError):
                ordered_ids = []

        catalog = list(Product.objects.filter(owner=seller).prefetch_related("media"))
        catalog_by_id = {p.pk: p for p in catalog}
        catalog_by_name = {_normalize_filename_match(p.name): p for p in catalog}

        # File d'attente positionnelle : les produits de `product_order`
        # (dans l'ordre donne par le front) qui n'ont pas deja de photo --
        # ce sont les "emplacements vides" que les fichiers non rattaches
        # par le nom viendront combler, un par un, dans l'ordre d'envoi.
        position_queue = [
            catalog_by_id[pid]
            for pid in ordered_ids
            if pid in catalog_by_id and not catalog_by_id[pid].media.exists()
        ]

        uploads = []
        errors = []
        used_product_ids: set[int] = set()

        for f in files:
            if f.size > MAX_IMAGE_BYTES:
                errors.append({"filename": f.name, "error": "Fichier > 5 Mo."})
                continue
            if not (f.content_type or "").startswith("image/"):
                errors.append({"filename": f.name, "error": "Type de fichier non-image."})
                continue

            filename_base = _normalize_filename_match(os.path.splitext(f.name)[0])
            matched_product = catalog_by_name.get(filename_base)
            match_kind = "filename" if matched_product else None

            if matched_product is None:
                while position_queue:
                    candidate = position_queue.pop(0)
                    if candidate.pk in used_product_ids:
                        continue
                    matched_product = candidate
                    match_kind = "position"
                    break

            if matched_product is None:
                # ProductMedia.product est obligatoire (pas de null=True) :
                # sans correspondance (nom ou position), on ne cree rien et
                # on renvoie l'erreur -- l'assignation manuelle se fait cote
                # UI (bouton photo sur la ligne) une fois le produit choisi.
                errors.append(
                    {
                        "filename": f.name,
                        "error": (
                            "Aucun produit du catalogue ne correspond (nom ou "
                            "position) ; assignez l'image manuellement."
                        ),
                    }
                )
                continue

            used_product_ids.add(matched_product.pk)
            # Une seule photo par produit dans cette grille : on remplace
            # plutot que d'empiler (ambigu/instable si plusieurs photos a
            # `order` egal pour le meme produit).
            ProductMedia.objects.filter(product=matched_product).delete()

            media = ProductMedia(
                product=matched_product,
                media_type=ProductMedia.MediaType.IMAGE,
                alt_text=os.path.splitext(f.name)[0],
                order=0,
            )
            media.file = f
            media.save()
            uploads.append(
                {
                    "filename": f.name,
                    "media_id": media.pk,
                    "url": request.build_absolute_uri(media.file.url)
                    if media.file
                    else None,
                    "auto_assigned_product_id": matched_product.pk,
                    "match_kind": match_kind,  # "filename" ou "position"
                }
            )

        return Response(
            {"uploads": uploads, "errors": errors},
            status=status.HTTP_201_CREATED if uploads else status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["post"], url_path="archive-product")
    def archive_product(self, request, flash_sale_pk=None):
        """POST .../archive-product/ {"product_id": N, "is_active": bool} --
        masque/reaffiche un produit du catalogue SANS le supprimer (garde
        l'historique de commandes intact). Un produit masque n'apparait
        plus par defaut dans la grille Publication rapide (cf. `catalog`),
        mais reste visible/reactivable via `?include_archived=1`."""
        seller = self.get_seller_profile()
        self._sale(flash_sale_pk)  # verifie juste l'ownership de la vente

        product_id = request.data.get("product_id")
        is_active = request.data.get("is_active", False)
        if isinstance(is_active, str):
            is_active = is_active.lower() in ("1", "true")
        try:
            product = Product.objects.get(pk=product_id, owner=seller)
        except (Product.DoesNotExist, TypeError, ValueError):
            return Response(
                {"detail": "Produit introuvable pour ce vendeur."},
                status=status.HTTP_404_NOT_FOUND,
            )

        product.is_active = bool(is_active)
        product.save(update_fields=["is_active"])
        audit(
            "product.archive" if not is_active else "product.unarchive",
            entity_type="Product",
            entity_id=product.pk,
            actor=request.user,
            request=request,
            is_admin_action=request.user.is_staff,
            acting_for_seller_id=seller.pk,
        )
        return Response({"product_id": product.pk, "is_active": product.is_active})

    @action(detail=False, methods=["post"], url_path="delete-product")
    def delete_product(self, request, flash_sale_pk=None):
        """POST .../delete-product/ {"product_id": N} -- suppression
        definitive d'un produit du catalogue (ex. doublon, erreur de saisie,
        produit qui n'existe plus du tout). Protegee automatiquement par
        Django (on_delete=PROTECT sur Order/OrderItem.product) des qu'une
        commande existe pour ce produit -- dans ce cas, on renvoie une
        erreur explicite invitant a masquer plutot que supprimer."""
        seller = self.get_seller_profile()
        self._sale(flash_sale_pk)  # verifie juste l'ownership de la vente

        product_id = request.data.get("product_id")
        try:
            product = Product.objects.get(pk=product_id, owner=seller)
        except (Product.DoesNotExist, TypeError, ValueError):
            return Response(
                {"detail": "Produit introuvable pour ce vendeur."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            with transaction.atomic():
                product.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Ce produit a déjà des commandes associées et ne peut "
                        "pas être supprimé définitivement ; masquez-le à la place."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        audit(
            "product.delete",
            entity_type="Product",
            entity_id=product_id,
            actor=request.user,
            request=request,
            is_admin_action=request.user.is_staff,
            acting_for_seller_id=seller.pk,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class _BulkValidationFailed(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("bulk validation failed")
