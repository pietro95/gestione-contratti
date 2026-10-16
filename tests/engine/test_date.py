"""Aritmetica dei mesi "fine mese su fine mese" (SPEC §5.1, TC-06)."""

import datetime

import pytest

from contratti.engine.date import aggiungi_mesi, giorni, periodi_per_anno

D = datetime.date


@pytest.mark.parametrize(
    ("data", "mesi", "atteso"),
    [
        (D(2026, 12, 31), -4, D(2026, 8, 31)),
        (D(2026, 12, 31), -9, D(2026, 3, 31)),
        (D(2026, 6, 30), -4, D(2026, 2, 28)),
        (D(2028, 6, 30), -4, D(2028, 2, 29)),
        (D(2026, 11, 30), -3, D(2026, 8, 31)),
        (D(2026, 9, 30), 3, D(2026, 12, 31)),
        (D(2026, 3, 15), -1, D(2026, 2, 15)),
        (D(2026, 5, 31), -3, D(2026, 2, 28)),
        (D(2026, 1, 30), 1, D(2026, 2, 28)),
        (D(2026, 1, 1), 12, D(2027, 1, 1)),
        (D(2027, 3, 31), -4, D(2026, 11, 30)),
    ],
)
def test_aggiungi_mesi_fine_mese(data, mesi, atteso):
    assert aggiungi_mesi(data, mesi) == atteso


def test_giorni_estremi_inclusi():
    assert giorni(D(2025, 12, 21), D(2026, 12, 20)) == 365
    assert giorni(D(2026, 1, 1), D(2026, 1, 1)) == 1


def test_periodi_per_anno():
    assert periodi_per_anno(D(2023, 3, 24), D(2026, 3, 23)) == {
        2023: 283,
        2024: 366,
        2025: 365,
        2026: 82,
    }


def test_mese_precedente():
    from contratti.engine.date import mese_precedente

    assert mese_precedente(D(2026, 9, 4)) == (D(2026, 8, 1), D(2026, 8, 31))
    assert mese_precedente(D(2026, 1, 10)) == (D(2025, 12, 1), D(2025, 12, 31))
    assert mese_precedente(D(2024, 3, 31)) == (D(2024, 2, 1), D(2024, 2, 29))
