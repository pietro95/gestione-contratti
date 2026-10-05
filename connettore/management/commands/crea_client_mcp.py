"""Crea un client OAuth per il connettore MCP (SPEC_MCP §4.3). Nessuna registrazione dinamica.

    manage.py crea_client_mcp claude        # app di Claude (claude.ai, Desktop, mobile, Cowork)
    manage.py crea_client_mcp claude-code   # Claude Code (client pubblico, redirect loopback)

Il secret si mostra una volta sola: nel database c'è solo il suo hash.
"""

from django.core.management.base import BaseCommand
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import get_application_model

TIPI = {
    "claude": {
        "nome": "Claude",
        "client_type": "confidential",
        "redirect_uris": (
            "https://claude.ai/api/mcp/auth_callback https://claude.com/api/mcp/auth_callback"
        ),
    },
    "claude-code": {
        "nome": "Claude Code",
        "client_type": "public",
        # Porta qualunque (RFC 8252): la sceglie Claude Code a ogni collegamento.
        "redirect_uris": "http://localhost/callback http://127.0.0.1/callback",
    },
}


class Command(BaseCommand):
    help = "Crea il client OAuth di Claude o di Claude Code per il connettore MCP."

    def add_arguments(self, parser):
        parser.add_argument("tipo", choices=sorted(TIPI))
        parser.add_argument("--nome", help="Nome mostrato nella pagina di consenso.")

    def handle(self, *args, **options):
        tipo = TIPI[options["tipo"]]
        Application = get_application_model()
        app = Application(
            name=options["nome"] or tipo["nome"],
            client_type=tipo["client_type"],
            authorization_grant_type="authorization-code",
            redirect_uris=tipo["redirect_uris"],
            algorithm="",
        )
        secret = ""
        if tipo["client_type"] == "confidential":
            secret = generate_client_secret()
            app.client_secret = secret
        else:
            app.client_secret = ""
        app.full_clean()
        app.save()
        self.stdout.write(f"Client creato: {app.name}")
        self.stdout.write(f"  client ID:     {app.client_id}")
        if secret:
            self.stdout.write(f"  client secret: {secret}")
            self.stdout.write("  Il secret non si potrà rileggere: copiarlo ora (RUNBOOK §12).")
        else:
            self.stdout.write("  Client pubblico: nessun secret (Claude Code usa PKCE).")
