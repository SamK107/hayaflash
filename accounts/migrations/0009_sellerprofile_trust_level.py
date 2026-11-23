from django.db import migrations, models

# Niveau de confiance des boutiques (D10). Sans RunPython, non destructive :
# - AddField avec default=1 : toute boutique existante passe au niveau 1 (vérifiée basique) ;
# - AlterField avec default=0 : toute nouvelle boutique naît au niveau 0 (non vérifiée).
# Le default de base de données disparaît après le AddField (Django ne le conserve pas).

_CHOICES = [
    (0, "Non vérifiée"),
    (1, "Vérifiée (basique)"),
    (2, "Vérifiée (renforcée)"),
]
_HELP = "0 non vérifiée, 1 vérifiée, 2 vérifiée renforcée. Visible par l'équipe seulement."


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_shopreport"),
    ]

    operations = [
        migrations.AddField(
            model_name="sellerprofile",
            name="trust_level",
            field=models.PositiveSmallIntegerField(
                choices=_CHOICES,
                default=1,
                help_text=_HELP,
                verbose_name="Niveau de confiance",
            ),
        ),
        migrations.AlterField(
            model_name="sellerprofile",
            name="trust_level",
            field=models.PositiveSmallIntegerField(
                choices=_CHOICES,
                default=0,
                help_text=_HELP,
                verbose_name="Niveau de confiance",
            ),
        ),
    ]
