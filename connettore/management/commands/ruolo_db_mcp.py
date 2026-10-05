"""Utente PostgreSQL del container ``mcp`` (SPEC_MCP §2.2 punto 5, §8.3).

Legge utente e password da ``MCP_DATABASE_URL`` e li crea (o aggiorna la password), poi
riassegna i privilegi da zero: ``SELECT`` su tutte le tabelle; ``INSERT`` e ``UPDATE`` solo
sulle tabelle di dominio che la scrittura dal connettore tocca (e sulle loro storie), sui
token OAuth e sui registri del connettore; ``DELETE`` solo sulle rate (rigenerazione dello
scadenzario) e sui token. Configurazione, utenti e sessioni restano in sola lettura: la
regola «nessuna cancellazione fisica» è imposta anche dal database.
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
    ("connettore", "OperazioneMCP"): "INSERT, UPDATE",
}
# Dominio scritto dai tool del connettore (F10.1): con la storia di ciascuno.
DOMINIO = {
    "Fornitore": "INSERT, UPDATE",
    "Fabbisogno": "INSERT, UPDATE",
    "Contratto": "INSERT, UPDATE",
    "OpzioneContratto": "INSERT, UPDATE",
    "Proroga": "INSERT, UPDATE",
    "VoceContratto": "INSERT, UPDATE",
    "QuotaPeriodo": "INSERT, UPDATE",
    "PianoFatturazione": "INSERT, UPDATE",
    "Rata": "INSERT, UPDATE, DELETE",
    "StatoPratica": "INSERT, UPDATE",
}


def privilegi() -> dict[str, str]:
    """Tabella → privilegi di scrittura dell'utente del connettore."""
    tabelle = {
        apps.get_model(app_label, nome)._meta.db_table: priv
        for (app_label, nome), priv in SCRITTURA.items()
    }
    for nome, priv in DOMINIO.items():
        modello = apps.get_model("contratti", nome)
        tabelle[modello._meta.db_table] = priv
        tabelle[modello.history.model._meta.db_table] = "INSERT"
    return tabelle


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
    for tabella, priv in privilegi().items():
        passi.append(
            sql.SQL("GRANT {} ON TABLE {} TO {}").format(sql.SQL(priv), sql.Identifier(tabella), r)
        )
        passi.append(
            sql.SQL(
                "SELECT format('GRANT USAGE ON SEQUENCE %s TO %I', "
                "pg_get_serial_sequence({}, {}), {})"
            ).format(sql.Literal(tabella), sql.Literal(_chiave(tabella)), sql.Literal(ruolo))
        )
    return passi


def _chiave(tabella: str) -> str:
    """Colonna con la sequenza: ``id``, o ``history_id`` per le tabelle di storia."""
    return "history_id" if tabella.split("_", 1)[1].startswith("historical") else "id"


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
        self.stdout.write(
            f"Utente PostgreSQL {ruolo} {azione}: lettura; scrittura solo su dominio del "
            "connettore, token e registri; cancellazione solo di rate e token."
        )
