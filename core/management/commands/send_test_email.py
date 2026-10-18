"""Envoie un e-mail de test avec la configuration SMTP courante.

    python manage.py send_test_email vous@example.com

Reservee a l'administrateur : une commande de gestion n'est jouable que par qui
a la main sur le serveur (``docker compose exec web python manage.py ...``),
elle n'est exposee par aucune URL. Elle affiche le backend, l'hote, le port et
l'expediteur utilises, JAMAIS les identifiants. Code de sortie != 0 si l'envoi
echoue (SMTP injoignable, authentification refusee...).
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = "Envoie un e-mail de test (SMTP) pour verifier la configuration EMAIL_*."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Adresse du destinataire du test.")

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        try:
            validate_email(recipient)
        except ValidationError as exc:
            raise CommandError(f"Adresse invalide : {recipient!r}") from exc

        backend = settings.EMAIL_BACKEND
        self.stdout.write(f"Backend    : {backend}")
        if "smtp" in backend:
            if settings.EMAIL_USE_SSL:
                mode = "SSL"
            elif settings.EMAIL_USE_TLS:
                mode = "STARTTLS"
            else:
                mode = "clair"
            self.stdout.write(f"SMTP       : {settings.EMAIL_HOST}:{settings.EMAIL_PORT} ({mode})")
        else:
            self.stdout.write(
                self.style.WARNING("Backend non-SMTP : le message ne partira pas vraiment (console/locmem).")
            )
        self.stdout.write(f"Expediteur : {settings.DEFAULT_FROM_EMAIL}")

        try:
            sent = send_mail(
                subject="HayaFlash - e-mail de test",
                message="Si vous lisez ce message, l'envoi d'e-mails depuis HayaFlash fonctionne.",
                from_email=None,  # DEFAULT_FROM_EMAIL
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001 - type + message, sans identifiants
            raise CommandError(f"Echec de l'envoi : {type(exc).__name__}: {exc}") from exc
        if sent != 1:
            raise CommandError("Aucun message envoye.")
        self.stdout.write(self.style.SUCCESS(f"E-mail de test envoye a {recipient}."))
