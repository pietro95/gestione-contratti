"""Generazione dello scadenzario rate (SPEC §4, regole di generazione).

La rata contiene solo la quota fissa. Rate uguali per periodo con residuo sull'ultima;
un ultimo periodo più corto pesa in proporzione ai suoi giorni.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from contratti.engine.date import UN_GIORNO, aggiungi_mesi, fine_mese, giorni
from contratti.engine.importi import arrotonda, ripartisci
from contratti.engine.tipi import INTERA_DURATA, MESI_PERIODICITA, Modalita, Piano, Rata, Voce


@dataclass(frozen=True)
class Periodo:
    inizio: datetime.date
    fine: datetime.date
    # 1 per un periodo pieno; frazione dei giorni per un ultimo periodo più corto.
    peso: Decimal


def data_pagamento(data_fattura: datetime.date, piano: Piano) -> datetime.date:
    """Fine del mese di (data fattura + giorni) se d.f.f.m.; solo informativa."""
    data = data_fattura + datetime.timedelta(days=piano.giorni_pagamento)
    return fine_mese(data) if piano.pagamento_fine_mese else data


def mesi_periodo(piano: Piano, inizio: datetime.date, fine: datetime.date) -> int | None:
    if piano.modalita == Modalita.CONSUMO:
        return 1
    if piano.periodicita == INTERA_DURATA or not piano.periodicita:
        return None
    return MESI_PERIODICITA[piano.periodicita]


def periodi(inizio: datetime.date, fine: datetime.date, mesi: int | None) -> list[Periodo]:
    """Periodi di fatturazione di [inizio, fine]; ``mesi=None`` = un periodo unico."""
    if mesi is None:
        return [Periodo(inizio, fine, Decimal(1))]
    risultato = []
    k = 0
    while True:
        p_inizio = aggiungi_mesi(inizio, k * mesi) if k else inizio
        if p_inizio > fine:
            break
        nominale = aggiungi_mesi(inizio, (k + 1) * mesi) - UN_GIORNO
        p_fine = min(nominale, fine)
        peso = (
            Decimal(1)
            if p_fine == nominale
            else Decimal(giorni(p_inizio, p_fine)) / Decimal(giorni(p_inizio, nominale))
        )
        risultato.append(Periodo(p_inizio, p_fine, peso))
        k += 1
    return risultato


def genera_rate(voce: Voce, importo: Decimal | None = None) -> list[Rata]:
    """Rate della quota fissa (o di ``importo``) secondo il piano della voce.

    SAL e Da verificare non generano rate: le prime si inseriscono a mano, per le
    seconde la cassa usa il pro-rata (SPEC §4).
    """
    piano = voce.piano
    totale = voce.importo_fisso if importo is None else importo
    if piano is None or piano.modalita in (Modalita.SAL, Modalita.DA_VERIFICARE):
        return []

    if piano.modalita == Modalita.UNA_TANTUM:
        data = piano.data_prima_fattura or voce.inizio
        return [
            Rata(1, data, data_pagamento(data, piano), arrotonda(totale), voce.inizio, voce.fine)
        ]

    mesi = mesi_periodo(piano, voce.inizio, voce.fine)
    elenco = periodi(voce.inizio, voce.fine, mesi)
    importi = ripartisci(totale, [p.peso for p in elenco])

    posticipata = piano.modalita in (Modalita.POSTICIPATA, Modalita.CONSUMO)
    rate = []
    for k, (p, quota) in enumerate(zip(elenco, importi, strict=True)):
        if piano.data_prima_fattura and mesi is not None:
            data = aggiungi_mesi(piano.data_prima_fattura, k * mesi)
        elif piano.data_prima_fattura:
            data = piano.data_prima_fattura
        else:
            data = p.fine if posticipata else p.inizio
        rate.append(Rata(k + 1, data, data_pagamento(data, piano), quota, p.inizio, p.fine))
    return rate
