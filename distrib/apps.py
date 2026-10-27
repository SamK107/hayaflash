from django.apps import AppConfig


class DistribConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "distrib"
    verbose_name = "Distrib (grossistes)"

    def ready(self):
        # distrib LIT orders ; orders n'importe jamais distrib (spec §2.1).
        from django.db.models.signals import post_save

        from orders.models import Order

        from . import signals

        post_save.connect(signals.order_saved, sender=Order, dispatch_uid="distrib_order_saved")
