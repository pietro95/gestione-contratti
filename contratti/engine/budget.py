"""Tre viste di budget per anno, con i livelli fisso / probabile / massimo (SPEC §5.2).

- Impegno: intero valore della voce nel suo anno di impegno.
- Cassa: rate per data fattura (la data di pagamento non entra nel budget).
- Competenza: pro-rata a giorni sul periodo di servizio, indipendente dalla fatturazione.

Ogni ripartizione quadra al centesimo con il valore ripartito.
"""

from collections.abc import Iterable
from decimal import Decimal

from contratti.engine.date import giorni, periodi_per_anno
from contratti.engine.importi import ZERO, arrotonda, ripartisci
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import Esito, Livello, Rata, Totali, Voce


def quota_variabile(voce: Voce, livello: Livello) -> Decimal:
    """Parte variabile della voce al livello richiesto."""
    if livello == Livello.FISSO:
        return ZERO
    if livello == Livello.MASSIMO:
        return arrotonda(voce.massimale_variabile)
    if voce.stima_consumo_importo is not None:
        return arrotonda(voce.stima_consumo_importo)
    if voce.stima_consumo_pct is not None:
        return arrotonda(voce.massimale_variabile * voce.stima_consumo_pct / Decimal(100))
    return ZERO


def valore(voce: Voce, livello: Livello = Livello.FISSO) -> Decimal:
    """Valore della voce al livello (TC-05): fisso + variabile del livello."""
    return arrotonda(voce.importo_fisso) + quota_variabile(voce, livello)


def competenza_per_anno(voce: Voce, importo: Decimal) -> dict[int, Decimal]:
    """Pro-rata a giorni sul periodo di servizio; residuo sull'ultimo anno (TC-01)."""
    per_anno = periodi_per_anno(voce.inizio, voce.fine)
    anni = sorted(per_anno)
    return dict(zip(anni, ripartisci(importo, [per_anno[a] for a in anni]), strict=True))


def rate_della_voce(voce: Voce) -> list[Rata]:
    return list(voce.rate) if voce.rate is not None else genera_rate(voce)


def cassa_per_anno(voce: Voce, livello: Livello, esiti: list[Esito]) -> dict[int, Decimal]:
    """Fisso dalle rate per data fattura; variabile distribuito sulle stesse date.

    Il variabile segue gli importi fissi delle rate; se il fisso è zero, i giorni dei
    periodi. Senza rate (SAL senza rate inserite, Da verificare) vale il pro-rata a
    giorni, segnalato.
    """
    rate = rate_della_voce(voce)
    variabile = quota_variabile(voce, livello)
    risultato: dict[int, Decimal] = {}

    if not rate:
        modalita = voce.piano.modalita if voce.piano else None
        esiti.append(
            Esito(
                "CASSA_PRO_RATA",
                f"Cassa stimata a pro-rata: nessuna rata ({modalita or 'piano assente'}).",
            )
        )
        return competenza_per_anno(voce, valore(voce, livello))

    for rata in rate:
        risultato[rata.data_fattura.year] = (
            risultato.get(rata.data_fattura.year, ZERO) + rata.importo
        )

    if variabile:
        pesi = [r.importo for r in rate]
        if not any(pesi):
            pesi = [
                Decimal(giorni(r.periodo_inizio, r.periodo_fine))
                if r.periodo_inizio and r.periodo_fine
                else Decimal(1)
                for r in rate
            ]
        for rata, quota in zip(rate, ripartisci(variabile, pesi), strict=True):
            anno = rata.data_fattura.year
            risultato[anno] = risultato.get(anno, ZERO) + quota
    return risultato


def calcola(voci: Iterable[Voce]) -> tuple[dict[str, Totali], list[Esito]]:
    """Impegno, cassa e competenza per anno e livello, sommati su tutte le voci."""
    viste = {"impegno": Totali(), "cassa": Totali(), "competenza": Totali()}
    esiti: list[Esito] = []
    for voce in voci:
        for livello in Livello:
            importo_livello = valore(voce, livello)
            viste["impegno"].aggiungi(voce.anno_impegno, livello, importo_livello)
            for anno, importo in cassa_per_anno(voce, livello, esiti).items():
                viste["cassa"].aggiungi(anno, livello, importo)
            fisso = competenza_per_anno(voce, voce.importo_fisso)
            var = competenza_per_anno(voce, quota_variabile(voce, livello))
            for anno in fisso:
                viste["competenza"].aggiungi(anno, livello, fisso[anno] + var.get(anno, ZERO))
    # Un avviso per voce basta: i livelli ripetono lo stesso.
    unici = list(dict.fromkeys(esiti))
    return viste, unici
