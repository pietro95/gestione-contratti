"""TC-20 (SPEC Rev21): fatturato e stanziato a competenza. Valori di docs/TEST_CASES.md."""

from dataclasses import replace

from contratti.engine.budget import calcola
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import Consuntivo, TipoConsuntivo

from .casi import D, euro, piano, voce


def _base():
    v = voce("12000.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("posticipata", "mensile"))
    return v, genera_rate(v)


def _con(rata_numero, consuntivo, extra=()):
    v, rate = _base()
    rate = tuple(replace(r, consuntivo=consuntivo) if r.numero == rata_numero else r for r in rate)
    return replace(v, rate=rate, consuntivi=tuple(extra))


def _fattura(importo, dal, al, **kw):
    return Consuntivo(TipoConsuntivo.FATTURA, euro(importo), dal, al, **kw)


def _anni(v):
    viste, esiti = calcola([v])
    return {n: (t.importo(2026), t.importo(2027)) for n, t in viste.items()}, esiti


def test_base_senza_fatture():
    v, rate = _base()
    assert len(rate) == 12 and rate[11].data_fattura == D(2026, 12, 31)
    viste, esiti = _anni(v)
    for nome in ("consuntivo", "cassa", "competenza"):
        assert viste[nome] == (euro("12000.00"), euro("0.00")), nome
    assert esiti == []


def test_a_fattura_a_cavallo_d_anno():
    f = _fattura("1000.00", D(2026, 12, 1), D(2027, 1, 31))
    viste, _ = _anni(_con(12, f))
    assert viste["consuntivo"] == (euro("11500.00"), euro("500.00"))
    assert viste["cassa"][0] == viste["competenza"][0] == euro("12000.00")


def test_b_fattura_emessa_dopo_la_fine_dell_anno():
    f = _fattura("1000.00", D(2026, 12, 1), D(2026, 12, 31))
    viste, _ = _anni(_con(12, f))  # registrata il 15/01/2027, competenza 2026
    assert viste["consuntivo"] == (euro("12000.00"), euro("0.00"))
    assert viste["cassa"][0] == euro("12000.00")


def test_c_stanziamento_poi_fattura():
    s = Consuntivo(TipoConsuntivo.STANZIAMENTO, euro("1000.00"), D(2026, 11, 1), D(2026, 11, 30))
    assert _anni(_con(11, s))[0]["consuntivo"][0] == euro("12000.00")
    f = _fattura("1050.00", D(2026, 11, 1), D(2026, 11, 30))
    assert _anni(_con(11, f))[0]["consuntivo"][0] == euro("12050.00")
    # Annullato: la rata torna alla previsione.
    assert _anni(_con(11, None))[0]["consuntivo"][0] == euro("12000.00")


def test_d_fattura_senza_competenza():
    f = _fattura("700.00", D(2026, 5, 10), D(2026, 5, 10), senza_competenza=True)
    viste, esiti = _anni(_con(5, f))
    assert viste["consuntivo"][0] == euro("11700.00")
    assert [e.codice for e in esiti] == ["COMPETENZA_FATTURA_MANCANTE"]


def test_e_fattura_non_abbinata():
    f = _fattura("300.00", D(2026, 3, 1), D(2026, 3, 31))
    viste, esiti = _anni(_con(0, None, extra=[f]))
    assert viste["consuntivo"][0] == euro("12300.00")
    assert [e.codice for e in esiti] == ["CONSUNTIVO_NON_ABBINATO"]
