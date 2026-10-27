"""Viste di budget per anno, con i livelli fisso / probabile / massimo (SPEC §5.2).

- Impegno: intero valore della voce nel suo anno di impegno.
- Cassa: rate per data fattura (la data di pagamento non entra nel budget); per le voci a SAL
  le fatture registrate per data documento e, per il residuo, rate a mano o quote (Rev28).
- Competenza: pro-rata a giorni sul periodo di servizio, indipendente dalla fatturazione.
- Consuntivo a competenza (Rev21): fatture registrate e stanziamenti al posto delle rate,
  imputati a giorni al periodo di competenza; le rate senza fattura né stanziamento restano
  la previsione.

Ogni ripartizione quadra al centesimo con il valore ripartito.
"""

from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal

from contratti.engine import sal
from contratti.engine.date import giorni
from contratti.engine.importi import ZERO, arrotonda, ripartisci
from contratti.engine.scadenzario import genera_rate, quote_valide
from contratti.engine.tipi import Consuntivo, Esito, Livello, Modalita, Rata, Totali, Voce


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
    return sal.a_giorni(importo, voce.inizio, voce.fine)


def competenza_fisso(voce: Voce, esiti: list[Esito]) -> dict[int, Decimal]:
    """Competenza del fisso: per quota se ci sono quote coerenti, altrimenti sulla voce."""
    if voce.quote and quote_valide(voce) is None:
        if sal.e_sal(voce):
            # Per un SAL le quote regolano il fatturato (Rev28), non la competenza.
            esito = Esito(
                "SAL_QUOTE_NON_IN_COMPETENZA",
                "Quote per periodo di una voce a SAL non usate nella competenza (pro-rata a "
                "giorni sul servizio): valgono per il fatturato.",
            )
        else:
            esito = Esito(
                "QUOTE_INCOERENTI",
                "Quote per periodo non contigue, fuori dal periodo o con somma diversa dal "
                "fisso: ignorate, competenza e rate sull'intera voce.",
            )
        esiti.append(esito)
    quote = quote_valide(voce)
    if not quote:
        return competenza_per_anno(voce, voce.importo_fisso)
    risultato: dict[int, Decimal] = {}
    for q in quote:
        parte = Voce(importo_fisso=q.importo, inizio=q.inizio, fine=q.fine, anno_impegno=0)
        for anno, importo in competenza_per_anno(parte, q.importo).items():
            risultato[anno] = risultato.get(anno, ZERO) + importo
    return risultato


def ripartizione_sal(
    voce: Voce, livello: Livello, vista: str
) -> tuple[sal.RipartoSal, list[Esito]]:
    """Consuntivo, previsto e non pianificato di una voce a SAL (vista ``cassa`` o
    ``consuntivo``), con gli avvisi relativi."""
    ripartizione = sal.ripartisci_sal(voce, quota_variabile(voce, livello), vista)
    esiti = list(ripartizione.esiti)
    for c in ripartizione.consuntivi_usati:
        # Nella cassa conta la data documento: la competenza mancante non è un problema.
        _segnala_consuntivo(
            replace(c, senza_competenza=c.senza_competenza and vista == sal.VISTA_CONSUNTIVO),
            esiti,
        )
    return ripartizione, esiti


def rate_della_voce(voce: Voce) -> list[Rata]:
    return list(voce.rate) if voce.rate is not None else genera_rate(voce)


def cassa_per_anno(voce: Voce, livello: Livello, esiti: list[Esito]) -> dict[int, Decimal]:
    """Fisso dalle rate per data fattura; variabile distribuito sulle stesse date.

    Il variabile segue gli importi fissi delle rate; se il fisso è zero, i giorni dei
    periodi. Senza rate (Da verificare) vale il pro-rata a giorni, segnalato; a consumo vale lo
    stesso pro-rata, senza avviso. Le voci a SAL non hanno mai il pro-rata: fatture, poi rate o
    quote per il residuo (``contratti.engine.sal``, Rev28).
    """
    if sal.e_sal(voce):
        ripartizione, nuovi = ripartizione_sal(voce, livello, sal.VISTA_CASSA)
        esiti.extend(nuovi)
        return ripartizione.per_anno

    rate = rate_della_voce(voce)
    variabile = quota_variabile(voce, livello)
    risultato: dict[int, Decimal] = {}

    if not rate:
        modalita = voce.piano.modalita if voce.piano else None
        # A consumo non ha un calendario di fatturazione: il pro-rata è la regola, non un avviso.
        if modalita != Modalita.CONSUMO:
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


