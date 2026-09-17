# Generated migration for Orange Money security improvements
# Adds notif_token field and WebhookLog model

import secrets

from django.db import migrations, models
import django.db.models.deletion
import uuid


def backfill_notif_tokens(apps, schema_editor):
    """Assign a unique notif_token to payments created before this field existed."""
    SubscriptionPayment = apps.get_model("subscriptions", "SubscriptionPayment")
    for payment in SubscriptionPayment.objects.filter(notif_token=""):
        payment.notif_token = secrets.token_hex(32)
        payment.save(update_fields=["notif_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0003_rename_sub_pay_order_idx_subscriptio_order_i_4af9d5_idx_and_more"),
    ]

    operations = [
        # Modify SubscriptionPayment model
        migrations.AlterField(
            model_name="subscriptionpayment",
            name="order_id",
            field=models.CharField(
                db_index=True,
                help_text="Identifiant commande Orange Money (max 24 chars)",
                max_length=24,
                unique=True,
            ),
        ),
        migrations.RemoveField(
            model_name="subscriptionpayment",
            name="pay_token",
        ),
        migrations.AddField(
            model_name="subscriptionpayment",
            name="notif_token",
            field=models.CharField(
                db_index=True,
                default="",
                help_text="Token de notification Orange Money (lookup webhook)",
                max_length=128,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_notif_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="subscriptionpayment",
            name="notif_token",
            field=models.CharField(
                db_index=True,
                help_text="Token de notification Orange Money (lookup webhook)",
                max_length=128,
                unique=True,
            ),
        ),
        # Add WebhookLog model
        migrations.CreateModel(
            name="WebhookLog",
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
                ("notif_token", models.CharField(db_index=True, max_length=128)),
                ("status", models.CharField(blank=True, max_length=20)),
                ("txn_id", models.CharField(blank=True, max_length=200)),
                ("raw_payload", models.JSONField()),
                ("processed", models.BooleanField(default=True)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="webhook_logs",
                        to="subscriptions.subscriptionpayment",
                    ),
                ),
            ],
            options={
                "verbose_name": "Log webhook Orange Money",
                "verbose_name_plural": "Logs webhooks Orange Money",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="webhooklog",
            index=models.Index(fields=["notif_token"], name="subscriptions_notif_t_idx"),
        ),
        migrations.AddIndex(
            model_name="webhooklog",
            index=models.Index(
                fields=["payment", "status"], name="subscriptions_payment_status_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="subscriptionpayment",
            index=models.Index(fields=["notif_token"], name="subscriptions_notif_token_idx"),
        ),
    ]
