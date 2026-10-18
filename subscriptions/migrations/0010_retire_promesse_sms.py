"""Migration de donnees (D3) : retire « Notifications SMS automatiques » des
fonctionnalites du plan Pro. Aucun SMS n'est envoye au lancement : la liste
affichee aux vendeuses ne doit pas le promettre.

Seule cette ligne est retiree ; les autres textes (eventuellement modifies dans
l'administration) restent intacts. Retour arriere : la ligne est remise en place
si elle manque.
"""

from django.db import migrations

PHRASE = "Notifications SMS automatiques"


def retirer(apps, schema_editor):
    PlanConfig = apps.get_model("subscriptions", "PlanConfig")
    for config in PlanConfig.objects.all():
        features = list(config.features or [])
        kept = [f for f in features if f != PHRASE]
        if kept != features:
            config.features = kept
            config.save(update_fields=["features"])


def remettre(apps, schema_editor):
    PlanConfig = apps.get_model("subscriptions", "PlanConfig")
    for config in PlanConfig.objects.filter(plan="pro"):
        features = list(config.features or [])
        if PHRASE not in features:
            features.insert(2 if len(features) >= 2 else len(features), PHRASE)
            config.features = features
            config.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0009_webhooklog_payment_nullable")]
    operations = [migrations.RunPython(retirer, remettre)]
