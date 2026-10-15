"""Budget dell'anno X: tre viste × tre livelli, consolidato e previsionale (SPEC §5.2-5.3).

OPEX e CAPEX sono budget distinti: il report li tiene in sezioni separate, mai sommate.

Ogni voce (reale o prevista) si calcola con il motore da sola; i totali del report sono
somme di questi importi, quindi coincidono al centesimo con il motore sull'insieme.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field, replace
from decimal import Decimal

from contratti import adapters
from contratti import models as m
from contratti.engine import budget
from contratti.engine.importi import ZERO
from contratti.engine.tipi import Esito, Livello, Voce
from contratti.selettori import codici_cluster

# Rev21: il budget di riferimento è il consuntivo a competenza (fatture registrate e
# stanziamenti per periodo di competenza, rate previste dove manca il consuntivo): prima
# colonna. "impegno" resta il nome interno della vista (SPEC §5.2, TEST_CASES); in pagina è
# "Ordinato". La cassa (rate per data fattura) resta come confronto.
VISTE = ("consuntivo", "cassa", "impegno", "competenza")
ETICHETTE_VISTE = {
    "consuntivo": "Fatturato e stanziato (competenza)",
    "cassa": "Fatturato (data fattura)",
    "impegno": "Ordinato (contratti emessi)",
    "competenza": "Competenza del contratto (pro-rata a giorni)",
}
# Nomi brevi per le intestazioni delle colonne dell'export.
SIGLE_VISTE = {
    "consuntivo": "fatt+stanz competenza",
    "cassa": "fatturato data fattura",
    "impegno": "ordinato",
    "competenza": "competenza contratto",
}
NATURE = tuple(m.Natura.values)
LIVELLI = tuple(Livello)
PARTI = ("consolidato", "previsionale", "totale")
RAGGRUPPAMENTI = {
    "conto": "Conto",
    "area": "Cluster",
    "fornitore": "Fornitore",
    "wbs": "WBS",
    "fabbisogno": "Fabbisogno",
}
# Voci su WBS a progetto (es. dissalatori): fuori dai budget dei cluster (F9.2).
PROGETTI = {"": "Escluse", "includi": "Incluse", "solo": "Solo WBS a progetto"}
# Voci extra budget autorizzate dall'AD: fuori dai budget dei cluster (Rev18).
EXTRA_BUDGET = {"": "Escluse", "includi": "Incluse", "solo": "Solo extra budget"}

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
    area: str | tuple[str, ...] = ""  # codice di cluster o tupla di codici; vuoto = tutti
    conto: int | None = None
    fornitore: int | None = None
    progetti: str = ""  # voci su WBS a progetto: "" escluse, "includi", "solo"
    extra_budget: str = ""  # voci extra budget (Rev18): "" escluse, "includi", "solo"
    previsionali: bool = True
    natura: str = ""  # vuoto: entrambe, da presentare separate
    wbs: int | None = None

    def ammette(self, cl: adapters.Classificazione) -> bool:
        """La voce, con la sua classificazione, entra in questo budget?"""
        if self.natura and cl.natura != self.natura:
            return False
        if self.conto and (cl.conto is None or cl.conto.pk != self.conto):
            return False
        if self.wbs and (cl.wbs is None or cl.wbs.pk != self.wbs):
            return False
        extra = cl.extra_budget is not None
        if self.extra_budget == "solo" and not extra:
            return False
        if not extra and self.progetti == "solo" and not cl.a_progetto:
            return False
        if extra:
            return bool(self.extra_budget)
        return self.progetti in ("includi", "solo") or not cl.a_progetto


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
    # Natura, conto e WBS: della voce reale, o decisi per i suoi rinnovi (previsti).
    classe: adapters.Classificazione = field(
        default_factory=lambda: adapters.Classificazione(m.Natura.OPEX, None, None)
    )

    @property
    def area(self) -> str:
        return self.fabbisogno.area

    @property
    def natura(self) -> str:
        return self.classe.natura

    @property
    def conto(self) -> m.ContoCoge | None:
        return self.classe.conto

    @property
    def wbs(self) -> m.WBS | None:
        return self.classe.wbs

    @property
    def senza_contratto(self) -> bool:
        """Del contratto registrato, o del contratto di partenza del previsto."""
        return bool(self.contratto and self.contratto.senza_contratto)

    @property
    def fornitore(self) -> m.Fornitore | None:
        return self.contratto.fornitore if self.contratto else None

    @property
    def finanziamento(self) -> str:
        return self.classe.finanziamento

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
        if criterio == "wbs":
            w = self.wbs
            if w is not None:
                return w.codice_wbs, str(w)
            if self.natura == m.Natura.CAPEX:
                return "", "(CAPEX: WBS da indicare)"
            return "", "(OPEX: nessuna WBS)"
        return str(self.fabbisogno.pk), str(self.fabbisogno)


@dataclass
class RinnovoMancante:
    fabbisogno: m.Fabbisogno
    previsti_esclusi: int
    dal: datetime.date
    al: datetime.date
    nature: frozenset = frozenset({m.Natura.OPEX})


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

    def sezioni(self) -> list["Budget"]:
        """Un budget per natura: quella filtrata, oppure OPEX e CAPEX separati."""
        nature = [self.filtri.natura] if self.filtri.natura else NATURE
        return [self.di_natura(n) for n in nature]

    def di_natura(self, natura: str) -> "Budget":
        voci = [v for v in self.voci if v.natura == natura]
        avvisi: dict[str, list[str]] = defaultdict(list)
        for vb in voci:
            for e in vb.esiti:
                avvisi[e.messaggio].append(f"{vb.fabbisogno} — {vb.descrizione}")
        return Budget(
            filtri=replace(self.filtri, natura=natura),
            oggi=self.oggi,
            voci=voci,
            rinnovi_mancanti=[r for r in self.rinnovi_mancanti if natura in r.nature],
            avvisi=dict(avvisi),
            senza_data=self.senza_data,
        )

    def gruppi(self, criterio: str) -> list["Gruppo"]:
        return raggruppa(self.voci, criterio)


@dataclass
class Gruppo:
    chiave: str
    etichetta: str
    voci: list[VoceBudget]
    totali: dict[str, Somme]

    def sotto(self, criterio: str) -> list["Gruppo"]:
        """Dettaglio del gruppo, es. i conti di una WBS (come lo legge il CdG)."""
        return raggruppa(self.voci, criterio)


def raggruppa(voci: list[VoceBudget], criterio: str) -> list[Gruppo]:
    per_chiave: dict[str, list[VoceBudget]] = defaultdict(list)
    etichette: dict[str, str] = {}
    for v in voci:
        chiave, etichetta = v.gruppo(criterio)
        per_chiave[chiave].append(v)
        etichette[chiave] = etichetta
    gruppi = [Gruppo(k, etichette[k], vv, _totali(vv)) for k, vv in per_chiave.items()]
    return sorted(gruppi, key=lambda g: g.etichetta.lower())


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
    if codici := codici_cluster(filtri.area):
        qs = qs.filter(fabbisogno__cluster__codice__in=codici)
    if filtri.fornitore:
        qs = qs.filter(fornitore_id=filtri.fornitore)
    return qs.select_related("fabbisogno__cluster", "fornitore", "procedura").prefetch_related(
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
            classe = adapters.classificazione(voce)
            if not filtri.ammette(classe):
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
                classe=classe,
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
        .select_related(
            "cluster", "categoria", "previsto_procedura", "conto_previsti", "wbs_previsti"
        )
        .prefetch_related(*adapters.PREFETCH_FABBISOGNO)
    )
    if codici := codici_cluster(filtri.area):
        fabbisogni = fabbisogni.filter(cluster__codice__in=codici)
    voci: list[VoceBudget] = []
    mancanti: list[RinnovoMancante] = []
    for f in fabbisogni.order_by("pk"):
        base = adapters.contratto_base_previsti(f)
        if filtri.fornitore and (base is None or base.fornitore_id != filtri.fornitore):
            continue
        natura = adapters.natura_previsti(f, base)
        nature = frozenset(m.Natura.values) if natura == m.Contratto.MISTA else frozenset({natura})
        previsti = adapters.previsti_fabbisogno(f, orizzonte)
        # SPEC §5.3: nell'anno X entrano solo i previsti che finiscono dal 01/01/X in poi.
        esclusi = [p for p in previsti if p.fine < inizio_anno]
        passati = [p for p in esclusi if p.fine < oggi]
        if passati:
            mancanti.append(
                RinnovoMancante(f, len(passati), passati[0].inizio, passati[-1].fine, nature)
            )
        riferimenti = {v.riferimento for p in previsti for v in p.voci if v.riferimento}
        modelli = m.VoceContratto.objects.select_related(
            "conto", "wbs", "conto_rinnovi", "wbs_rinnovi"
        ).in_bulk(riferimenti)
        for p in previsti:
            if p.fine < inizio_anno:
                continue
            for ve in p.voci:
                voce = modelli.get(ve.riferimento)
                classe = adapters.classificazione_prevista(f, voce)
                if not filtri.ammette(classe):
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
                        classe=classe,
                    )
                )
    return voci, mancanti
