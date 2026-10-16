"""Consuntivo a competenza (SPEC §5.2, Rev21): fatture e stanziamenti al posto delle rate."""

from dataclasses import replace

from contratti.engine.budget import calcola
from contratti.engine.importi import ripartisci
from contratti.engine.tipi import Consuntivo, Livello, Rata, TipoConsuntivo

from .casi import D, euro, piano, voce


def _rata(numero, data, importo, consuntivo=None, periodo=None):
    inizio, fine = periodo or (None, None)
    return Rata(numero, data, data, euro(importo), inizio, fine, consuntivo)


def _fattura(importo, dal, al, **kw):
    return Consuntivo(TipoConsuntivo.FATTURA, euro(importo), dal, al, **kw)


def _voce_con_rata(consuntivo=None, **kw):
    return voce(
        "1000.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("anticipata", "annuale"),
        rate=(_rata(1, D(2026, 1, 1), "1000.00", consuntivo, (D(2026, 1, 1), D(2026, 12, 31))),),
        **kw,
    )  # fmt: skip


def test_senza_fatture_il_consuntivo_segue_le_rate():
    viste, esiti = calcola([_voce_con_rata()])
    assert viste["consuntivo"].importo(2026) == euro("1000.00")
    assert esiti == []


def test_fattura_a_cavallo_d_anno_si_ripartisce_a_giorni():
    # Competenza 01/07/2026-30/06/2027: 184 giorni nel 2026, 181 nel 2027.
    f = _fattura("1200.00", D(2026, 7, 1), D(2027, 6, 30))
    viste, _ = calcola([_voce_con_rata(f)])
    atteso = ripartisci(euro("1200.00"), [184, 181])
    assert viste["consuntivo"].importo(2026) == atteso[0] == euro("604.93")
    assert viste["consuntivo"].importo(2027) == atteso[1] == euro("595.07")
    assert viste["consuntivo"].totale() == euro("1200.00")
    # La cassa legge ancora la rata (data fattura) e la competenza del contratto il servizio.
    assert viste["cassa"].importo(2026) == euro("1000.00")
    assert viste["competenza"].importo(2026) == euro("1000.00")


def test_fattura_data_a_gennaio_ma_competenza_dell_anno_prima():
    # Canone di dicembre 2025 fatturato a gennaio 2026: è un costo del 2025.
    f = _fattura("500.00", D(2025, 12, 1), D(2025, 12, 31))
    viste, _ = calcola([_voce_con_rata(f)])
    assert viste["consuntivo"].importo(2025) == euro("500.00")
    assert viste["consuntivo"].importo(2026) == euro("0.00")


def test_stanziamento_prende_il_posto_della_rata():
    s = Consuntivo(TipoConsuntivo.STANZIAMENTO, euro("800.00"), D(2026, 1, 1), D(2026, 12, 31))
    viste, _ = calcola([_voce_con_rata(s)])
    assert viste["consuntivo"].importo(2026) == euro("800.00")
    assert viste["cassa"].importo(2026) == euro("1000.00")


def test_fatture_non_abbinate_si_sommano_e_si_segnalano():
    f = _fattura("300.00", D(2026, 3, 1), D(2026, 3, 31))
    v = replace(_voce_con_rata(), consuntivi=(f,))
    viste, esiti = calcola([v])
    assert viste["consuntivo"].importo(2026) == euro("1300.00")
    assert [e.codice for e in esiti] == ["CONSUNTIVO_NON_ABBINATO"]


def test_competenza_mancante_e_voce_mancante_segnalate():
    f = _fattura("100.00", D(2026, 5, 10), D(2026, 5, 10), senza_competenza=True, senza_voce=True)
    viste, esiti = calcola([_voce_con_rata(f)])
    assert viste["consuntivo"].importo(2026) == euro("100.00")
    assert {e.codice for e in esiti} == {"COMPETENZA_FATTURA_MANCANTE", "FATTURA_SENZA_VOCE"}


def test_il_variabile_segue_la_competenza_della_voce():
    v = _voce_con_rata(massimale_variabile=euro("365.00"))
    viste, _ = calcola([v])
    assert viste["consuntivo"].importo(2026, Livello.FISSO) == euro("1000.00")
    assert viste["consuntivo"].importo(2026, Livello.MASSIMO) == euro("1365.00")
