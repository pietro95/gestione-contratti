"""Budget dell'anno X: tre viste × tre livelli, consolidato e previsionale (SPEC §5.2-5.3).

Ogni voce (reale o prevista) si calcola con il motore da sola; i totali del report sono
somme di questi importi, quindi coincidono al centesimo con il motore sull'insieme.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from contratti import adapters
from contratti import models as m
from contratti.engine import budget
from contratti.engine.importi import ZERO
from contratti.engine.tipi import Esito, Livello, Voce

VISTE = ("impegno", "cassa", "competenza")
ETICHETTE_VISTE = {
    "impegno": "Impegno (ordini)",
    "cassa": "Cassa (data fattura)",
    "competenza": "Competenza",
}
LIVELLI = tuple(Livello)
PARTI = ("consolidato", "previsionale", "totale")
RAGGRUPPAMENTI = {
    "conto": "Conto",
    "area": "Area",
    "fornitore": "Fornitore",
    "finanziamento": "Finanziamento",
    "fabbisogno": "Fabbisogno",
}

# vista → livello → importo
Somme = dict[str, dict[Livello, Decimal]]


def somme_vuote() -> Somme:
    return {vista: dict.fromkeys(LIVELLI, ZERO) for vista in VISTE}


def _somma(a: Somme, b: Somme) -> None:
    for vista in VISTE:
        for livello in LIVELLI:
            a[vista][livello] += b[vista][livello]


@dataclass(frozen=True)
class Filtri:
    anno: int
    area: str = ""
    conto: int | None = None
    fornitore: int | None = None
    finanziamento: str = ""
    previsionali: bool = True


@dataclass
class VoceBudget:
    """Una voce che contribuisce al budget dell'anno, con i suoi importi."""

    previsionale: bool
    fabbisogno: m.Fabbisogno
    contratto: m.Contratto | None  # reale, o contratto di partenza del previsto
    voce: m.VoceContratto | None  # reale, o voce d'origine del previsto
    descrizione: str
    inizio: datetime.date
    fine: datetime.date
    importi: Somme
    numero_previsto: int | None = None
    esiti: list[Esito] = field(default_factory=list)

    @property
    def area(self) -> str:
        return self.fabbisogno.area

    @property
    def conto(self) -> m.ContoCoge | None:
        return self.voce.conto if self.voce else None

    @property
    def fornitore(self) -> m.Fornitore | None:
        return self.contratto.fornitore if self.contratto else None

    @property
    def finanziamento(self) -> str:
        if self.contratto is None:
            return m.Contratto.Finanziamento.ORDINARIO
        return self.contratto.finanziamento

    def gruppo(self, criterio: str) -> tuple[str, str]:
        """(chiave, etichetta) del gruppo a cui appartiene la voce."""
        if criterio == "conto":
            c = self.conto
            return (c.codice, str(c)) if c else ("", "(conto non indicato)")
        if criterio == "area":
            return self.area, self.area
        if criterio == "fornitore":
            f = self.fornitore
            return (str(f.pk), str(f)) if f else ("", "(nuovo fabbisogno, fornitore da scegliere)")
        if criterio == "finanziamento":
            return self.finanziamento, m.Contratto.Finanziamento(self.finanziamento).label
        return str(self.fabbisogno.pk), str(self.fabbisogno)


@dataclass
class RinnovoMancante:
    fabbisogno: m.Fabbisogno
    previsti_esclusi: int
    dal: datetime.date
    al: datetime.date


@dataclass
class Budget:
    filtri: Filtri
    oggi: datetime.date
    voci: list[VoceBudget]
    rinnovi_mancanti: list[RinnovoMancante]
    avvisi: dict[str, list[str]]  # messaggio → voci interessate
    senza_data: int  # contratti esclusi perché senza data di inizio

    def totali(self) -> dict[str, Somme]:
        return _totali(self.voci)

    def gruppi(self, criterio: str) -> list["Gruppo"]:
        per_chiave: dict[str, list[VoceBudget]] = defaultdict(list)
        etichette: dict[str, str] = {}
        for v in self.voci:
            chiave, etichetta = v.gruppo(criterio)
            per_chiave[chiave].append(v)
            etichette[chiave] = etichetta
        gruppi = [Gruppo(k, etichette[k], vv, _totali(vv)) for k, vv in per_chiave.items()]
        return sorted(gruppi, key=lambda g: g.etichetta.lower())


@dataclass
class Gruppo:
    chiave: str
    etichetta: str
    voci: list[VoceBudget]
    totali: dict[str, Somme]


def _totali(voci: list[VoceBudget]) -> dict[str, Somme]:
    totali = {parte: somme_vuote() for parte in PARTI}
    for v in voci:
        _somma(totali["previsionale" if v.previsionale else "consolidato"], v.importi)
        _somma(totali["totale"], v.importi)
    return totali


def importi_anno(voce: Voce, anno: int) -> tuple[Somme, list[Esito]]:
    """Importi della singola voce nell'anno, per vista e livello (motore)."""
    viste, esiti = budget.calcola([voce])
    importi = somme_vuote()
    for vista in VISTE:
        for livello, importo in viste[vista].per_anno.get(anno, {}).items():
            importi[vista][livello] = importo
    return importi, esiti


