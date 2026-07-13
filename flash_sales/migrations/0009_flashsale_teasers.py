from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("flash_sales", "0008_alter_flashsale_description_audio"),
    ]

    operations = [
        migrations.AddField(
            model_name="flashsale",
            name="teasers",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Un teaser par ligne. Ex: 8 sacs de luxe · 15 montres · 5 parfums",
                verbose_name="Teasers page d'attente",
            ),
        ),
    ]
