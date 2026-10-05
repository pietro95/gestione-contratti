"""Tool di dettaglio (SPEC_MCP §5): contratto, fabbisogno, fornitore, scadenzario."""

from decimal import Decimal

import pytest

from accounts.roles import EDITOR
from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import adapters
from contratti import models as m
from tests.connettore.conftest import chiama
from tests.reports.conftest import OGGI

pytestmark = pytest.mark.django_db


def esegui(utente, nome, argomenti=None):
    risposta, _ = protocollo.gestisci(chiama(nome, argomenti), Contesto(utente, OGGI))
    risultato = risposta["result"]
    assert not risultato.get("isError"), risultato
    return risultato["structuredContent"]


def errore(utente, nome, argomenti=None) -> str:
    risposta, _ = protocollo.gestisci(chiama(nome, argomenti), Contesto(utente, OGGI))
    assert risposta["result"]["isError"] is True
    return risposta["result"]["content"][0]["text"]


def test_contratto(archivio, utente_reader):
    c = archivio
    dati = esegui(utente_reader, "contratto", {"id": c.pk})
    assert dati["id"] == c.pk and isinstance(dati["versione"], int)
    assert dati["data_fine"] == "2028-06-30"  # con la proroga
    assert dati["data_fine_contrattuale"] == "2027-12-31"
    assert [p["nuova_data_fine"] for p in dati["proroghe"]] == ["2028-06-30"]
    assert [x["id"] for x in dati["catena"] if x["questo"]] == [c.pk]
    canone = next(v for v in dati["voci"] if v["proroga"] is None)
    assert canone["natura"] == "CAPEX" and canone["wbs"]["codice"] == "WBS-PROVA"
    assert canone["valori"] == {"fisso": "12000.00", "probabile": "13500.00", "massimo": "15000.00"}
    assert canone["piano_fatturazione"]["modalita"] == "posticipata"
    somma = sum(Decimal(v["valori"]["probabile"]) for v in dati["voci"])
    assert dati["totali"]["probabile"] == str(somma)
    assert "note" not in dati


def test_contratto_inesistente(utente_reader):
    assert "Nessun contratto con id 999999" in errore(utente_reader, "contratto", {"id": 999999})


def test_scadenzario(archivio, utente_reader):
    dati = esegui(utente_reader, "scadenzario", {"contratto_id": archivio.pk})
    canone = next(v for v in dati["voci"] if v["rate"])
    assert len(canone["rate"]) == 8  # trimestrale posticipata su 24 mesi
    assert canone["totale_rate"] == "12000.00" and canone["quadra_con_il_fisso"] is True
    assert "entrambi" in errore(
        utente_reader, "scadenzario", {"contratto_id": archivio.pk, "voce_id": 1}
    )


def test_fabbisogno(archivio, utente_reader):
    f = archivio.fabbisogno
    dati = esegui(utente_reader, "fabbisogno", {"id": f.pk})
    assert [c["id"] for c in dati["contratti"]] == [archivio.pk]
    attesi = adapters.previsti_fabbisogno(f, adapters.orizzonte_default(OGGI))
    assert [p["inizio"] for p in dati["previsti"]] == [p.inizio.isoformat() for p in attesi]
    assert "referente" not in dati and "note" not in dati
    nuovo = m.Fabbisogno.objects.get(descrizione="Nuovo servizio previsto a mano")
    manuale = esegui(utente_reader, "fabbisogno", {"id": nuovo.pk})
    assert manuale["previsto_manuale"]["data_avvio"] == "2027-03-01"
    assert manuale["previsti"][0]["importi"]["fisso"] == "50000.00"


def test_fornitore_solo_admin_ed_editor(archivio, utente_reader, make_user):
    assert "riservato" in errore(utente_reader, "fornitore", {"id": archivio.fornitore_id})
    editor = make_user("redattore", role=EDITOR)
    dati = esegui(editor, "fornitore", {"id": archivio.fornitore_id})
    assert archivio.pk in [c["id"] for c in dati["contratti"]]


def test_tools_list_per_ruolo(utente_reader, make_user):
    def nomi(utente):
        risposta, _ = protocollo.gestisci(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, Contesto(utente, OGGI)
        )
        return {t["name"] for t in risposta["result"]["tools"]}

    editor = make_user("redattore", role=EDITOR)
    assert nomi(editor) - nomi(utente_reader) == {"fornitore", "piani_da_verificare"}
    assert len(nomi(editor)) == 11
