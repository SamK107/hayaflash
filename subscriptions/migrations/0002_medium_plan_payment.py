from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
        ("accounts", "0004_add_seller_profile_bio_avatar_zones"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subscription",
            name="plan",
            field=models.CharField(
                choices=[("free", "Gratuit"), ("medium", "Medium"), ("pro", "Pro")],
                db_index=True,
                default="free",
                max_length=20,
                verbose_name="Plan",
            ),
        ),
        migrations.CreateModel(
            name="SubscriptionPayment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "plan",
                    models.CharField(
                        choices=[
                            ("free", "Gratuit"),
                            ("medium", "Medium"),
                            ("pro", "Pro"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("orange", "Orange Money"),
                            ("moov", "Moov Money"),
                            ("wave", "Wave"),
                        ],
                        max_length=20,
                    ),
                ),
                ("amount", models.PositiveIntegerField(help_text="Montant en FCFA")),
                ("phone", models.CharField(help_text="Numero paye", max_length=20)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "En attente"),
                            ("success", "Succes"),
                            ("failed", "Echec"),
                            ("cancelled", "Annule"),
                            ("expired", "Expire"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "order_id",
                    models.CharField(db_index=True, max_length=100, unique=True),
                ),
                ("pay_token", models.CharField(blank=True, default="", max_length=200)),
                ("txn_id", models.CharField(blank=True, default="", max_length=200)),
                ("payment_url", models.URLField(blank=True, default="")),
                ("raw_response", models.JSONField(blank=True, default=dict)),
                ("raw_callback", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_payments",
                        to="accounts.sellerprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Paiement abonnement",
                "verbose_name_plural": "Paiements abonnement",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="subscriptionpayment",
            index=models.Index(fields=["order_id"], name="sub_pay_order_idx"),
        ),
        migrations.AddIndex(
            model_name="subscriptionpayment",
            index=models.Index(
                fields=["seller", "status"], name="sub_pay_seller_status_idx"
            ),
        ),
    ]
