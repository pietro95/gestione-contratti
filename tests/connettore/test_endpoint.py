"""Endpoint /mcp: token, ruolo, limite, protocollo HTTP, registro (SPEC_MCP §4, §6, §7)."""

import json
from decimal import Decimal

import pytest

from connettore.models import RegistroChiamata
from contratti import models as m
from tests.connettore.conftest import HOST_PUBBLICO, chiama

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_mcp")]

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "prova", "version": "0"},
    },
}


def test_senza_token_401_con_metadati_della_risorsa(mcp_post):
    r = mcp_post(INIT)
    assert r.status_code == 401
    assert r["WWW-Authenticate"].startswith("Bearer ")
    assert (
        'resource_metadata="https://mcp.esempio.test/.well-known/oauth-protected-resource"'
        in r["WWW-Authenticate"]
    )
    assert RegistroChiamata.objects.get().esito == "non_autorizzata"


def test_token_non_valido_401(mcp_post):
    r = mcp_post(INIT, token="token-inventato")
    assert r.status_code == 401
    assert 'error="invalid_token"' in r["WWW-Authenticate"]


def test_token_scaduto_401(mcp_post, utente_reader, crea_token):
    assert mcp_post(INIT, token=crea_token(utente_reader, scade_tra=-1)).status_code == 401


def test_token_senza_scope_di_lettura_403(mcp_post, utente_reader, crea_token):
    r = mcp_post(INIT, token=crea_token(utente_reader, scope="altro"))
    assert r.status_code == 403
    assert 'error="insufficient_scope"' in r["WWW-Authenticate"]


def test_token_nella_query_string_rifiutato(client, utente_reader, crea_token):
    token = crea_token(utente_reader)
    r = client.post(
        f"/mcp?access_token={token}",
        data=INIT,
        content_type="application/json",
        HTTP_HOST=HOST_PUBBLICO,
        secure=True,
    )
    assert r.status_code == 401


def test_initialize_e_versione(mcp_post, utente_reader, crea_token):
    r = mcp_post(INIT, token=crea_token(utente_reader))
    assert r.status_code == 200
    risultato = r.json()["result"]
    assert risultato["protocolVersion"] == "2025-11-25"
    assert risultato["capabilities"] == {"tools": {"listChanged": False}}
    assert "Mcp-Session-Id" not in r  # nessuna sessione lato server


def test_notifica_202_senza_corpo(mcp_post, utente_reader, crea_token):
    notifica = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    r = mcp_post(notifica, token=crea_token(utente_reader))
    assert r.status_code == 202
    assert r.content == b""


@pytest.mark.parametrize("metodo", ["get", "delete", "put"])
def test_solo_post(client, metodo):
    r = getattr(client, metodo)("/mcp", HTTP_HOST=HOST_PUBBLICO, secure=True)
    assert r.status_code == 405
    assert r["Allow"] == "POST"


def test_utente_senza_ruolo_403(mcp_post, make_user, crea_token):
    senza = make_user("senza-ruolo")
    r = mcp_post(INIT, token=crea_token(senza))
    assert r.status_code == 403
    assert RegistroChiamata.objects.get().messaggio == "ruolo"


def test_breakglass_403(mcp_post, make_user, crea_token):
    emergenza = make_user("emergenza", role="Admin", is_breakglass=True)
    assert mcp_post(INIT, token=crea_token(emergenza)).status_code == 403


def test_utente_disattivato_rifiutato(mcp_post, utente_reader, crea_token):
    token = crea_token(utente_reader)
    utente_reader.is_active = False
    utente_reader.save()
    assert mcp_post(INIT, token=token).status_code in (401, 403)


def test_origin_estranea_403(mcp_post, utente_reader, crea_token):
    token = crea_token(utente_reader)
    assert mcp_post(INIT, token=token, HTTP_ORIGIN="https://attaccante.example").status_code == 403
    assert mcp_post(INIT, token=token, HTTP_ORIGIN="https://mcp.esempio.test").status_code == 200


def test_versione_protocollo_non_supportata_400(mcp_post, utente_reader, crea_token):
    r = mcp_post(INIT, token=crea_token(utente_reader), HTTP_MCP_PROTOCOL_VERSION="1999-01-01")
    assert r.status_code == 400


