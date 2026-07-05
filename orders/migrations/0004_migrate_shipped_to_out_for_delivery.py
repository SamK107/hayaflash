from django.db import migrations


def forwards_shipped_to_out_for_delivery(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(status="shipped").update(status="out_for_delivery")


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0003_order_total_amount_alter_order_status"),
    ]

    operations = [
        migrations.RunPython(
            forwards_shipped_to_out_for_delivery,
            migrations.RunPython.noop,
        ),
    ]
