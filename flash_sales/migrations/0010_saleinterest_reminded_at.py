from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("flash_sales", "0009_flashsale_teasers"),
    ]

    operations = [
        migrations.AddField(
            model_name="saleinterest",
            name="reminded_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Rempli automatiquement quand le rappel SMS a été envoyé.",
                null=True,
                verbose_name="Rappel envoyé le",
            ),
        ),
    ]
