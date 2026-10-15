"""TC-07 — Rinnovi previsti ricorsivi, e rinnovo dopo le proroghe (TC-10)."""

from decimal import Decimal

from contratti.engine.budget import calcola
from contratti.engine.previsioni import previsti, previsto_manuale
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import ContrattoBase

from .casi import D, euro, piano, voce

ORIZZONTE = D(2028, 12, 31)


def adeguamento_3(_data):
    return Decimal("3")


def base_tc07():
    v = voce("10000.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("anticipata", "annuale"))
    return ContrattoBase(fine_effettiva=D(2026, 12, 31), durata_mesi=12, voci=(v,))


def test_tc07_due_previsti_nell_orizzonte():
    risultato = previsti(
        base_tc07(), decisione="rinnovare", orizzonte=ORIZZONTE, adeguamento=adeguamento_3
    )
    assert [(p.inizio, p.fine) for p in risultato] == [
        (D(2027, 1, 1), D(2027, 12, 31)),
        (D(2028, 1, 1), D(2028, 12, 31)),
    ]
    assert [p.voci[0].importo_fisso for p in risultato] == [euro("10300.00"), euro("10609.00")]
    assert [[r.data_fattura for r in genera_rate(p.voci[0])] for p in risultato] == [
        [D(2027, 1, 1)],
        [D(2028, 1, 1)],
    ]


def test_tc07_impegno_nell_anno_di_inizio():
    risultato = previsti(
        base_tc07(), decisione="rinnovare", orizzonte=ORIZZONTE, adeguamento=adeguamento_3
    )
    viste, _ = calcola([v for p in risultato for v in p.voci])
    assert viste["impegno"].importo(2027) == euro("10300.00")
    assert viste["impegno"].importo(2028) == euro("10609.00")


def test_tc07_con_stima_manuale():
    risultato = previsti(
        base_tc07(),
        decisione="rinnovare",
        orizzonte=ORIZZONTE,
        adeguamento=adeguamento_3,
        stima_manuale=euro("12000.00"),
    )
    assert [p.voci[0].importo_fisso for p in risultato] == [euro("12000.00"), euro("12360.00")]


def test_tc07_da_valutare_genera_previsti():
    assert previsti(
        base_tc07(), decisione="da_valutare", orizzonte=ORIZZONTE, adeguamento=adeguamento_3
    )


def test_tc07_dismettere_nessun_previsto():
    for decisione in ("dismettere", "sostituire"):
        assert (
            previsti(
                base_tc07(), decisione=decisione, orizzonte=ORIZZONTE, adeguamento=adeguamento_3
            )
            == []
        )


def test_tc07_successore_reale_sostituisce_i_previsti():
    # Il successore reale diventa la nuova base: i previsti partono dalla sua fine.
    successore = voce(
        "11000.00", D(2027, 1, 1), D(2027, 12, 31), piano=piano("anticipata", "annuale")
    )
    base = ContrattoBase(fine_effettiva=D(2027, 12, 31), durata_mesi=12, voci=(successore,))
    risultato = previsti(
        base, decisione="rinnovare", orizzonte=ORIZZONTE, adeguamento=adeguamento_3
    )
    assert [(p.inizio, p.voci[0].importo_fisso) for p in risultato] == [
        (D(2028, 1, 1), euro("11330.00"))
    ]


def test_stima_manuale_ripartita_in_proporzione_al_fisso():
    v1 = voce("3000.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("anticipata", "annuale"))
    v2 = voce("1000.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("anticipata", "annuale"))
    base = ContrattoBase(fine_effettiva=D(2026, 12, 31), durata_mesi=12, voci=(v1, v2))
    (p1,) = previsti(
        base,
        decisione="rinnovare",
        orizzonte=D(2027, 12, 31),
        adeguamento=adeguamento_3,
        stima_manuale=euro("5000.00"),
    )
    assert [v.importo_fisso for v in p1.voci] == [euro("3750.00"), euro("1250.00")]


def test_massimale_adeguato():
    v = voce(
        "6000.00",
        D(2026, 1, 1),
        D(2026, 12, 31),
        massimale_variabile=euro("14000.00"),
        stima_consumo_pct=euro("30"),
    )
    base = ContrattoBase(fine_effettiva=D(2026, 12, 31), durata_mesi=12, voci=(v,))
    (p1,) = previsti(
        base, decisione="rinnovare", orizzonte=D(2027, 12, 31), adeguamento=adeguamento_3
    )
    assert p1.voci[0].massimale_variabile == euro("14420.00")
    assert p1.voci[0].stima_consumo_pct == euro("30")


def test_tc10_rinnovo_dopo_le_proroghe():
    # Durata originale (12 mesi) e sola voce base; parte dalla fine effettiva 31/03/2027.
    base_voce = voce(
        "12000.00", D(2025, 4, 1), D(2026, 3, 31), piano=piano("anticipata", "annuale")
    )
    base = ContrattoBase(fine_effettiva=D(2027, 3, 31), durata_mesi=12, voci=(base_voce,))
    (p1,) = previsti(
        base, decisione="rinnovare", orizzonte=D(2027, 12, 31), adeguamento=adeguamento_3
    )
    assert (p1.inizio, p1.fine) == (D(2027, 4, 1), D(2028, 3, 31))
    assert [v.importo_fisso for v in p1.voci] == [euro("12360.00")]


def test_previsto_manuale_di_un_fabbisogno_nuovo():
    p = previsto_manuale(
        inizio=D(2027, 7, 1),
        durata_mesi=24,
        importo=euro("8000.00"),
        piano=piano("anticipata", "annuale"),
    )
    assert (p.inizio, p.fine) == (D(2027, 7, 1), D(2029, 6, 30))
    assert [r.data_fattura for r in genera_rate(p.voci[0])] == [D(2027, 7, 1), D(2028, 7, 1)]


def test_durata_rinnovo_diversa_dal_contratto_precedente():
    # Contratto di 18 mesi (01/07/2025-31/12/2026): il rinnovo è deciso a 24 mesi, e la
    # durata vale anche per i previsti successivi.
    v = voce("18000.00", D(2025, 7, 1), D(2026, 12, 31), piano=piano("anticipata", "annuale"))
    base = ContrattoBase(fine_effettiva=D(2026, 12, 31), durata_mesi=18, voci=(v,))
    p1, p2 = previsti(
        base,
        decisione="rinnovare",
        orizzonte=D(2029, 1, 1),
        adeguamento=adeguamento_3,
        stima_manuale=euro("24000.00"),
        durata_mesi=24,
    )
    assert (p1.inizio, p1.fine) == (D(2027, 1, 1), D(2028, 12, 31))
    assert (p2.inizio, p2.fine) == (D(2029, 1, 1), D(2030, 12, 31))
    assert [v.importo_fisso for v in p1.voci] == [euro("24000.00")]
    assert [v.importo_fisso for v in p2.voci] == [euro("24720.00")]
