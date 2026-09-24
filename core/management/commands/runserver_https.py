"""Serveur de dev en HTTPS (certificat mkcert) pour tester la PWA sur mobile.

Chrome n'installe une PWA que sur une origine securisee (https, ou localhost).
Pour tester depuis un telephone sur le meme Wi-Fi sans ngrok :

    python manage.py runserver_https --settings=config.settings.dev
    -> https://<IP du PC>:8443/

Au premier lancement, le certificat est genere dans `.certs/` via `mkcert`
(localhost, 127.0.0.1 + IP locales du PC), et refait automatiquement quand
l'IP du PC change (`--regen-cert` pour forcer). Le telephone doit faire confiance a l'autorite mkcert : voir
docs/DEV_HTTPS_MOBILE.md. Dev uniquement (refuse si DEBUG=False).
"""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticRunserverCommand,
)
from django.core.management.base import CommandError
from django.core.servers.basehttp import WSGIServer

CERT_DIR = Path(settings.BASE_DIR) / ".certs"
CERT_FILE = CERT_DIR / "hayaflash-dev.pem"
KEY_FILE = CERT_DIR / "hayaflash-dev-key.pem"
# Noms couverts par le certificat : s'ils ne couvrent plus les IP actuelles du
# PC (autre Wi-Fi, partage de connexion, DHCP), le certificat est refait.
# Sinon le telephone voit une erreur de certificat, et Chrome ne propose
# JAMAIS l'installation de la PWA sur une page en erreur de certificat.
HOSTS_FILE = CERT_DIR / "hosts.txt"


def local_ipv4s() -> list[str]:
    """IPv4 locales du poste (hors loopback), sans trafic reseau."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        # Interface de la route par defaut (UDP : aucun paquet n'est envoye).
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


class SecureWSGIServer(WSGIServer):
    """WSGIServer de runserver, socket enveloppe en TLS + environ HTTPS=on."""

    ssl_context: ssl.SSLContext | None = None

    def server_bind(self):
        super().server_bind()
        # Poignee de main TLS faite dans le thread de la requete (pas dans la
        # boucle d'accept) : un client lent ou en http ne bloque pas le serveur.
        self.socket = self.ssl_context.wrap_socket(
            self.socket, server_side=True, do_handshake_on_connect=False
        )

    def setup_environ(self):
        super().setup_environ()
        # wsgi.url_scheme = https -> request.is_secure(), URLs absolues, CSRF.
        self.base_environ["HTTPS"] = "on"

    def handle_error(self, request, client_address):
        # Client qui parle http sur le port https, certificat refuse, etc.
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError)):
            return
        super().handle_error(request, client_address)


class Command(StaticRunserverCommand):
    help = "runserver en HTTPS (mkcert) pour tester la PWA sur mobile via le Wi-Fi local."
    default_addr = "0.0.0.0"
    default_port = "8443"
    protocol = "https"
    server_cls = SecureWSGIServer

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--regen-cert",
            action="store_true",
            help="Regenerer le certificat mkcert (ex. apres un changement d'IP).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("runserver_https est reserve au developpement (DEBUG=True).")
        hosts = ["localhost", "127.0.0.1", *local_ipv4s()]
        covered = HOSTS_FILE.read_text().split() if HOSTS_FILE.exists() else []
        missing = [h for h in hosts if h not in covered]
        if options["regen_cert"] or missing or not (CERT_FILE.exists() and KEY_FILE.exists()):
            if missing and covered:
                self.stdout.write(f"Nouvelle IP detectee ({', '.join(missing)}) : certificat refait.")
            self._make_cert(hosts)
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(CERT_FILE, KEY_FILE)
        SecureWSGIServer.ssl_context = ctx
        super().handle(*args, **options)

    def _make_cert(self, hosts):
        mkcert = shutil.which("mkcert")
        if not mkcert and sys.platform == "win32":
            # Installe via winget mais pas (encore) dans le PATH de ce terminal.
            found = sorted(
                (Path.home() / "AppData/Local/Microsoft/WinGet/Packages").glob(
                    "FiloSottile.mkcert_*/mkcert.exe"
                )
            )
            mkcert = str(found[0]) if found else None
        if not mkcert:
            raise CommandError(
                "mkcert introuvable. Installez-le (winget install FiloSottile.mkcert), "
                "lancez une fois `mkcert -install`, puis relancez cette commande."
            )
        CERT_DIR.mkdir(exist_ok=True)
        self.stdout.write(f"Generation du certificat mkcert pour : {', '.join(hosts)}")
        subprocess.run(
            [mkcert, "-cert-file", str(CERT_FILE), "-key-file", str(KEY_FILE), *hosts],
            check=True,
        )
        HOSTS_FILE.write_text(" ".join(hosts))

    def on_bind(self, server_port):
        super().on_bind(server_port)
        self.stdout.write(self.style.SUCCESS("HTTPS actif :"))
        for host in ["localhost", *local_ipv4s()]:
            self.stdout.write(f"  https://{host}:{server_port}/")
