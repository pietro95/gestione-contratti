"""Spese ricorrenti senza contratto (F9.5, SPEC §5.6): occorrenze, voci e promemoria.

Un fabbisogno che si soddisfa senza contratto (es. il dominio DNS, pagato ogni anno con una
fattura diretta) ha importo, periodicità e data della prima spesa. Ogni periodo è una voce
`Una tantum` fatturata il primo giorno, di competenza sul periodo, impegnata nel suo anno.
Le date si contano sempre dalla prima spesa (k × periodo), con la regola di fine mese: non
scivolano nel tempo.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from contratti.engine.date import UN_GIORNO, aggiungi_mesi
from contratti.engine.tipi import Alert, Modalita, Piano, Voce


@dataclass(frozen=True)
class SpesaRicorrente:
    importo: Decimal
    dal: datetime.date  # prima spesa
    mesi: int  # periodicità
    al: datetime.date | None = None  # ultima spesa possibile, se la spesa è terminata
    riferimento: object = None


def occorrenze(s: SpesaRicorrente, fino_a: datetime.date) -> list[datetime.date]:
    """Date delle spese dalla prima fino a ``fino_a`` (e non oltre ``al``), estremi inclusi."""
    limite = min(fino_a, s.al) if s.al else fino_a
    date, k = [], 0
    while (d := aggiungi_mesi(s.dal, k * s.mesi)) <= limite:
        date.append(d)
        k += 1
    return date


def prossima(s: SpesaRicorrente, oggi: datetime.date) -> datetime.date | None:
    """Prima spesa da oggi in poi; ``None`` se la spesa è terminata."""
    k = 0
    while (d := aggiungi_mesi(s.dal, k * s.mesi)) < oggi:
        k += 1
    if s.al and d > s.al:
        return None
    return d


def voci(s: SpesaRicorrente, fino_a: datetime.date) -> list[Voce]:
    """Una voce per spesa: fattura il giorno della spesa, servizio fino alla successiva."""
    risultato = []
    for k, d in enumerate(occorrenze(s, fino_a)):
        fine = aggiungi_mesi(s.dal, (k + 1) * s.mesi) - UN_GIORNO
        risultato.append(
            Voce(
                importo_fisso=s.importo,
                inizio=d,
                fine=fine,
                anno_impegno=d.year,
                piano=Piano(modalita=Modalita.UNA_TANTUM, data_prima_fattura=d),
                riferimento=s.riferimento,
            )
        )
    return risultato


def promemoria(
    s: SpesaRicorrente, oggi: datetime.date, *, finestra_mesi: int, dismessa: bool = False
) -> tuple[Alert | None, datetime.date | None]:
    """Solo promemoria: 🟡 nella finestra prima della prossima spesa, altrimenti 🟢.

    Mai 🟠 o 🔴: non c'è una procedura da avviare. Nessun alert se la spesa è dismessa o
    terminata.
    """
    if dismessa:
        return None, None
    d = prossima(s, oggi)
    if d is None:
        return None, None
    return (Alert.GIALLO if oggi >= aggiungi_mesi(d, -finestra_mesi) else Alert.VERDE), d
