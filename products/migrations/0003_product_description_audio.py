from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0002_add_product_fields_and_media"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="description_audio",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="audio/products/",
                verbose_name="Description vocale",
            ),
        ),
    ]
