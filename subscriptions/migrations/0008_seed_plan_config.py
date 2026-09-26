"""Migration de donnees : les 3 lignes PlanConfig, depuis les constantes
historiques (FREE 0 / 3, MEDIUM 2000 / 10, PRO 5000 / illimite, 31 jours).

Valeurs recopiees ici (et non importees de services/plans.py) : une
migration doit rester figee meme si les valeurs de secours du code changent.
Les listes de fonctionnalites n'incluent pas la ligne du quota (« 10 ventes
flash par mois ») : elle est generee depuis monthly_sales_limit.
"""

from django.db import migrations

PLANS = [
    {
        "plan": "free",
        "price": 0,
        "monthly_sales_limit": 3,
        "features": [
            "Page publique vendeur",
            "Commandes en ligne",
            "Lien de partage WhatsApp",
        ],
    },
    {
        "plan": "medium",
        "price": 2000,
        "monthly_sales_limit": 10,
        "features": [
            "Statistiques de ventes (30 derniers jours)",
            "Historique des commandes complet",
            "Page publique vendeur",
            "Commandes en ligne",
            "Lien de partage WhatsApp",
        ],
    },
    {
        "plan": "pro",
        "price": 5000,
        "monthly_sales_limit": None,
        "features": [
            "Statistiques et analyses avancées (historique complet)",
            "Tableau de bord LIVE temps réel",
            "Notifications SMS automatiques",
            "Support prioritaire WhatsApp",
            "Accès aux nouvelles fonctionnalités en avant-première",
        ],
    },
]


def seed(apps, schema_editor):
    PlanConfig = apps.get_model("subscriptions", "PlanConfig")
    for row in PLANS:
        PlanConfig.objects.get_or_create(
            plan=row["plan"],
            defaults={
                "price": row["price"],
                "monthly_sales_limit": row["monthly_sales_limit"],
                "duration_days": 31,
                "features": row["features"],
                "is_active": True,
            },
        )


def unseed(apps, schema_editor):
    apps.get_model("subscriptions", "PlanConfig").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0007_tarifs_administrables_schema")]

    operations = [migrations.RunPython(seed, unseed)]
