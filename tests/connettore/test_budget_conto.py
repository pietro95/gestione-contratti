"""Connettore MCP, budget (SPEC_MCP Rev13): viste a scelta e budget assegnato per conto."""

import datetime

import pytest

from connettore import protocollo
from connettore.strumenti import Contesto

from .conftest import chiama

pytestmark = pytest.mark.django_db
OGGI = datetime.date.today()


def test_connettore_budget_di_default_e_assegnato(conti_assegnati, utente_reader):
    risposta, _ = protocollo.gestisci(
        chiama("budget", {"anno": 2026, "natura": "OPEX", "sottocluster": ["tutti"]}),
        Contesto(utente_reader, OGGI),
    )
    dati = risposta["result"]["structuredContent"]
    assert list(dati["viste"]) == ["fatturato_stanziato_competenza"]
    assert "ordinato" in dati["altre_viste_disponibili"]
    (sezione,) = dati["sezioni"]
    assert set(sezione["totale"]) == {"fatturato_stanziato_competenza"}
    per_conto = {g["chiave"]: g["budget_assegnato"] for g in sezione["gruppi"]}
    assert per_conto["C-SUP"]["stato"] == "superato"
    assert per_conto["C-OK"]["stato"] == "ok"
    assert per_conto["C-NO"] == {
        "assegnato": None,
        "speso": "10000.00",
        "utilizzo_pct": None,
        "stato": "non_assegnato",
    }
    assert dati["budget_assegnato_per_conto"]["soglia_avvicinamento_pct"] == "90.00"


def test_connettore_viste_a_scelta(conti_assegnati, utente_reader):
    risposta, _ = protocollo.gestisci(
        chiama(
            "budget",
            {"anno": 2026, "natura": "OPEX", "sottocluster": ["tutti"], "viste": ["ordinato"]},
        ),
        Contesto(utente_reader, OGGI),
    )
    dati = risposta["result"]["structuredContent"]
    assert list(dati["viste"]) == ["ordinato"]


def test_connettore_capex_assegnato_sulla_wbs(conti_assegnati, utente_reader):
    risposta, _ = protocollo.gestisci(
        chiama("budget", {"anno": 2026, "natura": "CAPEX", "sottocluster": ["tutti"]}),
        Contesto(utente_reader, OGGI),
    )
    (sezione,) = risposta["result"]["structuredContent"]["sezioni"]
    assert sezione["raggruppato_per"] == "wbs"
    per_wbs = {g["chiave"]: g["budget_assegnato"] for g in sezione["gruppi"]}
    assert per_wbs["W-OK"]["stato"] == "ok" and per_wbs["W-OK"]["speso"] == "20000.00"
    assert per_wbs["W-SUP"]["stato"] == "superato"
    assert per_wbs["W-NO"]["stato"] == "non_assegnato"
