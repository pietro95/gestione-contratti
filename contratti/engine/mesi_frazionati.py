"""Ripartizione della competenza a mesi frazionati (SPEC §5.2, Rev31). Funzione unica e pura.

Ogni mese di calendario toccato dal periodo pesa ``giorni coperti / giorni del mese``; il peso di
un anno è la somma dei suoi mesi; la quota di un anno è ``importo × peso anno / peso totale``.

Con questo metodo la tariffa non dipende dalla lunghezza dell'anno: due contratti contigui da
12 mesi, uno a cavallo di un anno bisestile e uno no, ripartiscono lo stesso canone nello stesso
modo. Il peso dei mesi di confine di due contratti contigui somma esattamente 1 (stesso mese,
stessa lunghezza), quindi un anno solare coperto per intero somma al canone annuo. Fa eccezione
il confine in febbraio tra un anno bisestile e uno no (il mese di inizio e quello di fine di uno
stesso contratto hanno lunghezze diverse): lo scarto è documentato in ``tests/engine``.

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


def pesi_per_anno(inizio: datetime.date, fine: datetime.date) -> dict[int, Fraction]:
    """Peso (in mesi, frazionato) del periodo [inizio, fine] in ciascun anno solare."""
    if fine < inizio:
        raise ValueError("periodo non valido: la fine precede l'inizio")
    pesi: dict[int, Fraction] = {}
    anno, mese = inizio.year, inizio.month
    while (anno, mese) <= (fine.year, fine.month):
        giorni_mese = calendar.monthrange(anno, mese)[1]
        da = max(inizio, datetime.date(anno, mese, 1))
        a = min(fine, datetime.date(anno, mese, giorni_mese))
        coperti = (a - da).days + 1
        pesi[anno] = pesi.get(anno, Fraction(0)) + Fraction(coperti, giorni_mese)
        anno, mese = (anno + 1, 1) if mese == 12 else (anno, mese + 1)
    return pesi


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
