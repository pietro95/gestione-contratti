"""Rinnovi previsti ricorsivi (SPEC §5.3, TC-07, TC-10)."""

import datetime
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

from contratti.engine.date import UN_GIORNO, aggiungi_mesi
from contratti.engine.importi import arrotonda, ripartisci
from contratti.engine.tipi import ContrattoBase, ContrattoPrevisto, Piano, Voce

DECISIONI_CON_RINNOVO = frozenset({"rinnovare", "da_valutare"})

# Percentuale di adeguamento valida a una data (parametro con validità temporale).
AdeguamentoAllaData = Callable[[datetime.date], Decimal]


def _applica(importo: Decimal, pct: Decimal) -> Decimal:
    return arrotonda(importo * (Decimal(1) + pct / Decimal(100)))


def _sposta(voce: Voce, inizio: datetime.date, fine: datetime.date, fisso, massimale) -> Voce:
    piano = voce.piano
    if piano is not None and piano.data_prima_fattura is not None:
        # La data della prima fattura del contratto originale non vale per il previsto.
        piano = replace(piano, data_prima_fattura=None)
    return replace(
        voce,
        inizio=inizio,
        fine=fine,
        anno_impegno=inizio.year,
        importo_fisso=fisso,
        massimale_variabile=massimale,
        stima_consumo_importo=(
            None
            if voce.stima_consumo_importo is None
            else min(voce.stima_consumo_importo, massimale)
        ),
        piano=piano,
        rate=None,
        # Il previsto riparte dall'importo totale, senza le quote del contratto precedente.
        quote=(),
    )


def prossimo(
    base: ContrattoBase,
    adeguamento_pct: Decimal,
    stima_manuale: Decimal | None = None,
    numero: int = 1,
    durata_mesi: int | None = None,
) -> ContrattoPrevisto:
    """Un rinnovo: inizio il giorno dopo la fine, stessa durata originale e stesso piano.

    ``durata_mesi`` sostituisce la durata del contratto precedente (rinnovo deciso su una
    durata diversa); gli importi non si ricalcolano in proporzione: li decide la stima.

    Fisso e massimale di ogni voce × (1 + adeguamento). Con la stima manuale, la stima
    sostituisce il fisso totale ed è ripartita tra le voci in proporzione al loro fisso.
    """
    inizio = base.fine_effettiva + UN_GIORNO
    fine = aggiungi_mesi(inizio, durata_mesi or base.durata_mesi) - UN_GIORNO
    if stima_manuale is not None:
        fissi = ripartisci(stima_manuale, [v.importo_fisso for v in base.voci])
    else:
        fissi = [_applica(v.importo_fisso, adeguamento_pct) for v in base.voci]
    voci = tuple(
        _sposta(v, inizio, fine, fisso, _applica(v.massimale_variabile, adeguamento_pct))
        for v, fisso in zip(base.voci, fissi, strict=True)
    )
    return ContrattoPrevisto(inizio=inizio, fine=fine, voci=voci, numero=numero)


def previsti(
    base: ContrattoBase,
    *,
    decisione: str,
    orizzonte: datetime.date,
    adeguamento: AdeguamentoAllaData,
    stima_manuale: Decimal | None = None,
    durata_mesi: int | None = None,
) -> list[ContrattoPrevisto]:
    """Catena di previsti finché l'inizio del successivo cade entro l'orizzonte.

    ``durata_mesi``, se indicata, vale per tutti i previsti della catena.

    La stima manuale vale solo per il primo previsto; i successivi partono da quello
    e applicano l'adeguamento (TC-07, variante con stima).
    """
    if decisione not in DECISIONI_CON_RINNOVO or not base.voci:
        return []
    risultato: list[ContrattoPrevisto] = []
    corrente = base
    stima = stima_manuale
    while corrente.fine_effettiva + UN_GIORNO <= orizzonte:
        inizio = corrente.fine_effettiva + UN_GIORNO
        nuovo = prossimo(
            corrente, adeguamento(inizio), stima, numero=len(risultato) + 1, durata_mesi=durata_mesi
        )
        risultato.append(nuovo)
        corrente = ContrattoBase(nuovo.fine, durata_mesi or base.durata_mesi, nuovo.voci)
        stima = None
    return risultato


def previsto_manuale(
    *,
    inizio: datetime.date,
    durata_mesi: int,
    importo: Decimal,
    piano: Piano | None,
) -> ContrattoPrevisto:
    """Previsto di un fabbisogno nuovo, dai dati decisi sul fabbisogno (SPEC §4)."""
    fine = aggiungi_mesi(inizio, durata_mesi) - UN_GIORNO
    voce = Voce(
        importo_fisso=arrotonda(importo),
        inizio=inizio,
        fine=fine,
        anno_impegno=inizio.year,
        piano=piano,
    )
    return ContrattoPrevisto(inizio=inizio, fine=fine, voci=(voce,))
