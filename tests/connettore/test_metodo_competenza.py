"""Connettore MCP: la competenza è a mesi frazionati e il tool lo dichiara (SPEC_MCP, Rev31)."""

import datetime
from decimal import Decimal

import pytest

from tests import factories as f
from tests.connettore.test_strumenti_report import esegui

pytestmark = pytest.mark.django_db
D = datetime.date
CANONE = Decimal("6500.00")


@pytest.fixture
def dpo():
    """Due contratti contigui da 12 mesi con lo stesso canone, a cavallo di un anno bisestile."""
    fab = f.fabbisogno("Servizio DPO", decisione="dismettere")
    for inizio in (D(2026, 6, 8), D(2027, 6, 8)):
        c = f.contratto(fabbisogno=fab, data_inizio=inizio, durata_mesi=12)
        f.piano(f.voce(c, importo_fisso=CANONE), modalita="anticipata", periodicita="annuale")
    return fab


def _competenza(dati, livello="fisso"):
    (sezione,) = [s for s in dati["sezioni"] if s["natura"] == "OPEX"]
    totale = sezione["totale"]["competenza"]["totale"]
    return Decimal(totale[livello])


def test_budget_competenza_2027_e_il_canone_e_dichiara_il_metodo(dpo, utente_reader):
    dati = esegui(utente_reader, "budget", {"anno": 2027, "cluster": ["tutti"], "previsti": False})
    assert _competenza(dati) == CANONE
    assert dati["metodo_competenza"]["metodo"] == "mesi_frazionati"
    assert "giorni coperti / giorni del mese" in dati["metodo_competenza"]["descrizione"]
    assert "28/02" in dati["metodo_competenza"]["limite_noto"]
    assert "mesi frazionati" in dati["viste"]["competenza"]


def test_budget_2026_e_2028_quadrano_con_il_2027(dpo, utente_reader):
    valori = {
        anno: _competenza(
            esegui(utente_reader, "budget", {"anno": anno, "cluster": ["tutti"], "previsti": False})
        )
        for anno in (2026, 2027, 2028)
    }
    assert valori == {2026: Decimal("3665.28"), 2027: CANONE, 2028: Decimal("2834.72")}


def test_i_tool_dichiarano_il_metodo_nelle_descrizioni(utente_reader):
    from connettore.strumenti.report import STRUMENTI

    testo = {s.nome: s.descrizione for s in STRUMENTI}
    for nome in ("budget", "piano_ordini", "piani_da_verificare"):
        assert "mesi frazionati" in testo[nome], nome
    assert "giorni" not in testo["budget"].lower().replace("giorni di", "")


def test_piano_ordini_e_fabbisogno_dichiarano_il_metodo(dpo, utente_reader):
    piano = esegui(utente_reader, "piano_ordini", {"anno": 2027, "cluster": ["tutti"]})
    assert piano["metodo_competenza"]["metodo"] == "mesi_frazionati"
    dati = esegui(utente_reader, "fabbisogno", {"id": dpo.pk})
    assert dati["metodo_competenza"]["metodo"] == "mesi_frazionati"
