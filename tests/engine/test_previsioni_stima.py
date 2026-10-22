"""Stima del prossimo importo = importo complessivo atteso, consumo compreso (SPEC §5.3, Rev27)."""

from decimal import Decimal

from contratti.engine.budget import valore
from contratti.engine.previsioni import prossimo
from contratti.engine.tipi import ContrattoBase, Livello

from .casi import D, euro, piano, voce


def _base(fisso, massimale, stima_importo):
    v = voce(
        fisso,
        D(2026, 1, 1),
        D(2026, 12, 31),
        piano=piano("anticipata", "annuale"),
        massimale_variabile=euro(massimale),
        stima_consumo_importo=euro(stima_importo),
    )
    return ContrattoBase(D(2026, 12, 31), 12, (v,))


def test_senza_stima_il_consumo_del_contratto_di_partenza_si_replica():
    p = prossimo(_base("5000.00", "5000.00", "3600.00"), Decimal(0))
    (v,) = p.voci
    assert valore(v, Livello.PROBABILE) == euro("8600.00")
    assert valore(v, Livello.MASSIMO) == euro("10000.00")


def test_con_la_stima_il_consumo_non_si_somma():
    # Prima: 8.600 diventavano 13.600 (stima + consumo del contratto di partenza).
    p = prossimo(_base("5000.00", "5000.00", "3600.00"), Decimal(0), stima_manuale=euro("8600.00"))
    (v,) = p.voci
    assert v.importo_fisso == euro("8600.00")
    assert v.massimale_variabile == euro("0.00")
    for livello in Livello:
        assert valore(v, livello) == euro("8600.00")


def test_con_la_stima_su_un_contratto_a_consumo_con_fisso_zero():
    # Prima: 20.000 diventavano 40.000.
    p = prossimo(_base("0.00", "20000.00", "10000.00"), Decimal(0), stima_manuale=euro("20000.00"))
    (v,) = p.voci
    assert valore(v, Livello.PROBABILE) == euro("20000.00")
    assert valore(v, Livello.MASSIMO) == euro("20000.00")


def test_la_stima_e_ripartita_tra_le_voci_in_proporzione_al_fisso():
    a = voce("3000.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("anticipata", "annuale"))
    b = voce(
        "1000.00",
        D(2026, 1, 1),
        D(2026, 12, 31),
        piano=piano("anticipata", "annuale"),
        massimale_variabile=euro("500.00"),
        stima_consumo_pct=euro("50"),
    )
    p = prossimo(ContrattoBase(D(2026, 12, 31), 12, (a, b)), Decimal(0), euro("8000.00"))
    assert [v.importo_fisso for v in p.voci] == [euro("6000.00"), euro("2000.00")]
    assert sum((valore(v, Livello.MASSIMO) for v in p.voci), Decimal(0)) == euro("8000.00")
