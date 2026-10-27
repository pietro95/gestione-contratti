"""Tool di report e voci a SAL (SPEC_MCP §5, Rev11): consuntivo e previsto separati, anomalie,
SAL non pianificato nel budget."""

import datetime
from decimal import Decimal

import pytest

from contratti import models as m
from tests import factories as f
from tests.connettore.test_strumenti_report import esegui

pytestmark = pytest.mark.django_db
D = datetime.date
FISSO = Decimal("2947639.75")


@pytest.fixture
def lavori():
    wbs = m.WBS.objects.create(codice_wbs="P.0001.01.0001", descrizione="Automazione impianto")
    c = f.contratto(
        fabbisogno=f.fabbisogno("Lavori impianto"),
        data_inizio=D(2024, 10, 15),
        durata_mesi=29,
        data_fine_override=D(2027, 3, 31),
        numero_contratto="5800000230",
    )
    voce = f.voce(c, descrizione="Lavori", natura="CAPEX", wbs=wbs, importo_fisso=FISSO)
    f.piano(voce, modalita="sal", periodicita="")
    return {"wbs": wbs, "contratto": c, "voce": voce}


def _riga(dati, voce):
    (riga,) = [r for r in dati["righe"] if r["voce"]["id"] == voce.pk]
    return riga


def test_spese_wbs_con_quote_separa_il_previsto(utente_reader, lavori):
    for anno, importo in ((2025, "1486870.87"), (2026, "1144060.62"), (2027, "316708.26")):
        m.QuotaPeriodo.objects.create(
            voce=lavori["voce"], dal=D(anno, 1, 1), al=D(anno, 12, 31), importo=Decimal(importo)
        )
    dati = esegui(utente_reader, "spese_wbs", {"wbs_id": lavori["wbs"].pk, "cluster": ["tutti"]})
    riga = _riga(dati, lavori["voce"])
    assert riga["per_anno"] == {"2025": "1486870.87", "2026": "1144060.62", "2027": "316708.26"}
    assert riga["consuntivo_per_anno"] == {}
    assert riga["previsto_per_anno"] == riga["per_anno"]
    assert riga["non_pianificato"] == "0.00"
    assert riga["fonte"] == "SAL: quote per periodo"
    assert "SAL: fatture registrate" in dati["fonte_della_vista"]
    assert dati["totali_previsto_per_anno"]["2027"] == "316708.26"
    assert dati["sal_non_pianificato"] == "0.00"


def test_spese_wbs_con_fatture_e_anomalia_di_wbs(utente_reader, lavori):
    altra = m.WBS.objects.create(codice_wbs="P.0002.01.0001", descrizione="Altro")
    c = lavori["contratto"]
    for i, (data, importo, wbs) in enumerate(
        [(D(2025, 5, 1), "1000000.00", None), (D(2026, 5, 1), "500000.00", altra)], start=1
    ):
        m.Fattura.objects.create(
            fornitore=c.fornitore, contratto=c, voce=lavori["voce"], numero=f"F-{i}", data=data,
            importo_documento=Decimal(importo), valore_base=Decimal(importo), wbs=wbs,
        )  # fmt: skip
    dati = esegui(utente_reader, "spese_wbs", {"wbs_id": lavori["wbs"].pk, "cluster": ["tutti"]})
    riga = _riga(dati, lavori["voce"])
    assert riga["consuntivo_per_anno"] == {"2025": "1000000.00"}  # la seconda è sull'altra WBS
    assert Decimal(riga["non_pianificato"]) == FISSO - Decimal("1500000.00")
    assert len(dati["anomalie"]) == 1 and "P.0002.01.0001" in dati["anomalie"][0]
    assert any("SAL non pianificato" in a for a in riga["avvisi"])
    altra_dati = esegui(utente_reader, "spese_wbs", {"wbs_id": altra.pk, "cluster": ["tutti"]})
    assert _riga(altra_dati, lavori["voce"])["consuntivo_per_anno"] == {"2026": "500000.00"}


def test_budget_segnala_il_sal_non_pianificato(utente_reader, lavori):
    # La WBS a progetto è fuori dal budget dei cluster, salvo richiesta.
    argomenti = {"anno": 2026, "cluster": ["tutti"], "wbs_a_progetto": "incluse"}
    assert "sal_non_pianificato" not in esegui(utente_reader, "budget", argomenti | {
        "wbs_a_progetto": "escluse"})  # fmt: skip
    dati = esegui(utente_reader, "budget", argomenti)
    assert dati["sal_non_pianificato"]["totale"] == str(FISSO)
    (voce,) = dati["sal_non_pianificato"]["voci"]
    assert voce["voce_id"] == lavori["voce"].pk and voce["natura"] == "CAPEX"
