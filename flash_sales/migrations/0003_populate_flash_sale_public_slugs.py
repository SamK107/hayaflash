from __future__ import annotations

from django.db import migrations


def populate_flash_sale_slugs(apps, schema_editor):
    FlashSale = apps.get_model("flash_sales", "FlashSale")
    from flash_sales.services.slugs import generate_unique_flash_sale_public_slug

    for sale in FlashSale.objects.filter(public_slug="").iterator():
        sale.public_slug = generate_unique_flash_sale_public_slug(sale)
        sale.save(update_fields=["public_slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("flash_sales", "0002_flashsale_public_slug"),
    ]

    operations = [
        migrations.RunPython(populate_flash_sale_slugs, migrations.RunPython.noop),
    ]
