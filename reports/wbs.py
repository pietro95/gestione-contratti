"""Spese per WBS (F9.2): per una WBS, di cluster o a progetto, i contratti e gli importi anno
per anno. Solo contratti registrati (niente previsti): è la spesa sostenuta o impegnata sulla
WBS, anche oltre i budget dei cluster (le WBS a progetto ne sono fuori).
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Q

from contratti import adapters
from contratti import models as m
from contratti.engine import budget as motore
from contratti.engine.importi import ZERO
from contratti.engine.tipi import Livello


@dataclass
class RigaWBS:
    voce: m.VoceContratto
    contratto: m.Contratto
    inizio: datetime.date
    fine: datetime.date
    per_anno: dict[int, Decimal]


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


def spese_wbs(wbs: m.WBS, vista: str = "cassa", livello: Livello = Livello.PROBABILE) -> SpeseWBS:
    """Voci (non archiviate, di contratti non archiviati) sulla WBS, importi per anno."""
    risultato = SpeseWBS(wbs, vista, livello)
    contratti = (
        m.Contratto.objects.filter(archiviato=False, voci__wbs=wbs, voci__archiviato=False)
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
            for ve in voci_engine:
                voce = modelli[ve.riferimento]
                if voce.wbs_id != wbs.pk:
                    continue
                per_anno = importi_per_anno(ve, vista, livello)
                risultato.righe.append(RigaWBS(voce, c, ve.inizio, ve.fine, per_anno))
    return risultato


def importi_per_anno(ve, vista: str, livello: Livello) -> dict[int, Decimal]:
    """Importi della voce (motore) per ogni anno in cui ne ha, nella vista e al livello dati."""
    viste, _ = motore.calcola([ve])
    return {
        anno: importi[livello]
        for anno, importi in sorted(viste[vista].per_anno.items())
        if importi.get(livello, ZERO)
    }


def elenco_wbs(codici_cluster: list[str], tipo: str = "", archiviate: bool = False):
    """WBS con il numero di voci; di default quelle dei cluster dati e tutte le WBS a progetto."""
    qs = m.WBS.objects.select_related("cluster").annotate(
        n_voci=Count(
            "voci",
            filter=Q(voci__archiviato=False, voci__contratto__archiviato=False),
            distinct=True,
        )
    )
    if not archiviate:
        qs = qs.filter(archiviato=False)
    if tipo:
        qs = qs.filter(tipo=tipo)
    if codici_cluster:
        qs = qs.filter(Q(tipo=m.WBS.Tipo.PROGETTO) | Q(cluster__codice__in=codici_cluster))
    return qs.order_by("tipo", "codice_wbs")
