"""Regole di generazione dello scadenzario e della cassa (SPEC Rev02 §4, §5.2)."""

from decimal import Decimal

from contratti.engine.budget import calcola
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import Livello, Rata

from .casi import D, euro, piano, voce


def test_ultimo_periodo_corto_proporzionale_ai_giorni():
    # 14 mesi a trimestri: 4 trimestri pieni + 2 mesi (01/01–28/02/2027, 59 gg su 90).
    v = voce("14000.00", D(2026, 1, 1), D(2027, 2, 28), piano=piano("anticipata", "trimestrale"))
    rate = genera_rate(v)
    assert [r.data_fattura for r in rate] == [
        D(2026, 1, 1),
        D(2026, 4, 1),
        D(2026, 7, 1),
        D(2026, 10, 1),
        D(2027, 1, 1),
    ]
    piene = rate[:4]
    assert len({r.importo for r in piene}) == 1
    # peso dell'ultima = 59/90; totale pesi = 4 + 59/90.
    attesa_piena = (euro("14000.00") / (4 + Decimal(59) / Decimal(90))).quantize(Decimal("0.01"))
    assert piene[0].importo == attesa_piena
    assert sum(r.importo for r in rate) == euro("14000.00")
    assert rate[-1].importo < piene[0].importo


def test_intera_durata_una_rata():
    v = voce("900.00", D(2026, 1, 1), D(2028, 12, 31), piano=piano("posticipata", "intera_durata"))
    rate = genera_rate(v)
    assert [(r.data_fattura, r.importo) for r in rate] == [(D(2028, 12, 31), euro("900.00"))]


def test_consumo_rate_mensili_posticipate():
    v = voce(
        "0.00",
        D(2026, 1, 1),
        D(2026, 12, 31),
        piano=piano("consumo"),
        massimale_variabile=euro("1200.00"),
        stima_consumo_pct=euro("50"),
    )
    rate = genera_rate(v)
    assert len(rate) == 12
    assert rate[0].data_fattura == D(2026, 1, 31)
    assert rate[-1].data_fattura == D(2026, 12, 31)
    viste, _ = calcola([v])
    # Fisso zero: il variabile si distribuisce sui giorni dei periodi.
    assert viste["cassa"].totale(Livello.PROBABILE) == euro("600.00")
    assert viste["cassa"].totale(Livello.MASSIMO) == euro("1200.00")
    assert viste["cassa"].totale(Livello.FISSO) == euro("0.00")


def test_sal_senza_rate_cassa_a_pro_rata_segnalata():
    v = voce("3650.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("sal"))
    assert genera_rate(v) == []
    viste, esiti = calcola([v])
    assert viste["cassa"].totale() == euro("3650.00")
    assert [e.codice for e in esiti] == ["CASSA_PRO_RATA"]


def test_sal_con_rate_inserite_a_mano():
    rate = (
        Rata(1, D(2026, 3, 15), D(2026, 5, 31), euro("1000.00")),
        Rata(2, D(2027, 1, 20), D(2027, 3, 31), euro("2650.00")),
    )
    v = voce("3650.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("sal"), rate=rate)
    viste, esiti = calcola([v])
    assert viste["cassa"].importo(2026) == euro("1000.00")
    assert viste["cassa"].importo(2027) == euro("2650.00")
    assert esiti == []


def test_da_verificare_cassa_a_pro_rata_segnalata():
    v = voce("3650.00", D(2025, 7, 1), D(2026, 6, 30), piano=piano("da_verificare"))
    viste, esiti = calcola([v])
    assert viste["cassa"].importo(2025) == viste["competenza"].importo(2025)
    assert [e.codice for e in esiti] == ["CASSA_PRO_RATA"]


def test_variabile_distribuito_come_il_fisso():
    v = voce(
        "12000.00",
        D(2026, 7, 1),
        D(2027, 6, 30),
        piano=piano("posticipata", "semestrale"),
        massimale_variabile=euro("2000.00"),
    )
    viste, _ = calcola([v])
    # Due rate uguali (31/12/2026, 30/06/2027): metà del variabile per anno.
    assert viste["cassa"].importo(2026, Livello.MASSIMO) == euro("7000.00")
    assert viste["cassa"].importo(2027, Livello.MASSIMO) == euro("7000.00")


def test_rate_modificate_a_mano_prevalgono():
    rate = (Rata(1, D(2026, 2, 1), D(2026, 4, 30), euro("1100.00")),)
    v = voce(
        "1000.00", D(2026, 1, 1), D(2026, 12, 31), piano=piano("anticipata", "annuale"), rate=rate
    )
    viste, _ = calcola([v])
    assert viste["cassa"].importo(2026) == euro("1100.00")
    assert viste["impegno"].importo(2026) == euro("1000.00")


def test_data_pagamento_informativa_senza_fine_mese():
    v = voce(
        "100.00",
        D(2026, 1, 1),
        D(2026, 12, 31),
        piano=piano("anticipata", "annuale", giorni_pagamento=30, pagamento_fine_mese=False),
    )
    assert genera_rate(v)[0].data_pagamento == D(2026, 1, 31)
