"""Stanziamento proposto dalle rate scadute senza fattura (SPEC §5.2, Rev22). Funzioni pure."""

import datetime

UN_GIORNO = datetime.timedelta(days=1)


def giorni_di_ritardo(data_fattura: datetime.date, oggi: datetime.date) -> int:
    """Giorni trascorsi dalla data prevista della fattura (negativo: non ancora scaduta)."""
    return (oggi - data_fattura).days


def da_stanziare(data_fattura: datetime.date, oggi: datetime.date, tolleranza: int) -> bool:
    """La rata senza fattura è scaduta oltre la tolleranza: si propone lo stanziamento."""
    return giorni_di_ritardo(data_fattura, oggi) > tolleranza


def periodo_proposto(
    data_fattura: datetime.date,
    inizio: datetime.date | None,
    fine: datetime.date | None,
) -> tuple[datetime.date, datetime.date]:
    """Competenza dello stanziamento: il periodo della rata, se noto, altrimenti la data
    prevista della fattura."""
    if inizio and fine:
        return inizio, fine
    return data_fattura, data_fattura
