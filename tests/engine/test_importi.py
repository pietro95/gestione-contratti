from decimal import Decimal

import pytest

from contratti.engine.importi import arrotonda, ripartisci


def test_arrotondamento_half_up():
    assert arrotonda(Decimal("144.655")) == Decimal("144.66")
    assert arrotonda(Decimal("0.005")) == Decimal("0.01")


def test_ripartisci_quadra_con_residuo_sull_ultima():
    quote = ripartisci(Decimal("100.00"), [1, 1, 1])
    assert quote == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(quote) == Decimal("100.00")


def test_ripartisci_pesi_nulli_parti_uguali():
    assert ripartisci(Decimal("10.00"), [0, 0]) == [Decimal("5.00"), Decimal("5.00")]


def test_ripartisci_mai_quote_negative():
    # Caso limite: arrotondando le prime due il residuo sarebbe negativo.
    quote = ripartisci(Decimal("0.01"), [1, 1, 0])
    assert sum(quote) == Decimal("0.01")
    assert all(q >= 0 for q in quote)


def test_ripartisci_pesi_negativi_rifiutati():
    with pytest.raises(ValueError):
        ripartisci(Decimal("1"), [1, -1])
