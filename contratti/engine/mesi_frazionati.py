"""Ripartizione della competenza a mesi frazionati (SPEC §5.2, Rev31). Funzione unica e pura.

Ogni mese di calendario toccato dal periodo pesa ``giorni coperti / giorni del mese``; il peso di
un anno è la somma dei suoi mesi; la quota di un anno è ``importo × peso anno / peso totale``.

Il peso di un periodo è la differenza tra due posizioni sull'asse dei mesi (additivo): due periodi
contigui pesano esattamente quanto il periodo unito. Il giorno di confine pesa quindi lo stesso in
ogni anno, e due contratti contigui da 12 mesi che coprono un anno solare intero sommano al canone
annuo.

**Febbraio.** Il numero di giorni di febbraio cambia da un anno all'altro: con il denominatore
effettivo (28 o 29) lo stesso giorno di confine peserebbe diversamente e il peso totale di un
contratto da 12 mesi non sarebbe 12. Per febbraio si usano quindi sempre 29 «posizioni»: i giorni
dall'1 al 28 occupano le posizioni 1–28 e l'ultimo giorno del mese (il 28 negli anni non bisestili,
il 29 in quelli bisestili) occupa sempre la 29. Un febbraio coperto per intero pesa 1 come ogni
altro mese; gli altri mesi non cambiano. Resta un solo confine che non quadra, ed è irrisolvibile
per costruzione: l'inizio al 28/02 di un anno bisestile (il suo anniversario cade lo stesso giorno
dell'anniversario di un inizio al 29/02, SPEC §5.1).

I pesi sono frazioni esatte (``Fraction``, mai ``float``) e gli importi ``Decimal``: ogni quota è
arrotondata ROUND_HALF_UP al centesimo e il residuo va all'anno con il peso maggiore (a parità,
l'ultimo), così la somma è esattamente l'importo. Se il residuo rendesse una quota di segno
opposto all'importo (pochi centesimi su molti anni), si usa l'arrotondamento cumulato.
"""

import calendar
import datetime
from decimal import Decimal
from fractions import Fraction

from contratti.engine.importi import CENTESIMO, arrotonda

UN_GIORNO = datetime.timedelta(days=1)
POSIZIONI_FEBBRAIO = 29


def _posizione(data: datetime.date) -> Fraction:
    """Inizio del giorno ``data`` sull'asse dei mesi (0 = inizio dell'anno 0)."""
    giorni_mese = calendar.monthrange(data.year, data.month)[1]
    if data.month == 2:
        slot = POSIZIONI_FEBBRAIO if data.day == giorni_mese else data.day
        lunghezza = POSIZIONI_FEBBRAIO
    else:
        slot, lunghezza = data.day, giorni_mese
    return data.year * 12 + data.month - 1 + Fraction(slot - 1, lunghezza)


def pesi_per_anno(inizio: datetime.date, fine: datetime.date) -> dict[int, Fraction]:
    """Peso (in mesi, frazionato) del periodo [inizio, fine] in ciascun anno solare."""
    if fine < inizio:
        raise ValueError("periodo non valido: la fine precede l'inizio")
    da, a = _posizione(inizio), _posizione(fine + UN_GIORNO)
    return {
        anno: min(a, _posizione(datetime.date(anno + 1, 1, 1)))
        - max(da, _posizione(datetime.date(anno, 1, 1)))
        for anno in range(inizio.year, fine.year + 1)
    }


def _centesimi_half_up(valore: Fraction) -> int:
    """Intero più vicino, con i mezzi arrotondati lontano da zero (ROUND_HALF_UP di Decimal)."""
    segno = -1 if valore < 0 else 1
    n, d = abs(valore.numerator), valore.denominator
    return segno * ((2 * n + d) // (2 * d))


def competenza_per_anno(
    importo: Decimal, inizio: datetime.date, fine: datetime.date
) -> dict[int, Decimal]:
    """Importo ripartito a mesi frazionati sugli anni di [inizio, fine] (estremi inclusi).

    La somma delle quote è esattamente ``importo`` (arrotondato al centesimo). Un periodo
    degenere (fine prima dell'inizio) solleva ``ValueError``, come la ripartizione a giorni
    che sostituisce.
    """
    pesi = pesi_per_anno(inizio, fine)
    totale = arrotonda(Decimal(importo))
    centesimi = int(totale.scaleb(2))
    peso_totale = sum(pesi.values(), Fraction(0))
    quote = {
        anno: _centesimi_half_up(Fraction(centesimi) * peso / peso_totale)
        for anno, peso in pesi.items()
    }
    # Il residuo va all'anno con il peso maggiore; a parità, all'ultimo.
    anno_residuo = max(pesi, key=lambda a: (pesi[a], a))
    quote[anno_residuo] += centesimi - sum(quote.values())
    if any(q * centesimi < 0 for q in quote.values()):
        # Caso limite (pochi centesimi su molti anni di peso pari): il residuo darebbe a un anno
        # una quota di segno opposto all'importo. Arrotondamento cumulato, che non lo produce mai.
        quote, cumulato = {}, Fraction(0)
        for anno, peso in pesi.items():
            precedente = _centesimi_half_up(cumulato)
            cumulato += Fraction(centesimi) * peso / peso_totale
            quote[anno] = _centesimi_half_up(cumulato) - precedente
    return {anno: Decimal(c) * CENTESIMO for anno, c in sorted(quote.items())}
