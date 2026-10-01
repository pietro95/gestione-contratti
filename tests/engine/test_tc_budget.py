"""TC-01 … TC-05 e TC-10 (parte economica): valori di docs/TEST_CASES.md."""

import pytest

from contratti.engine.budget import calcola, valore
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import Livello

from .casi import D, euro, piano, voce


def per_anno(totali, anni, livello=Livello.FISSO):
    return {a: totali.importo(a, livello) for a in anni}


# --- TC-01 -------------------------------------------------------------------


def test_tc01_competenza_a_giorni():
    v = voce("4800.00", D(2025, 12, 21), D(2026, 12, 20), piano=piano("anticipata", "annuale"))
    viste, _ = calcola([v])
    assert per_anno(viste["competenza"], [2025, 2026]) == {
        2025: euro("144.66"),
        2026: euro("4655.34"),
    }
    assert viste["competenza"].totale() == euro("4800.00")  # mai il 108% del vecchio Excel


# --- TC-02 -------------------------------------------------------------------


def test_tc02_pluriennale_una_tantum_anticipato():
    v = voce(
        "21990.06",
        D(2023, 3, 24),
        D(2026, 3, 23),
        piano=piano("una_tantum", data_prima_fattura=D(2023, 3, 24)),
        anno_impegno=2023,  # OdA del 10/03/2023
    )
    viste, _ = calcola([v])
    anni = [2023, 2024, 2025, 2026]
    assert per_anno(viste["impegno"], anni) == {
        2023: euro("21990.06"),
        2024: euro("0.00"),
        2025: euro("0.00"),
        2026: euro("0.00"),
    }
    assert per_anno(viste["cassa"], anni) == {
        2023: euro("21990.06"),
        2024: euro("0.00"),
        2025: euro("0.00"),
        2026: euro("0.00"),
    }
    assert per_anno(viste["competenza"], anni) == {
        2023: euro("5678.09"),
        2024: euro("7343.40"),
        2025: euro("7323.33"),
        2026: euro("1645.24"),
    }
    for vista in viste.values():
        assert vista.totale() == euro("21990.06")


# --- TC-03 -------------------------------------------------------------------

TC03_SCADENZARIO = [
    (D(2026, 9, 30), D(2026, 11, 30)),
    (D(2026, 12, 31), D(2027, 3, 31)),
    (D(2027, 3, 31), D(2027, 5, 31)),
    (D(2027, 6, 30), D(2027, 8, 31)),
    (D(2027, 9, 30), D(2027, 11, 30)),
    (D(2027, 12, 31), D(2028, 2, 29)),
    (D(2028, 3, 31), D(2028, 5, 31)),
    (D(2028, 6, 30), D(2028, 8, 31)),
]


def tc03():
    return voce(
        "24000.00",
        D(2026, 7, 1),
        D(2028, 6, 30),
        piano=piano("posticipata", "trimestrale", giorni_pagamento=60, pagamento_fine_mese=True),
    )


def test_tc03_scadenzario():
    rate = genera_rate(tc03())
    assert [(r.data_fattura, r.data_pagamento) for r in rate] == TC03_SCADENZARIO
    assert [r.importo for r in rate] == [euro("3000.00")] * 8
    assert [r.numero for r in rate] == list(range(1, 9))


def test_tc03_aggregati():
    viste, _ = calcola([tc03()])
    assert per_anno(viste["cassa"], [2026, 2027, 2028]) == {
        2026: euro("6000.00"),
        2027: euro("12000.00"),
        2028: euro("6000.00"),
    }
    assert per_anno(viste["competenza"], [2026, 2027, 2028]) == {
        2026: euro("6041.04"),
        2027: euro("11983.58"),
        2028: euro("5975.38"),
    }


