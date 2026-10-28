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


def mese_precedente(d: datetime.date) -> tuple[datetime.date, datetime.date]:
    """Primo e ultimo giorno del mese che precede quello di ``d``."""
    ultimo = d.replace(day=1) - UN_GIORNO
    return ultimo.replace(day=1), ultimo


def giorni(inizio: datetime.date, fine: datetime.date) -> int:
    """Giorni tra due date, estremi inclusi."""
    return (fine - inizio).days + 1
