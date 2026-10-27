"""Spese per WBS (F9.2): per una WBS, di cluster o a progetto, i contratti e gli importi anno
per anno. Solo contratti registrati (niente previsti): è la spesa sostenuta o impegnata sulla
WBS, anche oltre i budget dei cluster (le WBS a progetto ne sono fuori).

Voci a SAL (Rev29), nelle viste «Fatturato» e «Fatturato e stanziato»: il costo reale sta sulla
WBS della fattura (se indicata, altrimenti quella della voce) e il residuo previsionale su quella
della voce. Consuntivo (fatture) e previsto (rate o quote) restano separati; ``per_anno`` è il
totale. Una fattura con WBS diversa da quella della voce compare come anomalia.
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Q

from contratti import adapters
from contratti import models as m
from contratti.engine import budget as motore
from contratti.engine import sal
from contratti.engine.acquisti import formato_euro
from contratti.engine.importi import ZERO
from contratti.engine.tipi import Esito, Livello

# Fonte dell'importo, per vista: cosa rappresentano le cifre della riga di una voce non a SAL.
FONTI_VOCE = {
    "cassa": "rate del piano",
    "consuntivo": "fatture e stanziamenti (competenza); rate dove mancano",
    "impegno": "valore contrattuale nell'anno di impegno",
    "competenza": "pro-rata a giorni sul periodo di servizio",
}
VISTE_CON_SAL = (sal.VISTA_CASSA, sal.VISTA_CONSUNTIVO)
NOMI_FONTI_SAL = {
    sal.FONTE_FATTURE: "fatture registrate",
    sal.FONTE_RATE: "rate a mano",
    sal.FONTE_QUOTE: "quote per periodo",
}


@dataclass
class RigaWBS:
    voce: m.VoceContratto
    contratto: m.Contratto
    inizio: datetime.date
    fine: datetime.date
    per_anno: dict[int, Decimal]
    # Solo voci a SAL (Rev29): le due componenti di ``per_anno``, il residuo fuori dai totali,
    # la fonte degli importi e gli avvisi del calcolo.
    consuntivo: dict[int, Decimal] = field(default_factory=dict)
    previsto: dict[int, Decimal] = field(default_factory=dict)
    non_pianificato: Decimal = ZERO
    fonte: str = ""
    avvisi: list[str] = field(default_factory=list)
    anomalie: list[str] = field(default_factory=list)
    a_sal: bool = False


@dataclass
class SpeseWBS:
    wbs: m.WBS
    vista: str
    livello: Livello
    righe: list[RigaWBS] = field(default_factory=list)
    esclusi: list[str] = field(default_factory=list)  # contratti senza data di inizio

    @property
    def anni(self) -> list[int]:
        return sorted({a for r in self.righe for a in r.per_anno})

    def totali(self) -> dict[int, Decimal]:
        return {a: sum((r.per_anno.get(a, ZERO) for r in self.righe), ZERO) for a in self.anni}

    @property
    def totale(self) -> Decimal:
        return sum(self.totali().values(), ZERO)

    @property
    def con_sal(self) -> bool:
        return any(r.a_sal for r in self.righe)

    def totali_consuntivo(self) -> dict[int, Decimal]:
        """Parte dei totali che viene dalle fatture delle voci a SAL."""
        return {a: sum((r.consuntivo.get(a, ZERO) for r in self.righe), ZERO) for a in self.anni}

    def totali_previsto(self) -> dict[int, Decimal]:
        """Parte dei totali che viene da rate o quote delle voci a SAL (non ancora fatturato)."""
        return {a: sum((r.previsto.get(a, ZERO) for r in self.righe), ZERO) for a in self.anni}

    @property
    def non_pianificato(self) -> Decimal:
        """Residuo delle voci a SAL senza rate né quote: fuori dai totali."""
        return sum((r.non_pianificato for r in self.righe), ZERO)

    @property
    def anomalie(self) -> list[str]:
        return [a for r in self.righe for a in r.anomalie]

    @property
    def avvisi(self) -> list[str]:
        return list(dict.fromkeys(a for r in self.righe for a in r.avvisi))


def spese_wbs(wbs: m.WBS, vista: str = "cassa", livello: Livello = Livello.PROBABILE) -> SpeseWBS:
    """Voci (non archiviate, di contratti non archiviati) sulla WBS, importi per anno.

    Per le voci a SAL, nelle viste con le fatture, entrano anche le fatture che indicano questa
    WBS su una voce di un'altra WBS.
    """
    risultato = SpeseWBS(wbs, vista, livello)
    sulla_wbs = Q(voci__wbs=wbs, voci__archiviato=False)
    if vista in VISTE_CON_SAL:
        sulla_wbs |= Q(fatture__wbs=wbs, fatture__archiviato=False)
    contratti = (
        m.Contratto.objects.filter(sulla_wbs, archiviato=False)
        .distinct()
        .select_related("fabbisogno__cluster", "fornitore", "procedura")
        .prefetch_related(*adapters.PREFETCH_CALCOLO)
        .order_by("data_inizio", "pk")
    )
    with adapters.parametri_in_cache():
        for c in contratti:
            voci_engine, _ = adapters.voci_contratto(c)
            if c.data_inizio is None:
                risultato.esclusi.append(str(c))
                continue
            modelli = {v.pk: v for v in c.voci.all()}
            fatture = {f.pk: f for f in c.fatture.all()}
            for ve in voci_engine:
                riga = _riga(wbs, c, modelli[ve.riferimento], ve, vista, livello, fatture)
                if riga is not None:
                    risultato.righe.append(riga)
    return risultato


def _riga(wbs, contratto, voce, ve, vista, livello, fatture) -> RigaWBS | None:
    if vista in VISTE_CON_SAL and sal.e_sal(ve):
        return _riga_sal(wbs, contratto, voce, ve, vista, livello, fatture)
    if voce.wbs_id != wbs.pk:
        return None
    per_anno, esiti = importi_con_esiti(ve, vista, livello)
    return RigaWBS(
        voce, contratto, ve.inizio, ve.fine, per_anno, fonte=FONTI_VOCE[vista],
        avvisi=[e.messaggio for e in esiti],
    )  # fmt: skip


def _riga_sal(wbs, contratto, voce, ve, vista, livello, fatture) -> RigaWBS | None:
    """Voce a SAL: le fatture sulla WBS della fattura (o della voce), il residuo su quella della
    voce."""
    ripartizione, esiti = motore.ripartizione_sal(ve, livello, vista)

    def wbs_id_di(riferimento):
        fattura = fatture.get(riferimento)
        return (fattura.wbs_id if fattura is not None else None) or voce.wbs_id

    riferimenti = {r.riferimento for r in ripartizione.consuntivo}
    qui = {r for r in riferimenti if wbs_id_di(r) == wbs.pk}
    consuntivo = ripartizione.consuntivo_per_anno(qui)
    della_voce = voce.wbs_id == wbs.pk
    if not della_voce and not consuntivo:
        return None
    previsto = ripartizione.previsto if della_voce else {}
    anomalie = []
    for c in ripartizione.consuntivi_usati:
        fattura = fatture.get(c.riferimento)
        if fattura is None or not fattura.wbs_id or fattura.wbs_id == voce.wbs_id:
            continue
        anomalie.append(
            f"Fattura {fattura.numero} del {fattura.data:%d/%m/%Y} "
            f"({formato_euro(c.importo)}): WBS della fattura {fattura.wbs.codice_wbs}, "
            f"diversa da quella della voce ({voce.wbs.codice_wbs if voce.wbs_id else 'nessuna'}). "
            f"{contratto.numero_contratto or contratto.fornitore} — {voce.descrizione}."
        )
    per_anno = dict(consuntivo)
    for anno, importo in previsto.items():
        per_anno[anno] = per_anno.get(anno, ZERO) + importo
    fonti = [NOMI_FONTI_SAL[f] for f in ripartizione.fonti]
    return RigaWBS(
        voce, contratto, ve.inizio, ve.fine,
        {a: i for a, i in sorted(per_anno.items()) if i},
        consuntivo={a: i for a, i in sorted(consuntivo.items()) if i},
        previsto={a: i for a, i in sorted(previsto.items()) if i},
        non_pianificato=ripartizione.non_pianificato if della_voce else ZERO,
        fonte="SAL: " + (", ".join(fonti) if fonti else "nessuna fonte"),
        avvisi=[e.messaggio for e in esiti] if della_voce else [],
        anomalie=anomalie, a_sal=True,
    )  # fmt: skip


def importi_con_esiti(ve, vista: str, livello: Livello) -> tuple[dict[int, Decimal], list[Esito]]:
    """Importi della voce (motore) per ogni anno in cui ne ha, nella vista e al livello dati,
    con gli avvisi del calcolo."""
    viste, esiti = motore.calcola([ve])
    per_anno = {
        anno: importi[livello]
        for anno, importi in sorted(viste[vista].per_anno.items())
        if importi.get(livello, ZERO)
    }
    return per_anno, esiti


def importi_per_anno(ve, vista: str, livello: Livello) -> dict[int, Decimal]:
    """Importi della voce (motore) per ogni anno in cui ne ha, nella vista e al livello dati."""
    return importi_con_esiti(ve, vista, livello)[0]


def elenco_wbs(
    codici_cluster: list[str],
    tipo: str = "",
    archiviate: bool = False,
    sottocluster: int | None = None,
):
    """WBS con il numero di voci; di default quelle dei cluster dati e tutte le WBS a progetto.

    Con ``sottocluster``: solo le WBS con almeno una voce di un fabbisogno di quel sottocluster,
    e il numero di voci conta solo quelle.
    """
    voci = Q(voci__archiviato=False, voci__contratto__archiviato=False)
    if sottocluster:
        voci &= Q(voci__contratto__fabbisogno__sottocluster_id=sottocluster)
    qs = m.WBS.objects.select_related("cluster").annotate(
        n_voci=Count("voci", filter=voci, distinct=True)
    )
    if sottocluster:
        qs = qs.filter(n_voci__gt=0)
    if not archiviate:
        qs = qs.filter(archiviato=False)
    if tipo:
        qs = qs.filter(tipo=tipo)
    if codici_cluster:
        qs = qs.filter(Q(tipo=m.WBS.Tipo.PROGETTO) | Q(cluster__codice__in=codici_cluster))
    return qs.order_by("tipo", "codice_wbs")
