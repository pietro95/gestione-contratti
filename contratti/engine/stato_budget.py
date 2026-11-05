"""Stato di un budget assegnato rispetto a quanto speso (SPEC §5.2, Rev34). Funzioni pure."""

import enum
from decimal import ROUND_HALF_UP, Decimal

from contratti.engine.importi import ZERO

CENTO = Decimal(100)


class StatoBudget(enum.StrEnum):
    OK = "ok"
    IN_AVVICINAMENTO = "in_avvicinamento"
    SUPERATO = "superato"
    NON_ASSEGNATO = "non_assegnato"


ETICHETTE_STATO = {
    StatoBudget.OK: "OK",
    StatoBudget.IN_AVVICINAMENTO: "In avvicinamento",
    StatoBudget.SUPERATO: "Superato",
    StatoBudget.NON_ASSEGNATO: "Non assegnato",
}


def stato_budget(assegnato: Decimal | None, speso: Decimal, soglia_pct: Decimal) -> StatoBudget:
    """Confronta lo speso con l'assegnato.

    - nessun assegnato: ``NON_ASSEGNATO`` (il confronto non si calcola);
    - speso oltre l'assegnato: ``SUPERATO``;
    - speso dalla soglia (% dell'assegnato) fino all'assegnato incluso: ``IN_AVVICINAMENTO``;
    - altrimenti ``OK``. Con speso zero lo stato è sempre ``OK``.
    """
    if assegnato is None:
        return StatoBudget.NON_ASSEGNATO
    if speso > assegnato:
        return StatoBudget.SUPERATO
    if speso <= ZERO:
        return StatoBudget.OK
    if speso * CENTO >= assegnato * soglia_pct:
        return StatoBudget.IN_AVVICINAMENTO
    return StatoBudget.OK


def percentuale_utilizzo(assegnato: Decimal | None, speso: Decimal) -> Decimal | None:
    """Speso / assegnato in %, a un decimale (None se non c'è un assegnato positivo)."""
    if assegnato is None or assegnato <= ZERO:
        return None
    return (speso * CENTO / assegnato).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
