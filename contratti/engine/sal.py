"""Voci a SAL: il fatturato non è mai una ripartizione lineare sul tempo (SPEC §5.2, Rev28).

Una voce a SAL non ha un calendario di fatturazione: le rate si inseriscono a mano. Per le viste
«Fatturato» (cassa) e «Fatturato e stanziato» (consuntivo) gli importi per anno vengono, in
ordine, da:

1. **consuntivo**: le fatture registrate (valore base). Nella cassa per anno della data
   documento; nel consuntivo, insieme agli stanziamenti, a giorni sul periodo di competenza;
2. **previsto**: il residuo ``importo_fisso − consuntivo``, dalle rate inserite a mano (non
   consuntivate); se non ce ne sono, dalle quote per periodo, solo per gli anni successivi
   all'ultimo anno con consuntivo (dove ci sono fatture valgono le fatture: niente doppio
   conto). Il previsto non supera mai il residuo;
3. **non pianificato**: la parte di residuo senza né rate né quote. Resta fuori dai totali e si
   segnala: l'ultima fonte non è mai il pro-rata a giorni.

Consuntivo e previsto restano separati, perché possono coesistere nello stesso anno.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from contratti.engine.acquisti import formato_euro
from contratti.engine.date import periodi_per_anno
from contratti.engine.importi import ZERO, arrotonda, ripartisci
from contratti.engine.tipi import Consuntivo, Esito, Modalita, Quota, TipoConsuntivo, Voce

VISTA_CASSA = "cassa"
VISTA_CONSUNTIVO = "consuntivo"

FONTE_FATTURE = "fatture"
FONTE_RATE = "rate"
FONTE_QUOTE = "quote"


@dataclass(frozen=True)
class RigaConsuntivoSal:
    """Importo di consuntivo in un anno, con la fattura da cui viene (per attribuirlo a una WBS)."""

    anno: int
    importo: Decimal
    riferimento: object = None


@dataclass(frozen=True)
class RipartoSal:
    consuntivo: tuple[RigaConsuntivoSal, ...] = ()
    previsto: dict[int, Decimal] = field(default_factory=dict)
    # Residuo senza rate né quote (e variabile senza previsto): fuori dai totali.
    non_pianificato: Decimal = ZERO
    fonti: tuple[str, ...] = ()
    esiti: tuple[Esito, ...] = ()
    # Consuntivi contati, perché l'adapter segnali quelli senza voce o senza competenza.
    consuntivi_usati: tuple[Consuntivo, ...] = ()

    def consuntivo_per_anno(self, riferimenti: Iterable | None = None) -> dict[int, Decimal]:
        """Consuntivo per anno; con ``riferimenti``, solo le righe di quelle fatture."""
        risultato: dict[int, Decimal] = {}
        for r in self.consuntivo:
            if riferimenti is None or r.riferimento in riferimenti:
                risultato[r.anno] = risultato.get(r.anno, ZERO) + r.importo
        return risultato

    @property
    def per_anno(self) -> dict[int, Decimal]:
        """Consuntivo più previsto, anno per anno."""
        risultato = self.consuntivo_per_anno()
        for anno, importo in self.previsto.items():
            risultato[anno] = risultato.get(anno, ZERO) + importo
        return risultato


def e_sal(voce: Voce) -> bool:
    return voce.piano is not None and voce.piano.modalita == Modalita.SAL


def a_giorni(importo: Decimal, inizio, fine) -> dict[int, Decimal]:
    """Importo ripartito a giorni sugli anni del periodo [inizio, fine]; residuo sull'ultimo."""
    per_anno = periodi_per_anno(inizio, fine)
    anni = sorted(per_anno)
    return dict(zip(anni, ripartisci(importo, [per_anno[a] for a in anni]), strict=True))


# --- Quote per periodo di una voce a SAL ---------------------------------------------------------


