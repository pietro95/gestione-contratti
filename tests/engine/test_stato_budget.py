"""Stato del budget assegnato rispetto allo speso (SPEC §5.2, Rev34): confini della soglia."""

from decimal import Decimal

import pytest

from contratti.engine.stato_budget import StatoBudget, percentuale_utilizzo, stato_budget

D = Decimal
SOGLIA = D("90")


@pytest.mark.parametrize(
    ("assegnato", "speso", "atteso"),
    [
        (None, D("100.00"), StatoBudget.NON_ASSEGNATO),
        (D("1000.00"), D("0.00"), StatoBudget.OK),
        (D("1000.00"), D("899.99"), StatoBudget.OK),
        (D("1000.00"), D("900.00"), StatoBudget.IN_AVVICINAMENTO),  # esattamente la soglia
        (D("1000.00"), D("1000.00"), StatoBudget.IN_AVVICINAMENTO),  # esattamente l'assegnato
        (D("1000.00"), D("1000.01"), StatoBudget.SUPERATO),
        (D("0.00"), D("0.00"), StatoBudget.OK),
        (D("0.00"), D("0.01"), StatoBudget.SUPERATO),
    ],
)
def test_stati(assegnato, speso, atteso):
    assert stato_budget(assegnato, speso, SOGLIA) == atteso


def test_la_soglia_e_un_parametro():
    assert stato_budget(D("1000"), D("800"), D("80")) == StatoBudget.IN_AVVICINAMENTO
    assert stato_budget(D("1000"), D("800"), D("90")) == StatoBudget.OK


def test_percentuale_di_utilizzo():
    assert percentuale_utilizzo(D("3000.00"), D("1000.00")) == D("33.3")
    assert percentuale_utilizzo(D("0.00"), D("10.00")) is None
    assert percentuale_utilizzo(None, D("10.00")) is None
