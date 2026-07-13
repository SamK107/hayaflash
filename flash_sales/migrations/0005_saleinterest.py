from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("flash_sales", "0004_extend_statuts_and_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SaleInterest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("phone", models.CharField(max_length=32, verbose_name="Téléphone")),
                (
                    "name",
                    models.CharField(blank=True, max_length=150, verbose_name="Nom"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "flash_sale",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="interests",
                        to="flash_sales.flashsale",
                        verbose_name="Vente flash",
                    ),
                ),
            ],
            options={
                "verbose_name": "Réservation d'intérêt",
                "verbose_name_plural": "Réservations d'intérêt",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="saleinterest",
            index=models.Index(
                fields=["flash_sale", "created_at"],
                name="flash_sales_flash_s_created_idx",
            ),
        ),
    ]
