"""Contrainte CHECK : aucun stock négatif (produits et variantes).

Garde-fou contre la survente au niveau base. La migration vérifie d'abord les
données : si une ligne a déjà un stock négatif, elle ÉCHOUE explicitement avec
la liste des lignes, sans rien modifier (transaction annulée). Il faut alors
corriger les données à la main, puis relancer la migration.

Requête de contrôle équivalente (à lancer avant déploiement) :
    SELECT 'product', id, stock_available FROM products_product WHERE stock_available < 0
    UNION ALL
    SELECT 'variant', id, stock FROM products_productvariant WHERE stock < 0;
"""

from django.db import migrations, models


def _verifier_aucun_stock_negatif(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    ProductVariant = apps.get_model("products", "ProductVariant")

    negatifs = [
        f"produit #{pk} (stock_available={valeur})"
        for pk, valeur in Product.objects.filter(stock_available__lt=0)
        .values_list("pk", "stock_available")
    ] + [
        f"variante #{pk} (stock={valeur})"
        for pk, valeur in ProductVariant.objects.filter(stock__lt=0).values_list(
            "pk", "stock"
        )
    ]
    if negatifs:
        raise RuntimeError(
            "Migration products.0011 interrompue : stock négatif existant, "
            "corriger les données avant de relancer. Lignes : " + ", ".join(negatifs)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0010_alter_product_description_audio_and_more"),
    ]

    operations = [
        migrations.RunPython(
            _verifier_aucun_stock_negatif,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=models.Q(("stock_available__gte", 0)),
                name="product_stock_available_non_negatif",
            ),
        ),
        migrations.AddConstraint(
            model_name="productvariant",
            constraint=models.CheckConstraint(
                condition=models.Q(("stock__gte", 0)),
                name="productvariant_stock_non_negatif",
            ),
        ),
    ]
