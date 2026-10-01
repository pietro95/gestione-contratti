"""Importi in Decimal: arrotondamento ROUND_HALF_UP al centesimo, residuo sull'ultimo."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

CENTESIMO = Decimal("0.01")
ZERO = Decimal("0.00")


def arrotonda(valore: Decimal) -> Decimal:
    return valore.quantize(CENTESIMO, rounding=ROUND_HALF_UP)


def ripartisci(totale: Decimal, pesi: Sequence[Decimal | int]) -> list[Decimal]:
    """Ripartisce ``totale`` in proporzione ai pesi; la somma quadra al centesimo.

    Ogni quota è arrotondata ROUND_HALF_UP; il residuo va sull'ultima. Con pesi tutti
    nulli il totale si ripartisce in parti uguali.
    """
    if not pesi:
        raise ValueError("serve almeno un peso")
    totale = arrotonda(Decimal(totale))
    pesi = [Decimal(p) for p in pesi]
    if any(p < 0 for p in pesi):
        raise ValueError("pesi negativi")
    somma = sum(pesi)
    if somma == 0:
        pesi = [Decimal(1)] * len(pesi)
        somma = Decimal(len(pesi))
    quote = [arrotonda(totale * p / somma) for p in pesi[:-1]]
    residuo = totale - sum(quote, ZERO)
    if (totale >= 0) == (residuo >= 0):
        return [*quote, residuo]
    # Caso limite (centesimi su pesi molto sbilanciati): arrotondamento cumulato,
    # che non produce mai quote di segno opposto al totale.
    cumulati, acc = [], Decimal(0)
    for p in pesi:
        acc += p
        cumulati.append(arrotonda(totale * acc / somma))
    return [b - a for a, b in zip([ZERO, *cumulati[:-1]], cumulati, strict=True)]
