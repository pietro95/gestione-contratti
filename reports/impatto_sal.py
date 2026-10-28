"""Impatto della Rev29 sulle voci a SAL: per ogni voce, il fatturato per anno prima e dopo.

«Prima» è il calcolo precedente alla Rev29: una voce a SAL trattata come «Da verificare», cioè con
le rate salvate se ci sono e altrimenti la ripartizione a mesi frazionati (nel consuntivo sommato
anche alle fatture non abbinate). «Dopo» è il calcolo attuale. Solo lettura: serve a vedere,
prima del rilascio, quali totali cambiano. Si usa dal comando ``impatto_sal``.
"""

import datetime
from dataclasses import dataclass, field, replace
from decimal import Decimal

from contratti import adapters
from contratti import models as m
from contratti.engine import budget as motore
from contratti.engine import sal
from contratti.engine.importi import ZERO
from contratti.engine.tipi import Livello, Modalita, TipoConsuntivo
from reports import xlsx
from reports.budget import ETICHETTE_VISTE

VISTE_IMPATTO = ("cassa", "consuntivo")


@dataclass
class RigaImpatto:
    contratto: m.Contratto
    voce: m.VoceContratto
    cluster: str
    importo_fisso: Decimal
    fatturato: Decimal  # fatture registrate, valore base
    n_fatture: int
    n_quote: int
    somma_quote: Decimal
    n_rate: int
    # vista → anno → importo
    prima: dict[str, dict[int, Decimal]] = field(default_factory=dict)
    dopo: dict[str, dict[int, Decimal]] = field(default_factory=dict)
    non_pianificato: dict[str, Decimal] = field(default_factory=dict)
    avvisi: list[str] = field(default_factory=list)

    @property
    def fonti(self) -> str:
        fonti = []
        if self.n_fatture:
            fonti.append("fatture")
        if self.n_rate:
            fonti.append("rate a mano")
        elif self.n_quote:
            fonti.append("quote")
        return ", ".join(fonti) or "nessuna: tutto non pianificato"

    def delta(self, vista: str, anno: int) -> Decimal:
        return self.dopo[vista].get(anno, ZERO) - self.prima[vista].get(anno, ZERO)


def _per_anno(viste, vista: str, livello: Livello) -> dict[int, Decimal]:
    return {a: i[livello] for a, i in sorted(viste[vista].per_anno.items()) if i.get(livello, ZERO)}


def righe_impatto(livello: Livello = Livello.PROBABILE) -> list[RigaImpatto]:
    """Le voci a SAL (non archiviate, di contratti non archiviati) con prima e dopo."""
    contratti = (
        m.Contratto.objects.filter(
            archiviato=False,
            voci__archiviato=False,
            voci__piano_fatturazione__modalita=m.ModalitaFatturazione.SAL,
        )
        .distinct()
        .select_related("fabbisogno__cluster", "fornitore")
        .prefetch_related(*adapters.PREFETCH_CALCOLO)
        .order_by("fabbisogno__cluster__codice", "data_inizio", "pk")
    )
    righe = []
    with adapters.parametri_in_cache():
        for c in contratti:
            voci_engine, _ = adapters.voci_contratto(c)
            modelli = {v.pk: v for v in c.voci.all()}
            for ve in voci_engine:
                if sal.e_sal(ve):
                    righe.append(_riga(c, modelli[ve.riferimento], ve, livello))
    return righe


def _riga(contratto, voce, ve, livello: Livello) -> RigaImpatto:
    # Il calcolo precedente: la stessa voce con modalità «Da verificare» (rate salvate o, senza,
    # ripartizione a mesi frazionati).
    prima_ve = replace(ve, piano=replace(ve.piano, modalita=Modalita.DA_VERIFICARE))
    viste_prima, _ = motore.calcola([prima_ve])
    viste_dopo, esiti = motore.calcola([ve])
    consuntivi = [r.consuntivo for r in (ve.rate or ()) if r.consuntivo] + list(ve.consuntivi)
    fatture = [c for c in consuntivi if c.tipo == TipoConsuntivo.FATTURA]
    riga = RigaImpatto(
        contratto=contratto,
        voce=voce,
        cluster=contratto.fabbisogno.cluster.codice,
        importo_fisso=ve.importo_fisso,
        fatturato=sum((c.importo for c in fatture), ZERO),
        n_fatture=len(fatture),
        n_quote=len(ve.quote),
        somma_quote=sum((q.importo for q in ve.quote), ZERO),
        n_rate=len(ve.rate or ()),
        avvisi=[e.messaggio for e in esiti if e.codice.startswith(("SAL_", "QUOTE_", "FATTURA_"))],
    )
    for vista in VISTE_IMPATTO:
        riga.prima[vista] = _per_anno(viste_prima, vista, livello)
        riga.dopo[vista] = _per_anno(viste_dopo, vista, livello)
        ripartizione, _ = motore.ripartizione_sal(ve, livello, vista)
        riga.non_pianificato[vista] = ripartizione.non_pianificato
    return riga