def test_tc03_prima_fattura_esplicita_resta_a_fine_mese():
    # 30/09 + 3 mesi = 31/12 (fine mese su fine mese), non 30/12.
    v = voce(
        "24000.00",
        D(2026, 7, 1),
        D(2028, 6, 30),
        piano=piano("posticipata", "trimestrale", data_prima_fattura=D(2026, 9, 30)),
    )
    assert [r.data_fattura for r in genera_rate(v)] == [d for d, _ in TC03_SCADENZARIO]


# --- TC-04 -------------------------------------------------------------------


def test_tc04_anticipato_annuale():
    v = voce("3000.00", D(2026, 3, 3), D(2029, 3, 2), piano=piano("anticipata", "annuale"))
    rate = genera_rate(v)
    assert [(r.data_fattura, r.importo) for r in rate] == [
        (D(2026, 3, 3), euro("1000.00")),
        (D(2027, 3, 3), euro("1000.00")),
        (D(2028, 3, 3), euro("1000.00")),
    ]
    viste, _ = calcola([v])
    assert per_anno(viste["cassa"], [2026, 2027, 2028, 2029]) == {
        2026: euro("1000.00"),
        2027: euro("1000.00"),
        2028: euro("1000.00"),
        2029: euro("0.00"),
    }


# --- TC-05 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("livello", "atteso"),
    [
        (Livello.FISSO, "6000.00"),
        (Livello.PROBABILE, "10200.00"),
        (Livello.MASSIMO, "20000.00"),
    ],
)
def test_tc05_livelli(livello, atteso):
    v = voce(
        "6000.00",
        D(2026, 1, 1),
        D(2026, 12, 31),
        piano=piano("anticipata", "annuale"),
        massimale_variabile=euro("14000.00"),
        stima_consumo_pct=euro("30"),
    )
    assert valore(v, livello) == euro(atteso)
    viste, _ = calcola([v])
    for nome in ("impegno", "cassa", "competenza"):
        assert viste[nome].totale(livello) == euro(atteso), nome


def test_tc05_massimo_mai_sotto_il_probabile():
    v = voce(
        "6000.00",
        D(2026, 1, 1),
        D(2026, 12, 31),
        massimale_variabile=euro("14000.00"),
        stima_consumo_importo=euro("14000.00"),
    )
    assert valore(v, Livello.MASSIMO) >= valore(v, Livello.PROBABILE)


# --- TC-10 (parte economica) ---------------------------------------------------


def tc10_voci():
    base = voce(
        "12000.00",
        D(2025, 4, 1),
        D(2026, 3, 31),
        piano=piano("anticipata", "annuale"),
        anno_impegno=2025,
    )
    proroga1 = voce(
        "6000.00", D(2026, 4, 1), D(2026, 9, 30), piano=piano("una_tantum"), anno_impegno=2026
    )
    proroga2 = voce(
        "6300.00", D(2026, 10, 1), D(2027, 3, 31), piano=piano("una_tantum"), anno_impegno=2026
    )
    return [base, proroga1, proroga2]


def test_tc10_scadenzario():
    rate = [r for v in tc10_voci() for r in genera_rate(v)]
    assert [(r.data_fattura, r.importo) for r in rate] == [
        (D(2025, 4, 1), euro("12000.00")),
        (D(2026, 4, 1), euro("6000.00")),
        (D(2026, 10, 1), euro("6300.00")),
    ]


def test_tc10_viste():
    viste, _ = calcola(tc10_voci())
    anni = [2025, 2026, 2027]
    assert per_anno(viste["impegno"], anni) == {
        2025: euro("12000.00"),
        2026: euro("12300.00"),
        2027: euro("0.00"),
    }
    assert per_anno(viste["cassa"], anni) == {
        2025: euro("12000.00"),
        2026: euro("12300.00"),
        2027: euro("0.00"),
    }
    assert per_anno(viste["competenza"], anni) == {
        2025: euro("9041.10"),
        2026: euro("12143.52"),
        2027: euro("3115.38"),
    }
    for vista in viste.values():
        assert vista.totale() == euro("24300.00")