def _non_nulla(importi: Somme) -> bool:
    return any(importi[v][liv] for v in VISTE for liv in LIVELLI)


def orizzonte_report(anno: int, oggi: datetime.date) -> datetime.date:
    """Previsti almeno fino al 31/12 dell'anno del report (anche oltre l'orizzonte)."""
    return max(adapters.orizzonte_default(oggi), datetime.date(anno, 12, 31))


def _contratti(filtri: Filtri):
    qs = m.Contratto.objects.filter(archiviato=False, fabbisogno__archiviato=False)
    if filtri.area:
        qs = qs.filter(fabbisogno__area=filtri.area)
    if filtri.fornitore:
        qs = qs.filter(fornitore_id=filtri.fornitore)
    if filtri.finanziamento:
        qs = qs.filter(finanziamento=filtri.finanziamento)
    return qs.select_related("fabbisogno", "fornitore", "procedura").prefetch_related(
        *adapters.PREFETCH_CALCOLO
    )


def calcola_budget(filtri: Filtri, oggi: datetime.date) -> Budget:
    with adapters.parametri_in_cache():
        return _calcola_budget(filtri, oggi)


def _calcola_budget(filtri: Filtri, oggi: datetime.date) -> Budget:
    voci: list[VoceBudget] = []
    avvisi: dict[str, list[str]] = defaultdict(list)
    contratti = _contratti(filtri)
    senza_data = contratti.filter(data_inizio__isnull=True).count()

    for c in contratti.filter(data_inizio__isnull=False).order_by("pk"):
        modelli = {v.pk: v for v in c.voci.all()}
        voci_engine, _ = adapters.voci_contratto(c)
        for ve in voci_engine:
            voce = modelli[ve.riferimento]
            if filtri.conto and voce.conto_id != filtri.conto:
                continue
            importi, esiti = importi_anno(ve, filtri.anno)
            if not _non_nulla(importi):
                continue
            vb = VoceBudget(
                previsionale=False,
                fabbisogno=c.fabbisogno,
                contratto=c,
                voce=voce,
                descrizione=voce.descrizione,
                inizio=ve.inizio,
                fine=ve.fine,
                importi=importi,
                esiti=esiti,
            )
            voci.append(vb)

    rinnovi_mancanti: list[RinnovoMancante] = []
    if filtri.previsionali:
        voci_prev, rinnovi_mancanti = _voci_previste(filtri, oggi)
        voci += voci_prev

    for vb in voci:
        for e in vb.esiti:
            avvisi[e.messaggio].append(f"{vb.fabbisogno} — {vb.descrizione}")
    return Budget(filtri, oggi, voci, rinnovi_mancanti, dict(avvisi), senza_data)


def _voci_previste(filtri: Filtri, oggi: datetime.date):
    inizio_anno = datetime.date(filtri.anno, 1, 1)
    orizzonte = orizzonte_report(filtri.anno, oggi)
    fabbisogni = (
        m.Fabbisogno.objects.filter(archiviato=False)
        .select_related("categoria", "previsto_procedura")
        .prefetch_related(*adapters.PREFETCH_FABBISOGNO)
    )
    if filtri.area:
        fabbisogni = fabbisogni.filter(area=filtri.area)
    voci: list[VoceBudget] = []
    mancanti: list[RinnovoMancante] = []
    for f in fabbisogni.order_by("pk"):
        base = adapters.contratto_base_previsti(f)
        if filtri.fornitore and (base is None or base.fornitore_id != filtri.fornitore):
            continue
        finanziamento = base.finanziamento if base else m.Contratto.Finanziamento.ORDINARIO
        if filtri.finanziamento and finanziamento != filtri.finanziamento:
            continue
        previsti = adapters.previsti_fabbisogno(f, orizzonte)
        # SPEC §5.3: nell'anno X entrano solo i previsti che finiscono dal 01/01/X in poi.
        esclusi = [p for p in previsti if p.fine < inizio_anno]
        passati = [p for p in esclusi if p.fine < oggi]
        if passati:
            mancanti.append(RinnovoMancante(f, len(passati), passati[0].inizio, passati[-1].fine))
        riferimenti = {v.riferimento for p in previsti for v in p.voci if v.riferimento}
        modelli = m.VoceContratto.objects.select_related("conto").in_bulk(riferimenti)
        for p in previsti:
            if p.fine < inizio_anno:
                continue
            for ve in p.voci:
                voce = modelli.get(ve.riferimento)
                if filtri.conto and (voce is None or voce.conto_id != filtri.conto):
                    continue
                importi, esiti = importi_anno(ve, filtri.anno)
                if not _non_nulla(importi):
                    continue
                voci.append(
                    VoceBudget(
                        previsionale=True,
                        fabbisogno=f,
                        contratto=base,
                        voce=voce,
                        descrizione=voce.descrizione if voce else f.descrizione,
                        inizio=ve.inizio,
                        fine=ve.fine,
                        importi=importi,
                        numero_previsto=p.numero,
                        esiti=esiti,
                    )
                )
    return voci, mancanti
