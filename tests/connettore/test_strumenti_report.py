"""Tool di report (SPEC_MCP §5): stessi numeri dei report web ed export, al centesimo."""

from decimal import Decimal

import pytest

from accounts.roles import EDITOR
from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import models as m
from contratti import selettori
from reports.budget import LIVELLI, PARTI, VISTE, Filtri, calcola_budget
from reports.piano_ordini import calcola_piano
from reports.wbs import spese_wbs
from tests.connettore.conftest import chiama
from tests.reports.conftest import OGGI

pytestmark = pytest.mark.django_db

NOMI = {"cassa": "fatturato", "impegno": "ordinato", "competenza": "competenza"}


def esegui(utente, nome, argomenti=None):
    risposta, _ = protocollo.gestisci(chiama(nome, argomenti), Contesto(utente, OGGI))
    risultato = risposta["result"]
    assert not risultato.get("isError"), risultato
    return risultato["structuredContent"]


def errore(utente, nome, argomenti=None) -> str:
    risposta, _ = protocollo.gestisci(chiama(nome, argomenti), Contesto(utente, OGGI))
    assert risposta["result"]["isError"] is True
    return risposta["result"]["content"][0]["text"]


@pytest.mark.parametrize("anno", [2026, 2027])
def test_budget_uguale_al_report(archivio, utente_reader, anno):
    dati = esegui(utente_reader, "budget", {"anno": anno, "cluster": ["tutti"]})
    assert [s["natura"] for s in dati["sezioni"]] == ["OPEX", "CAPEX"]
    for sezione in dati["sezioni"]:
        atteso = calcola_budget(Filtri(anno=anno, natura=sezione["natura"]), OGGI).totali()
        for vista in VISTE:
            for parte in PARTI:
                for liv in LIVELLI:
                    assert sezione["totale"][NOMI[vista]][parte][liv.value] == str(
                        atteso[parte][vista][liv]
                    ), (sezione["natura"], vista, parte, liv)


def test_budget_gruppi_sommano_al_totale_della_sezione(archivio, utente_reader):
    dati = esegui(utente_reader, "budget", {"anno": 2027, "cluster": ["tutti"]})
    for sezione in dati["sezioni"]:
        for vista in NOMI.values():
            somma = sum(
                (Decimal(g["importi"][vista]["totale"]) for g in sezione["gruppi"]),
                Decimal("0.00"),
            )
            assert str(somma) == sezione["totale"][vista]["totale"]["probabile"]
    opex, capex = dati["sezioni"]
    assert opex["raggruppato_per"] == "conto" and capex["raggruppato_per"] == "wbs"


def test_budget_filtri_e_dettaglio(archivio, utente_reader):
    solo_capex = esegui(
        utente_reader,
        "budget",
        {"anno": 2026, "natura": "CAPEX", "cluster": ["tutti"], "wbs_a_progetto": "solo"},
    )
    (sezione,) = solo_capex["sezioni"]
    etichette = [g["etichetta"] for g in sezione["gruppi"]]
    assert "WBS-PROVA — Prova" in etichette
    # Solo WBS a progetto: nessun gruppo di WBS di cluster o CAPEX senza WBS.
    assert all(not e.startswith("(") for e in etichette)
    escluse = esegui(
        utente_reader, "budget", {"anno": 2026, "natura": "CAPEX", "cluster": ["tutti"]}
    )
    assert "WBS-PROVA — Prova" not in [g["etichetta"] for g in escluse["sezioni"][0]["gruppi"]]
    dettaglio = esegui(
        utente_reader,
        "budget",
        {"anno": 2026, "natura": "OPEX", "cluster": ["tutti"], "dettaglio_voci": True},
    )
    for g in dettaglio["sezioni"][0]["gruppi"]:
        assert len(g["voci"]) == g["n_voci"]
    assert "budget/?anno=2026" in dettaglio["link"]


def _tutte_le_righe_piano(utente, anno):
    dati = esegui(utente, "piano_ordini", {"anno": anno, "cluster": ["tutti"], "limite": 100})
    righe = list(dati["righe"])
    while dati.get("cursore_successivo"):
        dati = esegui(
            utente,
            "piano_ordini",
            {"anno": anno, "cluster": ["tutti"], "cursore": dati["cursore_successivo"]},
        )
        righe += dati["righe"]
    return righe


def test_piano_ordini_uguale_al_report(archivio, utente_reader):
    dati = esegui(
        utente_reader, "piano_ordini", {"anno": 2027, "cluster": ["tutti"], "limite": 100}
    )
    piano = calcola_piano(2027, OGGI)
    assert dati["totale"] == len(piano.righe)
    for natura, totali in piano.totali_per_natura().items():
        assert dati["totali_per_natura"][natura] == {liv.value: str(totali[liv]) for liv in LIVELLI}
    righe = _tutte_le_righe_piano(utente_reader, 2027)
    assert len(righe) == len(piano.righe)
    # I registrati non hanno data limite: si ordinano per avvio.
    date = [r["data_limite_avvio"] or r["avvio_servizio"] for r in righe]
    assert date == sorted(date)
    previsto = next(r for r in righe if r["fabbisogno"]["descrizione"].startswith("Nuovo"))
    assert previsto["contratto_uscente_id"] is None
    assert previsto["importi"]["fisso"] == "50000.00"
    assert previsto["stato"] == "Previsto" and previsto["sottocluster"] is None
    assert previsto["fonte_finanziamento"] == "Ordinaria"
    assert set(previsto["normalizzato"]) == {"fisso", "probabile", "massimo"}
    registrato = next(r for r in righe if r["fase"] == "registrato")
    assert registrato["contratto_id"] and registrato["data_limite_avvio"] is None
    assert registrato["stato"] in ("In stipula", "Stipulato")


def test_spese_wbs_elenco_e_dettaglio(archivio, utente_reader):
    elenco = esegui(utente_reader, "spese_wbs", {"cluster": ["tutti"], "limite": 100})
    assert "WBS-PROVA" in [w["codice"] for w in elenco["wbs"]]
    dati = esegui(utente_reader, "spese_wbs", {"codice_wbs": "WBS-PROVA", "vista": "ordinato"})
    atteso = spese_wbs(m.WBS.objects.get(codice_wbs="WBS-PROVA"), "impegno")
    assert dati["totale"] == str(atteso.totale)
    assert dati["totali_per_anno"] == {str(a): str(v) for a, v in atteso.totali().items()}
    assert "WBS-INESISTENTE" in errore(
        utente_reader, "spese_wbs", {"codice_wbs": "WBS-INESISTENTE"}
    )


def test_piani_da_verificare_solo_admin_ed_editor(archivio, utente_reader, make_user):
    assert "riservato ad Admin ed Editor" in errore(utente_reader, "piani_da_verificare")
    editor = make_user("redattore", role=EDITOR)
    dati = esegui(editor, "piani_da_verificare", {"cluster": ["tutti"], "limite": 100})
    attese = list(selettori.voci_piano_da_verificare([]))
    assert [v["id"] for v in dati["voci"]] == [v.pk for v in attese][: len(dati["voci"])]
    assert dati["totale"] == len(attese)
    assert dati["totale_peso"] == str(sum((v.peso for v in attese), Decimal("0.00")))


def test_risposta_troppo_grande(archivio, utente_reader, settings):
    settings.MCP_RISPOSTA_MAX_BYTES = 2000
    testo = errore(
        utente_reader, "budget", {"anno": 2027, "cluster": ["tutti"], "dettaglio_voci": True}
    )
    assert "Risultato troppo grande" in testo and "limite" in testo
