"""Costruttori dei casi di docs/TEST_CASES.md per i test del motore."""

import datetime
from decimal import Decimal

from contratti.engine.tipi import Modalita, Piano, Voce

D = datetime.date


def voce(fisso, inizio, fine, *, piano=None, anno_impegno=None, **kw):
    return Voce(
        importo_fisso=Decimal(fisso),
        inizio=inizio,
        fine=fine,
        anno_impegno=anno_impegno or inizio.year,
        piano=piano,
        **kw,
    )


def piano(modalita, periodicita="", **kw):
    return Piano(modalita=Modalita(modalita), periodicita=periodicita, **kw)


def euro(valore):
    return Decimal(valore)
