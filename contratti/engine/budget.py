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
from contratti.engine.scadenzario import genera_rate, quote_valide
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


def competenza_fisso(voce: Voce, esiti: list[Esito]) -> dict[int, Decimal]:
    """Competenza del fisso: per quota se ci sono quote coerenti, altrimenti sulla voce."""
    if voce.quote and quote_valide(voce) is None:
        esiti.append(
            Esito(
                "QUOTE_INCOERENTI",
                "Quote per periodo non contigue, fuori dal periodo o con somma diversa dal "
                "fisso: ignorate, competenza e rate sull'intera voce.",
            )
        )
    quote = quote_valide(voce)
    if not quote:
        return competenza_per_anno(voce, voce.importo_fisso)
    risultato: dict[int, Decimal] = {}
    for q in quote:
        parte = Voce(importo_fisso=q.importo, inizio=q.inizio, fine=q.fine, anno_impegno=0)
        for anno, importo in competenza_per_anno(parte, q.importo).items():
            risultato[anno] = risultato.get(anno, ZERO) + importo
    return risultato


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
            fisso = competenza_fisso(voce, esiti)
            var = competenza_per_anno(voce, quota_variabile(voce, livello))
            for anno in sorted(set(fisso) | set(var)):
                viste["competenza"].aggiungi(
                    anno, livello, fisso.get(anno, ZERO) + var.get(anno, ZERO)
                )
    # Un avviso per voce basta: i livelli ripetono lo stesso.
    unici = list(dict.fromkeys(esiti))
    return viste, unici