def errori_quote(importo_fisso: Decimal, quote: Sequence[tuple]) -> list[tuple[int | None, str]]:
    """Motivi per cui le quote (dal, al, importo) di una voce a SAL non sono ammesse.

    Solo sovrapposizione e somma oltre l'importo fisso: le quote non devono coprire il periodo di
    servizio, e ad anno solare possono iniziare prima o finire dopo. Restituisce coppie
    (indice nella sequenza data o ``None``, messaggio).
    """
    errori: list[tuple[int | None, str]] = []
    ordinate = sorted(enumerate(quote), key=lambda x: (x[1][0], x[1][1]))
    for (_, prima), (i, dopo) in zip(ordinate, ordinate[1:], strict=False):
        if dopo[0] <= prima[1]:
            errori.append(
                (i, f"si sovrappone a un'altra quota ({prima[0]:%d/%m/%Y}–{prima[1]:%d/%m/%Y}).")
            )
    somma = sum((q[2] for q in quote), ZERO)
    if somma > importo_fisso:
        errori.append((None, "La somma delle quote supera l'importo fisso della voce."))
    return errori


def avvisi_quote(voce: Voce) -> list[str]:
    """Avvisi non bloccanti sulle quote di una voce a SAL."""
    avvisi = []
    if any(q.inizio.year != q.fine.year for q in voce.quote):
        avvisi.append(
            "Una o più quote attraversano due anni: l'importo va tutto all'anno della data «dal»."
        )
    somma = sum((q.importo for q in voce.quote), ZERO)
    if voce.quote and somma < arrotonda(voce.importo_fisso):
        avvisi.append(
            "La somma delle quote è inferiore all'importo fisso: il resto è «SAL non "
            "pianificato» e resta fuori dai totali."
        )
    return avvisi


def _quote_usabili(voce: Voce, esiti: list[Esito]) -> tuple[Quota, ...]:
    quote = tuple(sorted(voce.quote, key=lambda q: (q.inizio, q.fine)))
    if not quote:
        return ()
    if any(q.fine < q.inizio for q in quote) or errori_quote(
        arrotonda(voce.importo_fisso), [(q.inizio, q.fine, q.importo) for q in quote]
    ):
        esiti.append(
            Esito(
                "QUOTE_INCOERENTI",
                "Quote per periodo di una voce a SAL sovrapposte o con somma superiore al "
                "fisso: ignorate.",
            )
        )
        return ()
    if any(q.inizio.year != q.fine.year for q in quote):
        esiti.append(
            Esito(
                "SAL_QUOTA_A_CAVALLO",
                "Quota per periodo a cavallo di due anni: tutto l'importo va all'anno della "
                "data «dal».",
            )
        )
    return quote


# --- Ripartizione --------------------------------------------------------------------------------


def _consuntivi(voce: Voce) -> tuple[list[Consuntivo], list[Consuntivo]]:
    """Fatture e stanziamenti della voce, abbinati a una rata o no."""
    tutti = [r.consuntivo for r in (voce.rate or ()) if r.consuntivo is not None]
    tutti += voce.consuntivi
    return (
        [c for c in tutti if c.tipo == TipoConsuntivo.FATTURA],
        [c for c in tutti if c.tipo == TipoConsuntivo.STANZIAMENTO],
    )


def _taglia(previsto: dict[int, Decimal], massimo: Decimal) -> dict[int, Decimal]:
    """Toglie l'eccedenza sul massimo dagli anni più lontani."""
    eccedenza = sum(previsto.values(), ZERO) - massimo
    risultato = dict(previsto)
    for anno in sorted(risultato, reverse=True):
        if eccedenza <= 0:
            break
        tolto = min(risultato[anno], eccedenza)
        risultato[anno] -= tolto
        eccedenza -= tolto
    return {a: i for a, i in risultato.items() if i}