def _a_competenza(importo: Decimal, inizio, fine) -> dict[int, Decimal]:
    """Importo ripartito a giorni sugli anni del periodo; residuo sull'ultimo anno."""
    return competenza_per_anno(
        Voce(importo_fisso=importo, inizio=inizio, fine=fine, anno_impegno=0), importo
    )


def _aggiungi(risultato: dict[int, Decimal], parte: dict[int, Decimal]) -> None:
    for anno, importo in parte.items():
        risultato[anno] = risultato.get(anno, ZERO) + importo


def _segnala_consuntivo(c: Consuntivo, esiti: list[Esito]) -> None:
    if c.senza_competenza:
        esiti.append(
            Esito(
                "COMPETENZA_FATTURA_MANCANTE",
                "Fattura senza periodo di competenza: imputata all'anno della data fattura.",
            )
        )
    if c.senza_voce:
        esiti.append(
            Esito(
                "FATTURA_SENZA_VOCE",
                "Fattura del contratto senza voce indicata: attribuita alla voce principale.",
            )
        )


def consuntivo_per_anno(voce: Voce, livello: Livello, esiti: list[Esito]) -> dict[int, Decimal]:
    """Consuntivo a competenza della voce (Rev21).

    Per ogni rata: la fattura registrata (valore base) o lo stanziamento che la sostituisce,
    imputati a giorni sul loro periodo di competenza; altrimenti la previsione della rata,
    sul periodo della rata se noto, altrimenti nell'anno della data fattura. Si sommano le
    fatture e gli stanziamenti non abbinati a una rata. La quota variabile segue il
    pro-rata a giorni della voce, come la competenza.
    """
    if sal.e_sal(voce):
        ripartizione, nuovi = ripartizione_sal(voce, livello, sal.VISTA_CONSUNTIVO)
        esiti.extend(nuovi)
        return ripartizione.per_anno

    rate = rate_della_voce(voce)
    risultato: dict[int, Decimal] = {}
    if not rate:
        # Stesso caso della cassa (CASSA_PRO_RATA): un solo avviso.
        _aggiungi(risultato, competenza_fisso(voce, []))
    for rata in rate:
        c = rata.consuntivo
        if c is not None:
            _segnala_consuntivo(c, esiti)
            _aggiungi(risultato, _a_competenza(c.importo, c.inizio, c.fine))
        elif rata.periodo_inizio and rata.periodo_fine:
            _aggiungi(
                risultato, _a_competenza(rata.importo, rata.periodo_inizio, rata.periodo_fine)
            )
        else:
            anno = rata.data_fattura.year
            risultato[anno] = risultato.get(anno, ZERO) + rata.importo
    for c in voce.consuntivi:
        _segnala_consuntivo(c, esiti)
        _aggiungi(risultato, _a_competenza(c.importo, c.inizio, c.fine))
    if voce.consuntivi and rate:
        esiti.append(
            Esito(
                "CONSUNTIVO_NON_ABBINATO",
                "Fatture o stanziamenti non abbinati a una rata si sommano alle rate previste: "
                "abbinali alla rata per evitare il doppio conteggio.",
            )
        )
    _aggiungi(risultato, competenza_per_anno(voce, quota_variabile(voce, livello)))
    return risultato


def calcola(voci: Iterable[Voce]) -> tuple[dict[str, Totali], list[Esito]]:
    """Consuntivo, impegno, cassa e competenza per anno e livello, sommati su tutte le voci."""
    viste = {
        "consuntivo": Totali(),
        "impegno": Totali(),
        "cassa": Totali(),
        "competenza": Totali(),
    }
    esiti: list[Esito] = []
    for voce in voci:
        for livello in Livello:
            importo_livello = valore(voce, livello)
            viste["impegno"].aggiungi(voce.anno_impegno, livello, importo_livello)
            for anno, importo in cassa_per_anno(voce, livello, esiti).items():
                viste["cassa"].aggiungi(anno, livello, importo)
            for anno, importo in consuntivo_per_anno(voce, livello, esiti).items():
                viste["consuntivo"].aggiungi(anno, livello, importo)
            fisso = competenza_fisso(voce, esiti)
            var = competenza_per_anno(voce, quota_variabile(voce, livello))
            for anno in sorted(set(fisso) | set(var)):
                viste["competenza"].aggiungi(
                    anno, livello, fisso.get(anno, ZERO) + var.get(anno, ZERO)
                )
    # Un avviso per voce basta: i livelli ripetono lo stesso.
    unici = list(dict.fromkeys(esiti))
    return viste, unici
