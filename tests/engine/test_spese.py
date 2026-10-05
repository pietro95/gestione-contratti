"""TC-14 (motore): spesa ricorrente senza contratto (dominio DNS)."""

import datetime
from decimal import Decimal

from contratti.engine import budget, spese
from contratti.engine.tipi import Alert, Livello

D = datetime.date
DNS = spese.SpesaRicorrente(importo=Decimal("25.00"), dal=D(2025, 3, 15), mesi=12)


def test_occorrenze_e_prossima():
    assert spese.occorrenze(DNS, D(2027, 12, 31)) == [
        D(2025, 3, 15),
        D(2026, 3, 15),
        D(2027, 3, 15),
    ]
    assert spese.prossima(DNS, D(2026, 12, 1)) == D(2027, 3, 15)
    assert spese.prossima(DNS, D(2027, 3, 15)) == D(2027, 3, 15)  # oggi è il giorno della spesa


def test_mensile_dal_fine_mese_resta_a_fine_mese():
    s = spese.SpesaRicorrente(importo=Decimal("10.00"), dal=D(2026, 1, 31), mesi=1)
    assert spese.occorrenze(s, D(2026, 4, 30)) == [
        D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)
    ]  # fmt: skip


def test_tre_viste_2026():
    viste, esiti = budget.calcola(spese.voci(DNS, D(2026, 12, 31)))
    assert not esiti
    assert viste["cassa"].importo(2026) == Decimal("25.00")  # fattura del 15/03/2026
    assert viste["impegno"].importo(2026) == Decimal("25.00")
    # Competenza: 73/365 del periodo 2025-26 (5,00) + 292/365 del periodo 2026-27 (20,00).
    assert viste["competenza"].importo(2026) == Decimal("25.00")
    assert viste["competenza"].importo(2025) == Decimal("20.00")  # 292 giorni nel 2025
    for livello in Livello:
        assert viste["cassa"].importo(2026, livello) == Decimal("25.00")


def test_promemoria_solo_giallo():
    def alert(oggi, **kw):
        return spese.promemoria(DNS, oggi, finestra_mesi=3, **kw)

    assert alert(D(2026, 12, 1)) == (Alert.VERDE, D(2027, 3, 15))  # limite 15/12/2026
    assert alert(D(2026, 12, 20)) == (Alert.GIALLO, D(2027, 3, 15))
    assert alert(D(2027, 3, 15)) == (Alert.GIALLO, D(2027, 3, 15))
    assert alert(D(2027, 3, 16)) == (Alert.VERDE, D(2028, 3, 15))  # mai rosso o arancione
    assert alert(D(2026, 12, 20), dismessa=True) == (None, None)


def test_spesa_terminata():
    s = spese.SpesaRicorrente(
        importo=Decimal("25.00"), dal=D(2025, 3, 15), mesi=12, al=D(2026, 12, 31)
    )
    assert spese.occorrenze(s, D(2028, 12, 31)) == [D(2025, 3, 15), D(2026, 3, 15)]
    assert spese.promemoria(s, D(2027, 1, 1), finestra_mesi=3) == (None, None)
    viste, _ = budget.calcola(spese.voci(s, D(2027, 12, 31)))
    assert viste["cassa"].importo(2027) == Decimal("0.00")
