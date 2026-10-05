"""Utente PostgreSQL del container ``mcp`` (SPEC_MCP §2.2, punto 5).

Legge utente e password da ``MCP_DATABASE_URL`` e li crea (o aggiorna la password), poi
riassegna i privilegi da zero: ``SELECT`` su tutte le tabelle; scrittura solo sui token OAuth
e sul registro delle chiamate. Una falla di lettura non diventa una falla di scrittura.
Si esegue a ogni deploy, dopo le migration, così le tabelle nuove ricevono i privilegi.
"""

import environ
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg import sql

# Tabelle in cui il container mcp scrive, con i privilegi necessari. Lo scambio del codice
# cancella il grant; la rotazione del refresh cancella il vecchio access token.
SCRITTURA = {
    ("oauth2_provider", "Grant"): "INSERT, UPDATE, DELETE",
    ("oauth2_provider", "AccessToken"): "INSERT, UPDATE, DELETE",
    ("oauth2_provider", "RefreshToken"): "INSERT, UPDATE, DELETE",
    ("oauth2_provider", "IDToken"): "INSERT, UPDATE, DELETE",
    ("connettore", "RegistroChiamata"): "INSERT",
}


def istruzioni(ruolo: str, password: str, esiste: bool, database: str) -> list[sql.Composable]:
    r = sql.Identifier(ruolo)
    verbo = sql.SQL("ALTER ROLE") if esiste else sql.SQL("CREATE ROLE")
    passi = [
        sql.SQL("{} {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION").format(
            verbo, r, sql.Literal(password)
        ),
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), r),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r),
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(r),
        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(r),
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(r),
    ]
    for (app_label, nome), privilegi in SCRITTURA.items():
        tabella = apps.get_model(app_label, nome)._meta.db_table
        passi.append(
            sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                sql.SQL(privilegi), sql.Identifier(tabella), r
            )
        )
        passi.append(
            sql.SQL(
                "SELECT format('GRANT USAGE ON SEQUENCE %s TO %I', "
                "pg_get_serial_sequence({}, 'id'), {})"
            ).format(sql.Literal(tabella), sql.Literal(ruolo))
        )
    return passi


class Command(BaseCommand):
    help = "Crea o aggiorna l'utente PostgreSQL limitato del container mcp (MCP_DATABASE_URL)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url", help="URL del database dell'utente mcp (default: MCP_DATABASE_URL)."
        )

    def handle(self, *args, **options):
        url = options["url"] or environ.Env().str("MCP_DATABASE_URL", default="")
        if not url:
            raise CommandError("MCP_DATABASE_URL non impostata: connettore senza utente limitato.")
        config = environ.Env.db_url_config(url)
        ruolo, password = config.get("USER"), config.get("PASSWORD")
        if not ruolo or not password:
            raise CommandError("MCP_DATABASE_URL deve contenere utente e password.")
        if ruolo == connection.settings_dict["USER"]:
            raise CommandError("L'utente mcp deve essere diverso dal proprietario del database.")
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [ruolo])
            esiste = cursor.fetchone() is not None
            database = connection.settings_dict["NAME"]
            pg = connection.connection
            for passo in istruzioni(ruolo, password, esiste, database):
                testo = passo.as_string(pg)
                cursor.execute(testo)
                if testo.startswith("SELECT format("):
                    cursor.execute(cursor.fetchone()[0])
        azione = "aggiornato" if esiste else "creato"
        self.stdout.write(f"Utente PostgreSQL {ruolo} {azione}: lettura, scrittura solo sui token.")
