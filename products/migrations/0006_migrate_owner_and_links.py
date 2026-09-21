from __future__ import annotations

from django.db import migrations


def migrate_owner_and_links(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    FlashSaleProduct = apps.get_model("products", "FlashSaleProduct")

    products = Product.objects.filter(flash_sale_id__isnull=False).select_related(
        "flash_sale"
    )
    to_update = []
    links_to_create = []
    for product in products:
        if product.owner_id is None:
            product.owner_id = product.flash_sale.owner_id
            to_update.append(product)
        links_to_create.append(
            FlashSaleProduct(
                flash_sale_id=product.flash_sale_id,
                product_id=product.pk,
                promo_price=None,
                display_order=product.display_order,
                is_active=product.is_active,
            )
        )

    if to_update:
        Product.objects.bulk_update(to_update, ["owner_id"], batch_size=500)

    if links_to_create:
        FlashSaleProduct.objects.bulk_create(
            links_to_create,
            batch_size=500,
            ignore_conflicts=True,  # unique_together (flash_sale, product) -- idempotent si relance
        )

    # Produits orphelins (vente historique supprimee, flash_sale_id deja NULL
    # via SET_NULL) : owner ne peut pas etre inferee, on les laisse tels
    # quels (owner=None) plutot que de fabriquer une donnee inventee. Ils
    # resteront invisibles du catalogue (les vues filtrent par owner) mais
    # ne sont pas supprimes : on ne perd aucun historique de commande.


def reverse_migrate_owner_and_links(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    FlashSaleProduct = apps.get_model("products", "FlashSaleProduct")

    FlashSaleProduct.objects.all().delete()
    Product.objects.filter(flash_sale_id__isnull=False).update(owner_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0005_owner_and_flashsaleproduct"),
    ]

    operations = [
        migrations.RunPython(
            migrate_owner_and_links, reverse_migrate_owner_and_links
        ),
    ]
