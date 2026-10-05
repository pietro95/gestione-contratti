"""Utente PostgreSQL del container mcp (SPEC_MCP §2.2, punto 5): legge tutto, scrive solo token."""

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

pytestmark = pytest.mark.django_db

RUOLO = "contratti_mcp_test"
URL = f"postgres://{RUOLO}:password-di-prova@localhost:5432/qualsiasi"


def privilegio(tabella: str, tipo: str) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT has_table_privilege(%s, %s, %s)", [RUOLO, tabella, tipo])
        return c.fetchone()[0]


def test_privilegi(capsys):
    # CREATE ROLE è transazionale: il ruolo sparisce con il rollback del test.
    call_command("ruolo_db_mcp", url=URL)
    assert "creato" in capsys.readouterr().out
    for tabella in ("contratti_contratto", "contratti_rata", "accounts_user", "django_session"):
        assert privilegio(tabella, "SELECT")
        for tipo in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not privilegio(tabella, tipo), (tabella, tipo)
    for tabella in ("oauth2_provider_accesstoken", "oauth2_provider_refreshtoken"):
        assert privilegio(tabella, "INSERT") and privilegio(tabella, "DELETE")
    assert privilegio("connettore_registrochiamata", "INSERT")
    assert not privilegio("connettore_registrochiamata", "UPDATE")
    assert not privilegio("connettore_registrochiamata", "DELETE")
    assert not privilegio("oauth2_provider_application", "UPDATE")


def test_rieseguibile(capsys):
    call_command("ruolo_db_mcp", url=URL)
    call_command("ruolo_db_mcp", url=URL)
    assert "aggiornato" in capsys.readouterr().out
    assert not privilegio("contratti_contratto", "UPDATE")


def test_rifiuta_il_proprietario_del_database():
    proprietario = connection.settings_dict["USER"]
    with pytest.raises(CommandError, match="diverso dal proprietario"):
        call_command("ruolo_db_mcp", url=f"postgres://{proprietario}:x@localhost/db")


def test_senza_url():
    with pytest.raises(CommandError, match="MCP_DATABASE_URL"):
        call_command("ruolo_db_mcp")
