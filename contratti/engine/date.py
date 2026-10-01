"""Aritmetica delle date (SPEC §5.1). Estremi sempre inclusi."""

import calendar
import datetime

from dateutil.relativedelta import relativedelta

UN_GIORNO = datetime.timedelta(days=1)


def fine_mese(d: datetime.date) -> datetime.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def is_fine_mese(d: datetime.date) -> bool:
    return d == fine_mese(d)


def aggiungi_mesi(d: datetime.date, mesi: int) -> datetime.date:
    """Somma (o sottrae, se negativo) mesi con la regola "fine mese su fine mese".

    Una data di fine mese resta a fine mese (30/11 − 3 mesi = 31/08); le altre
    mantengono il giorno, ridotto all'ultimo del mese se questo è più corto.
    """
    risultato = d + relativedelta(months=mesi)
    return fine_mese(risultato) if is_fine_mese(d) else risultato


def giorni(inizio: datetime.date, fine: datetime.date) -> int:
    """Giorni tra due date, estremi inclusi."""
    return (fine - inizio).days + 1


def periodi_per_anno(inizio: datetime.date, fine: datetime.date) -> dict[int, int]:
    """Giorni del periodo [inizio, fine] che cadono in ciascun anno solare."""
    risultato = {}
    for anno in range(inizio.year, fine.year + 1):
        da = max(inizio, datetime.date(anno, 1, 1))
        a = min(fine, datetime.date(anno, 12, 31))
        risultato[anno] = giorni(da, a)
    return risultato
