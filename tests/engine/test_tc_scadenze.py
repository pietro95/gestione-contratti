"""TC-06 (data limite e alert) e TC-10 (data di fine effettiva con proroghe)."""

import pytest

from contratti.engine.scadenze import (
    alert,
    data_fine_contrattuale,
    data_fine_effettiva,
    data_limite_avvio,
    data_ultima_disdetta,
)
from contratti.engine.tipi import Alert, Scadenza

from .casi import D

LEAD_TIME = {"diretto": 4, "negoziata": 9}  # parametri di TC-06
FINESTRA = 3


def scadenza_tc06(procedura):
    # Data di fine 31/12/2026.
    return Scadenza(inizio=D(2026, 1, 1), durata_mesi=12, lead_time_mesi=LEAD_TIME[procedura])


@pytest.mark.parametrize(
    ("caso", "procedura", "oggi", "stato", "successore", "limite", "atteso"),
    [
        ("a", "diretto", D(2026, 9, 30), "non_avviata", False, D(2026, 8, 31), Alert.ARANCIONE),
        ("b", "diretto", D(2026, 6, 15), "non_avviata", False, D(2026, 8, 31), Alert.GIALLO),
        ("c", "diretto", D(2026, 1, 15), "non_avviata", False, D(2026, 8, 31), Alert.VERDE),
        ("d", "diretto", D(2026, 9, 30), "rda_predisposta", False, D(2026, 8, 31), Alert.GIALLO),
        ("e", "diretto", D(2027, 1, 5), "rda_predisposta", False, D(2026, 8, 31), Alert.ROSSO),
        ("f", "diretto", D(2027, 1, 5), None, True, None, None),
        ("g", "negoziata", D(2026, 6, 30), "non_avviata", False, D(2026, 3, 31), Alert.ARANCIONE),
    ],
)
def test_tc06(caso, procedura, oggi, stato, successore, limite, atteso):
    s = scadenza_tc06(procedura)
    assert data_fine_effettiva(s) == D(2026, 12, 31)
    if limite:
        assert data_limite_avvio(s) == limite
    risultato = alert(
        s,
        oggi,
        decisione="rinnovare",
        stato_pratica=stato,
        ha_successore=successore,
        finestra_mesi=FINESTRA,
    )
    assert risultato == atteso, caso


def test_tc06_dismettere_mai_alert():
    s = scadenza_tc06("diretto")
    for oggi in (D(2026, 1, 15), D(2026, 9, 30), D(2027, 1, 5)):
        assert (
            alert(
                s,
                oggi,
                decisione="dismettere",
                stato_pratica="non_avviata",
                ha_successore=False,
                finestra_mesi=FINESTRA,
            )
            is None
        )


def test_senza_passaggi_la_pratica_e_non_avviata():
    s = scadenza_tc06("diretto")
    kw = {"decisione": "rinnovare", "ha_successore": False, "finestra_mesi": FINESTRA}
    assert alert(s, D(2026, 9, 30), stato_pratica=None, **kw) == Alert.ARANCIONE


def test_offerta_richiesta_resta_arancione():
    s = scadenza_tc06("diretto")
    kw = {"decisione": "rinnovare", "ha_successore": False, "finestra_mesi": FINESTRA}
    assert alert(s, D(2026, 9, 30), stato_pratica="offerta_richiesta", **kw) == Alert.ARANCIONE


# --- TC-10 -----------------------------------------------------------------------

TC10 = Scadenza(
    inizio=D(2025, 4, 1),
    durata_mesi=12,
    lead_time_mesi=4,
    nuove_date_fine=(D(2026, 9, 30), D(2027, 3, 31)),
)


def test_tc10_date():
    assert data_fine_contrattuale(TC10) == D(2026, 3, 31)
    assert data_fine_effettiva(TC10) == D(2027, 3, 31)
    assert data_limite_avvio(TC10) == D(2026, 11, 30)


@pytest.mark.parametrize(
    ("oggi", "atteso"),
    [
        (D(2026, 12, 15), Alert.ARANCIONE),
        (D(2026, 7, 15), Alert.VERDE),
        (D(2026, 8, 31), Alert.GIALLO),  # inizio della finestra: 30/11 − 3 mesi = 31/08
        (D(2026, 8, 30), Alert.VERDE),
        (D(2027, 4, 15), Alert.ROSSO),
    ],
)
def test_tc10_alert(oggi, atteso):
    risultato = alert(
        TC10,
        oggi,
        decisione="rinnovare",
        stato_pratica="non_avviata",
        ha_successore=False,
        finestra_mesi=FINESTRA,
    )
    assert risultato == atteso


def test_override_della_fine():
    s = Scadenza(
        inizio=D(2026, 1, 1), durata_mesi=12, lead_time_mesi=4, fine_override=D(2027, 2, 28)
    )
    assert data_fine_effettiva(s) == D(2027, 2, 28)


# --- Tacito rinnovo (SPEC §5.1) ---------------------------------------------------


def test_tacito_rinnovo_usa_la_data_piu_vicina():
    s = Scadenza(
        inizio=D(2026, 1, 1),
        durata_mesi=12,
        lead_time_mesi=1,  # data limite 30/11/2026
        tacito_rinnovo=True,
        preavviso_disdetta_giorni=90,  # ultima disdetta 02/10/2026
    )
    assert data_ultima_disdetta(s) == D(2026, 10, 2)
    kw = {"decisione": "rinnovare", "ha_successore": False, "finestra_mesi": FINESTRA}
    assert alert(s, D(2026, 10, 15), stato_pratica="non_avviata", **kw) == Alert.ARANCIONE
    assert alert(s, D(2026, 7, 2), stato_pratica="non_avviata", **kw) == Alert.GIALLO
    assert alert(s, D(2026, 7, 1), stato_pratica="non_avviata", **kw) == Alert.VERDE


# --- Fabbisogno nuovo con previsto manuale (cruscotto F4) ------------------------


@pytest.mark.parametrize(
    ("oggi", "atteso"),
    [
        (
            D(2026, 9, 30),
            Alert.VERDE,
        ),  # limite 01/04/2027 (01/07/2027 − 3 mesi), finestra dal 01/01/2027
        (D(2027, 1, 15), Alert.GIALLO),
        (D(2027, 4, 15), Alert.ARANCIONE),
        (D(2027, 7, 2), Alert.ROSSO),
    ],
)
def test_alert_previsto_manuale(oggi, atteso):
    from contratti.engine.scadenze import alert_previsto_manuale

    assert (
        alert_previsto_manuale(
            D(2027, 7, 1),
            3,
            oggi,
            decisione="rinnovare",
            stato_pratica=None,
            finestra_mesi=FINESTRA,
        )
        == atteso
    )