def ripartisci_sal(voce: Voce, variabile: Decimal, vista: str) -> RipartoSal:
    """Consuntivo, previsto e non pianificato di una voce a SAL nella vista data.

    ``variabile`` è la quota variabile del livello richiesto (zero al livello fisso): non ha un
    calendario e segue il previsto del fisso.
    """
    esiti: list[Esito] = []
    fisso = arrotonda(voce.importo_fisso)
    fatture, stanziamenti = _consuntivi(voce)
    cassa = vista == VISTA_CASSA

    # Consuntivo.
    usati = fatture if cassa else [*fatture, *stanziamenti]
    righe: list[RigaConsuntivoSal] = []
    for c in usati:
        riferimento = c.riferimento if c.tipo == TipoConsuntivo.FATTURA else None
        if cassa:
            data = c.data or c.inizio
            righe.append(RigaConsuntivoSal(data.year, c.importo, riferimento))
            if data < voce.inizio or data > voce.fine:
                esiti.append(
                    Esito(
                        "FATTURA_FUORI_PERIODO",
                        "Fattura di una voce a SAL con data fuori dal periodo di servizio: "
                        "contata nell'anno della data documento.",
                    )
                )
        else:
            righe += [
                RigaConsuntivoSal(anno, importo, riferimento)
                for anno, importo in a_giorni(c.importo, c.inizio, c.fine).items()
            ]
    consumato = sum((r.importo for r in righe), ZERO)
    ultimo_anno = max(
        [r.anno for r in righe] if cassa else [c.fine.year for c in usati], default=None
    )
    residuo = max(fisso - consumato, ZERO)
    if consumato > fisso:
        esiti.append(
            Esito(
                "SAL_FATTURATO_SUPERA_FISSO",
                "Fatture di una voce a SAL oltre l'importo fisso: contate per intero, nessun "
                "previsto.",
            )
        )

    # Previsto del fisso: rate inserite a mano o, senza rate, quote per periodo.
    previsto: dict[int, Decimal] = {}
    fonti = [FONTE_FATTURE] if righe else []
    rate = voce.rate or ()
    if rate:
        for rata in rate:
            c = rata.consuntivo
            # Una rata con fattura è già nel consuntivo; con uno stanziamento resta la
            # previsione di cassa, ma nel consuntivo è lo stanziamento a prenderne il posto.
            if c is not None and (c.tipo == TipoConsuntivo.FATTURA or not cassa):
                continue
            if not cassa and rata.periodo_inizio and rata.periodo_fine:
                parti = a_giorni(rata.importo, rata.periodo_inizio, rata.periodo_fine)
            else:
                parti = {rata.data_fattura.year: rata.importo}
            for anno, importo in parti.items():
                previsto[anno] = previsto.get(anno, ZERO) + importo
        if previsto:
            fonti.append(FONTE_RATE)
        if voce.quote:
            esiti.append(
                Esito(
                    "SAL_QUOTE_E_RATE",
                    "Voce a SAL con rate e quote per periodo: il previsto viene dalle rate, "
                    "le quote non si contano.",
                )
            )
    else:
        for q in _quote_usabili(voce, esiti):
            anno = q.inizio.year
            if q.importo and (ultimo_anno is None or anno > ultimo_anno):
                previsto[anno] = previsto.get(anno, ZERO) + q.importo
        if previsto:
            fonti.append(FONTE_QUOTE)

    if sum(previsto.values(), ZERO) > residuo:
        previsto = _taglia(previsto, residuo)
        esiti.append(
            Esito(
                "SAL_PREVISTO_ECCEDENTE",
                "Rate o quote di una voce a SAL oltre il residuo dell'importo fisso: il "
                "previsto è limitato al residuo, dagli anni più lontani.",
            )
        )
    previsto_fisso = sum(previsto.values(), ZERO)
    non_pianificato_fisso = residuo - previsto_fisso
    if non_pianificato_fisso > 0:
        esiti.append(
            Esito(
                "SAL_NON_PIANIFICATO",
                f"SAL non pianificato: {formato_euro(non_pianificato_fisso)} dell'importo fisso "
                "senza rate, quote né fatture. Resta fuori dai totali; nessuna ripartizione a "
                "giorni.",
            )
        )

    # Variabile: segue il previsto del fisso; senza previsto resta non pianificato.
    non_pianificato = non_pianificato_fisso
    if variabile:
        if previsto_fisso:
            anni = sorted(previsto)
            for anno, quota in zip(
                anni, ripartisci(variabile, [previsto[a] for a in anni]), strict=True
            ):
                previsto[anno] += quota
        else:
            non_pianificato += variabile

    return RipartoSal(
        consuntivo=tuple(righe),
        previsto=previsto,
        non_pianificato=non_pianificato,
        fonti=tuple(fonti),
        esiti=tuple(esiti),
        consuntivi_usati=tuple(usati),
    )