def test_json_non_valido(client, utente_reader, crea_token):
    r = client.post(
        "/mcp",
        data="{non json",
        content_type="application/json",
        HTTP_HOST=HOST_PUBBLICO,
        HTTP_AUTHORIZATION=f"Bearer {crea_token(utente_reader)}",
        secure=True,
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700


def test_limite_di_frequenza(mcp_post, utente_reader, crea_token):
    m.Parametro.objects.filter(chiave="mcp_richieste_minuto").update(valore=Decimal("2"))
    token = crea_token(utente_reader)
    assert mcp_post(INIT, token=token).status_code == 200
    assert mcp_post(INIT, token=token).status_code == 200
    r = mcp_post(INIT, token=token)
    assert r.status_code == 429
    assert r["Retry-After"] == "60"
    # Il limite è per collegamento: un altro token dello stesso utente passa.
    assert mcp_post(INIT, token=crea_token(utente_reader)).status_code == 200


def test_registro_senza_token_in_chiaro(mcp_post, utente_reader, crea_token):
    token = crea_token(utente_reader)
    mcp_post(chiama("cerca", {"testo": "nessun risultato atteso"}), token=token)
    riga = RegistroChiamata.objects.get()
    assert (riga.utente, riga.metodo, riga.tool, riga.esito) == (
        utente_reader,
        "tools/call",
        "cerca",
        "ok",
    )
    assert riga.argomenti == {"testo": "nessun risultato atteso"}
    assert riga.client_id
    assert token not in json.dumps(list(RegistroChiamata.objects.values()), default=str)
    from oauth2_provider.models import AccessToken

    assert not AccessToken.objects.filter(token=token).exists()  # solo l'hash nel database


def test_connettore_spento_404(mcp_post, settings, utente_reader, crea_token):
    settings.MCP_URL_PUBBLICO = ""
    assert mcp_post(INIT, token=crea_token(utente_reader)).status_code == 404


def test_errore_interno_non_espone_dettagli(mcp_post, utente_reader, crea_token, monkeypatch):
    from connettore import strumenti

    def esplode(ctx, argomenti):
        raise RuntimeError("dettaglio interno")

    s = strumenti.STRUMENTI["riferimenti"]
    monkeypatch.setitem(
        strumenti.STRUMENTI,
        "riferimenti",
        strumenti.Strumento(s.nome, s.titolo, s.descrizione, s.input_schema, esplode),
    )
    r = mcp_post(chiama("riferimenti"), token=crea_token(utente_reader))
    assert r.status_code == 200
    errore = r.json()["error"]
    # Al client solo il tipo dell'eccezione, mai il testo (può contenere dettagli del database).
    assert errore["code"] == -32603 and errore["message"].startswith(
        "Errore interno (RuntimeError)"
    )
    assert "dettaglio interno" not in r.content.decode()


def test_tool_con_link_dal_container_pubblico(mcp_post, utente_reader, crea_token, archivio):
    """I link si costruiscono con la URLconf interna anche sull'host pubblico."""
    token = crea_token(utente_reader)
    for nome, argomenti in [
        ("contratto", {"id": archivio.pk}),
        ("fabbisogno", {"id": archivio.fabbisogno_id}),
        ("budget", {"anno": 2027, "cluster": ["tutti"]}),
        ("piano_ordini", {"anno": 2027, "cluster": ["tutti"]}),
        ("spese_wbs", {"codice_wbs": "WBS-PROVA"}),
        ("scadenzario", {"contratto_id": archivio.pk}),
    ]:
        r = mcp_post(chiama(nome, argomenti), token=token)
        risultato = r.json()["result"]
        assert not risultato.get("isError"), (nome, risultato)
        assert risultato["structuredContent"]["link"].startswith("https://contratti.esempio.test/")


def test_scrittura_via_http_solo_con_lo_scope(mcp_post, make_user, crea_token):
    """Lo scope del token decide: senza «registro.scrittura» niente tool di scrittura."""
    editor = make_user("redattore", role="Editor")
    elenco = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

    def nomi(token):
        return {t["name"] for t in mcp_post(elenco, token=token).json()["result"]["tools"]}

    solo_lettura = crea_token(editor)
    con_scrittura = crea_token(editor, scope="registro.lettura registro.scrittura")
    assert "crea_fornitore" not in nomi(solo_lettura)
    assert {"crea_fornitore", "conferma_operazione"} <= nomi(con_scrittura)
    r = mcp_post(chiama("crea_fornitore", {"ragione_sociale": "Via HTTP"}), token=solo_lettura)
    assert r.json()["result"]["isError"] is True
    anteprima = mcp_post(
        chiama("crea_fornitore", {"ragione_sociale": "Via HTTP"}), token=con_scrittura
    ).json()["result"]["structuredContent"]
    esito = mcp_post(
        chiama("conferma_operazione", {"id_operazione": anteprima["id_operazione"]}),
        token=con_scrittura,
    ).json()["result"]["structuredContent"]
    assert esito["esito"] == "eseguita"
    from contratti.models import Fornitore

    assert Fornitore.objects.get(ragione_sociale="Via HTTP").history.get().history_user == editor
    assert list(
        RegistroChiamata.objects.filter(tool__in=["crea_fornitore", "conferma_operazione"])
        .order_by("timestamp")
        .values_list("tool", "esito")
    ) == [
        ("crea_fornitore", "errore_tool"),
        ("crea_fornitore", "ok"),
        ("conferma_operazione", "ok"),
    ]


def test_errore_interno_indica_il_tipo_e_registra_il_testo(
    mcp_post, utente_reader, crea_token, monkeypatch
):
    from connettore import protocollo

    def guasto(*args, **kwargs):
        raise ValueError("segreto del database")

    monkeypatch.setattr(protocollo, "gestisci", guasto)
    r = mcp_post(INIT, token=crea_token(utente_reader))
    testo = r.json()["error"]["message"]
    assert "ValueError" in testo and "segreto" not in testo  # al client solo il tipo
    assert "segreto del database" in RegistroChiamata.objects.latest("pk").messaggio
