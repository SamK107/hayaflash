from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "flash_sales",
            "0006_rename_flash_sales_flash_s_created_idx_flash_sales_flash_s_4bd4c8_idx",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="flashsale",
            name="description_audio",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="audio/sales/",
                verbose_name="Description vocale",
            ),
        ),
    ]