def _anni(righe: list[RigaImpatto]) -> list[int]:
    return sorted(
        {a for r in righe for vista in VISTE_IMPATTO for d in (r.prima[vista], r.dopo[vista])
         for a in d}
    )  # fmt: skip


def impatto_xlsx(righe: list[RigaImpatto], livello: Livello, oggi: datetime.date):
    wb = xlsx.nuovo_libro()
    anni = _anni(righe)
    intestazione = [
        "Impatto della Rev29 sulle voci a SAL",
        f"Livello {livello.value}. Prima = calcolo precedente (rate salvate, altrimenti "
        "ripartizione a mesi frazionati); dopo = fatture, poi rate a mano o quote, mai la "
        "ripartizione sul tempo.",
        "Importi imponibili (IVA esclusa). Solo lettura: nessun dato è stato modificato.",
        f"Generato il {oggi:%d/%m/%Y}.",
    ]

    # 1. Riepilogo: totali per anno, e per cluster e anno.
    riepilogo = []
    for vista in VISTE_IMPATTO:
        for anno in anni:
            prima = sum((r.prima[vista].get(anno, ZERO) for r in righe), ZERO)
            dopo = sum((r.dopo[vista].get(anno, ZERO) for r in righe), ZERO)
            riepilogo.append(["Tutti", ETICHETTE_VISTE[vista], anno, prima, dopo, dopo - prima])
    for cluster in sorted({r.cluster for r in righe}):
        for vista in VISTE_IMPATTO:
            for anno in anni:
                prima = sum(
                    (r.prima[vista].get(anno, ZERO) for r in righe if r.cluster == cluster), ZERO
                )  # noqa: E501
                dopo = sum(
                    (r.dopo[vista].get(anno, ZERO) for r in righe if r.cluster == cluster), ZERO
                )  # noqa: E501
                if prima or dopo:
                    riepilogo.append(
                        [cluster, ETICHETTE_VISTE[vista], anno, prima, dopo, dopo - prima]
                    )
    xlsx.foglio(
        wb, "Totali per anno", intestazione,
        ["Cluster", "Vista", "Anno", "Prima", "Dopo", "Delta"], riepilogo,
    )  # fmt: skip

    # 2. Le voci: identità, importi e fonti.
    voci = [
        [
            r.cluster,
            r.contratto.numero_contratto or "",
            str(r.contratto.fornitore),
            r.voce.descrizione,
            r.voce.wbs.codice_wbs if r.voce.wbs_id else "",
            r.importo_fisso,
            r.fatturato,
            r.n_fatture,
            r.n_quote,
            r.somma_quote,
            r.n_rate,
            r.fonti,
            r.non_pianificato["cassa"],
            " | ".join(dict.fromkeys(r.avvisi)),
        ]
        for r in righe
    ]
    xlsx.foglio(
        wb, "Voci a SAL", intestazione,
        ["Cluster", "Contratto", "Fornitore", "Voce", "WBS", "Importo fisso",
         "Fatturato registrato", "N. fatture", "N. quote", "Somma quote", "N. rate a mano",
         "Fonte del fatturato", "SAL non pianificato", "Avvisi"],
        voci,
    )  # fmt: skip

    # 3. Per vista: una riga per voce, prima / dopo / delta per ogni anno.
    for vista, titolo in (("cassa", "Fatturato per anno"), ("consuntivo", "Consuntivo per anno")):
        colonne = ["Cluster", "Contratto", "Voce"]
        for anno in anni:
            colonne += [f"{anno} prima", f"{anno} dopo", f"{anno} delta"]
        tabella = []
        for r in righe:
            riga = [r.cluster, r.contratto.numero_contratto or str(r.contratto.fornitore),
                    r.voce.descrizione]  # fmt: skip
            for anno in anni:
                riga += [r.prima[vista].get(anno, ZERO), r.dopo[vista].get(anno, ZERO),
                         r.delta(vista, anno)]  # fmt: skip
            tabella.append(riga)
        xlsx.foglio(wb, titolo, [*intestazione, f"Vista: {ETICHETTE_VISTE[vista]}"], colonne,
                    tabella)  # fmt: skip
    return wb
