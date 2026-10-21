"""JSON-RPC del connettore (SPEC_MCP §3) e serializzazione (§5), senza HTTP."""

import datetime
from decimal import Decimal

import pytest

from connettore import protocollo, schema, serializza
from connettore.strumenti import STRUMENTI, Contesto

pytestmark = pytest.mark.django_db


@pytest.fixture
def ctx(utente_reader):
    return Contesto(utente_reader, datetime.date(2026, 10, 5))


def richiesta(metodo, params=None, id_=7):
    messaggio = {"jsonrpc": "2.0", "id": id_, "method": metodo}
    if params is not None:
        messaggio["params"] = params
    return messaggio


@pytest.mark.parametrize(
    ("chiesta", "data"),
    [("2025-11-25", "2025-11-25"), ("2025-06-18", "2025-06-18"), ("2099-01-01", "2025-11-25")],
)
def test_negoziazione_della_versione(ctx, chiesta, data):
    risposta, _ = protocollo.gestisci(richiesta("initialize", {"protocolVersion": chiesta}), ctx)
    assert risposta["id"] == 7
    assert risposta["result"]["protocolVersion"] == data
    assert risposta["result"]["serverInfo"]["name"] == "registro-contratti-ictdinn"


def test_ping(ctx):
    assert protocollo.gestisci(richiesta("ping"), ctx)[0] == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {},
    }


def test_tools_list_sola_lettura(ctx):
    risposta, _ = protocollo.gestisci(richiesta("tools/list"), ctx)
    tools = risposta["result"]["tools"]
    # Reader: niente «fornitore» e «piani_da_verificare», come le pagine dell'interfaccia.
    assert [t["name"] for t in tools] == [
        "riferimenti",
        "cerca",
        "scadenze",
        "contratto",
        "fabbisogno",
        "scadenzario",
        "budget",
        "piano_ordini",
        "spese_wbs",
        # F12.1: processo d'acquisto (SPEC_MCP §11.2), tutti i ruoli.
        "rda",
        "elenco_rda",
        "fattura",
        "elenco_fatture",
        "esecuzione",
        "cruscotto_acquisti",
        "contratti_da_chiudere",
        "stanziamenti",  # Rev22
        "anomalie_esecuzione",
    ]
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["inputSchema"]["type"] == "object"
        assert t["inputSchema"]["additionalProperties"] is False
        assert t["description"]


@pytest.mark.parametrize(
    ("messaggio", "codice"),
    [
        (richiesta("resources/list"), protocollo.METHOD_NOT_FOUND),
        (richiesta("tools/call", {"name": "cancella_tutto"}), protocollo.INVALID_PARAMS),
        ({"jsonrpc": "1.0", "id": 1, "method": "ping"}, protocollo.INVALID_REQUEST),
        ([richiesta("ping")], protocollo.INVALID_REQUEST),  # niente batch (2025-06-18)
        ({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []}, protocollo.INVALID_REQUEST),
    ],
)
def test_errori_di_protocollo(ctx, messaggio, codice):
    risposta, esito = protocollo.gestisci(messaggio, ctx)
    assert risposta["error"]["code"] == codice
    assert esito.esito == "errore_protocollo"


def test_notifiche_senza_risposta(ctx):
    risposta, esito = protocollo.gestisci(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, ctx
    )
    assert risposta is None
    assert esito.metodo == "notifications/initialized"


def test_ogni_schema_e_valido_per_il_validatore():
    for s in STRUMENTI.values():
        schema.valida({}, {**s.input_schema, "required": []})


def test_importi_stringhe_con_due_decimali():
    assert serializza.importo(Decimal("1234.5")) == "1234.50"
    assert serializza.importo(Decimal("0.005")) == "0.01"  # ROUND_HALF_UP
    assert serializza.in_json({"a": [Decimal("1"), datetime.date(2026, 12, 31)]}) == {
        "a": ["1.00", "2026-12-31"]
    }


def test_float_vietato():
    with pytest.raises(TypeError, match="float"):
        serializza.in_json({"importo": 1.5})
