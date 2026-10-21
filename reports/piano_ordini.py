"""Piano ordini dell'anno X per il Procurement (SPEC §5.4).

Una riga per ogni contratto previsto (automatico o manuale) la cui procedura, dalla data limite
di avvio all'avvio del servizio, tocca l'anno X:
- «da avviare»: data limite nell'anno X; solo queste righe entrano nei totali;
- «da concludere»: procedura da avviare in un anno precedente, ordine da emettere entro l'avvio
  del servizio, nell'anno X o dopo. Nel piano dell'anno in corso sono da concludere anche i
  previsti con servizio già partito (non finito prima dell'anno) e pratica non conclusa.
Nell'anno in corso una riga è «in ritardo» se la data limite è passata e la pratica non è
avviata, o se il servizio doveva già partire. Una pratica conclusa toglie le righe da concludere.
Restano fuori i rinnovi senza contratto (non si ordinano tramite il Procurement, SPEC §5.6).
Il Procurement ordina sia OPEX sia CAPEX: il piano li contiene in sezioni separate, con i totali
propri, mai sommati; un contratto misto compare in entrambe con la sola quota della natura.
Nelle sezioni le righe sono raggruppate per cluster e sottocluster, con i subtotali.

Oltre ai previsti, il piano riporta i contratti già registrati (in stipula o stipulati) che
pesano nell'anno, cioè con competenza dell'anno diversa da zero: fase «registrato», fuori dai
totali del valore contrattuale (sono già ordinati). Ogni riga ha il valore contrattuale
(intera durata) e il valore normalizzato sull'anno (competenza pro-rata a giorni, SPEC §5.2).
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Max, Q

from contratti import acquisti, adapters
from contratti import models as m
from contratti.engine.budget import valore
from contratti.engine.date import UN_GIORNO, aggiungi_mesi
from contratti.engine.importi import ZERO
from contratti.engine.tipi import ContrattoPrevisto, Livello, Voce
from contratti.selettori import codici_cluster
from reports.budget import LIVELLI, NATURE, importi_anno, orizzonte_report

DA_AVVIARE = "da_avviare"
DA_CONCLUDERE = "da_concludere"
REGISTRATO = "registrato"
FONTE_ORDINARIA = "Ordinaria"
SENZA_SOTTOCLUSTER = "(senza sottocluster)"
PREVISTO = "Previsto"
IN_STIPULA = "In stipula"
STIPULATO = "Stipulato"

Importi = dict[Livello, Decimal]


@dataclass
class RigaPiano:
    fabbisogno: m.Fabbisogno
    contratto_uscente: m.Contratto | None
    procedura: m.Procedura | None
    lead_time_mesi: int
    data_limite: datetime.date | None  # None per i contratti registrati
    avvio: datetime.date
    fine: datetime.date
    durata_mesi: int
    stato_pratica: str | None
    importi: Importi  # valore contrattuale: intera durata
    numero_previsto: int
    natura: str = m.Natura.OPEX  # OPEX, CAPEX o "OPEX e CAPEX"
    # Importi per natura delle voci (F9.2: un contratto può avere quote OPEX e CAPEX).
    per_natura: dict[str, Importi] = field(default_factory=dict)
    a_progetto: bool = False
    sopra_soglia: list[str] = field(default_factory=list)
    in_ritardo: bool = False
    fase: str = "da_avviare"  # "da_concludere" (SPEC §5.4 Rev17) o "registrato"
    # Contratto già registrato (fase «registrato»); per i previsti è None.
    contratto: m.Contratto | None = None
    stato: str = PREVISTO  # Previsto, In stipula o Stipulato
    # Valore normalizzato sull'anno: competenza pro-rata a giorni (SPEC §5.2), totale e per natura.
    normalizzato: Importi = field(default_factory=dict)
    normalizzato_per_natura: dict[str, Importi] = field(default_factory=dict)
    fonti: dict[str, str] = field(default_factory=dict)  # fonte di finanziamento per natura

    @property
    def da_avviare(self) -> bool:
        return self.fase == DA_AVVIARE

    @property
    def registrato(self) -> bool:
        return self.fase == REGISTRATO

    @property
    def sottocluster(self) -> m.Sottocluster | None:
        return self.fabbisogno.sottocluster

    @property
    def fornitore_uscente(self) -> m.Fornitore | None:
        return self.contratto_uscente.fornitore if self.contratto_uscente else None

    @property
    def fornitore(self) -> m.Fornitore | None:
        """Fornitore del contratto registrato; per un previsto, quello uscente."""
        return self.contratto.fornitore if self.contratto else self.fornitore_uscente

    @property
    def fonte(self) -> str:
        return " / ".join(dict.fromkeys(self.fonti.values())) or FONTE_ORDINARIA

    @property
    def data_ordinamento(self) -> datetime.date:
        return self.data_limite or self.avvio

    @property
    def stato_pratica_label(self) -> str:
        if self.registrato:
            return "—"  # la pratica di rinnovo riguarda il contratto in scadenza
        if not self.stato_pratica:
            return "Non avviata"
        return m.StatoPratica.Stato(self.stato_pratica).label


@dataclass
class AvvisoFrazionamento:
    tipo: str  # "sottocluster" o "fornitore"
    nome: str
    soglia: m.Soglia
    totale_massimo: Decimal
    righe: list[RigaPiano]


@dataclass
class PianoOrdini:
    anno: int
    righe: list[RigaPiano]
    soglie: list[m.Soglia]
    avvisi: list[AvvisoFrazionamento]

    @property
    def in_ritardo(self) -> list[RigaPiano]:
        return [r for r in self.righe if r.in_ritardo]

    @property
    def da_avviare(self) -> list[RigaPiano]:
        return [r for r in self.righe if r.da_avviare]

    @property
    def da_concludere(self) -> list[RigaPiano]:
        return [r for r in self.righe if r.fase == DA_CONCLUDERE]

    @property
    def registrati(self) -> list[RigaPiano]:
        return [r for r in self.righe if r.registrato]

    def sezioni(self, natura: str = "") -> list["Sezione"]:
        """Una sezione per natura (OPEX, CAPEX), con cluster e sottocluster e i subtotali."""
        return [_sezione(n, self.righe) for n in NATURE if (not natura or n == natura)
                if any(n in r.per_natura for r in self.righe)]  # fmt: skip

    def totali(self, natura: str = "") -> dict[Livello, Decimal]:
        """Solo le righe da avviare: una da concludere è già contata nel piano del suo avvio."""
        totali = dict.fromkeys(LIVELLI, ZERO)
        for r in self.da_avviare:
            importi = r.per_natura.get(natura) if natura else r.importi
            for livello in LIVELLI:
                totali[livello] += (importi or {}).get(livello, ZERO)
        return totali

    def totali_per_natura(self) -> dict[str, dict[Livello, Decimal]]:
        """OPEX e CAPEX distinti: sono budget diversi anche quando si ordinano insieme."""
        nature = [n for n in NATURE if any(n in r.per_natura for r in self.da_avviare)]
        return {n: self.totali(n) for n in nature}


@dataclass
class RigaNatura:
    """Una riga del piano vista dalla sua sezione: la sola quota della natura."""

    riga: RigaPiano
    natura: str
    importi: Importi
    normalizzato: Importi
    fonte: str


@dataclass
class Totali:
    """Contrattuale: solo le righe da avviare. Normalizzato: tutte le righe (competenza)."""

    contrattuale: Importi = field(default_factory=lambda: dict.fromkeys(LIVELLI, ZERO))
    normalizzato: Importi = field(default_factory=lambda: dict.fromkeys(LIVELLI, ZERO))

    def aggiungi(self, r: RigaNatura) -> None:
        for livello in LIVELLI:
            self.normalizzato[livello] += r.normalizzato.get(livello, ZERO)
            if r.riga.da_avviare:
                self.contrattuale[livello] += r.importi.get(livello, ZERO)


@dataclass
class GruppoSottocluster:
    sottocluster: m.Sottocluster | None
    righe: list[RigaNatura] = field(default_factory=list)
    totali: Totali = field(default_factory=Totali)
    id_stipulati: str = ""  # classe HTML che lega la riga di riepilogo ai contratti espansi

    @property
    def nome(self) -> str:
        return self.sottocluster.nome if self.sottocluster else SENZA_SOTTOCLUSTER

    @property
    def stipulati(self) -> list[RigaNatura]:
        """Contratti già stipulati: la vista li raggruppa in una sola riga espandibile."""
        return [rn for rn in self.righe if rn.riga.stato == STIPULATO]

    @property
    def altre(self) -> list[RigaNatura]:
        return [rn for rn in self.righe if rn.riga.stato != STIPULATO]

    @property
    def riepilogo_stipulati(self) -> Totali:
        """Somma dei contratti stipulati: valore contrattuale e normalizzato sull'anno."""
        somma = Totali()
        for rn in self.stipulati:
            for livello in LIVELLI:
                somma.contrattuale[livello] += rn.importi.get(livello, ZERO)
                somma.normalizzato[livello] += rn.normalizzato.get(livello, ZERO)
        return somma


@dataclass
class GruppoCluster:
    cluster: m.Cluster
    sottocluster: list[GruppoSottocluster] = field(default_factory=list)
    totali: Totali = field(default_factory=Totali)


@dataclass
class Sezione:
    natura: str
    cluster: list[GruppoCluster] = field(default_factory=list)
    totali: Totali = field(default_factory=Totali)
    numero_righe: int = 0


def _sezione(natura: str, righe: list[RigaPiano]) -> Sezione:
    """Raggruppa per cluster e sottocluster (senza sottocluster in coda), righe per data."""
    sezione = Sezione(natura)
    cluster: dict[int, GruppoCluster] = {}
    gruppi: dict[tuple[int, int | None], GruppoSottocluster] = {}
    for r in righe:  # già in ordine di data
        if natura not in r.per_natura:
            continue
        rn = RigaNatura(
            r,
            natura,
            r.per_natura[natura],
            r.normalizzato_per_natura.get(natura, dict.fromkeys(LIVELLI, ZERO)),
            r.fonti.get(natura, FONTE_ORDINARIA),
        )
        f = r.fabbisogno
        gc = cluster.setdefault(f.cluster_id, GruppoCluster(f.cluster))
        chiave = (f.cluster_id, f.sottocluster_id)
        if chiave not in gruppi:
            gruppi[chiave] = GruppoSottocluster(f.sottocluster)
            gc.sottocluster.append(gruppi[chiave])
        gruppi[chiave].righe.append(rn)
        for totali in (gruppi[chiave].totali, gc.totali, sezione.totali):
            totali.aggiungi(rn)
        sezione.numero_righe += 1
    sezione.cluster = sorted(cluster.values(), key=lambda g: g.cluster.codice)
    for gc in sezione.cluster:
        gc.sottocluster.sort(key=lambda g: (g.sottocluster is None, g.nome))
        for gs in gc.sottocluster:
            sotto = gs.sottocluster.pk if gs.sottocluster else 0
            gs.id_stipulati = f"stip-{natura.lower()}-{gc.cluster.pk}-{sotto}"
    return sezione


def soglie_valide(alla_data: datetime.date) -> list[m.Soglia]:
    """Per ogni codice, la soglia valida alla data (l'ultima con inizio ≤ data)."""
    qs = (
        m.Soglia.objects.filter(valida_dal__lte=alla_data)
        .filter(Q(valida_al__isnull=True) | Q(valida_al__gte=alla_data))
        .order_by("codice", "-valida_dal")
    )
    per_codice: dict[str, m.Soglia] = {}
    for s in qs:
        per_codice.setdefault(s.codice, s)
    return list(per_codice.values())


PRATICA_CONCLUSA = {m.StatoPratica.Stato.CONTRATTO_EMESSO, m.StatoPratica.Stato.CONTRATTO_ATTIVO}


def _lead_time_massimo() -> int:
    """Il lead time più lungo in uso: fin dove servono i previsti per coprire l'anno X."""
    procedure = m.Procedura.objects.aggregate(n=Max("lead_time_mesi"))["n"] or 0
    contratti = m.Contratto.objects.aggregate(n=Max("lead_time_mesi_override"))["n"] or 0
    return max(procedure, contratti)


def _ultimo_stato(oggetto, oggi: datetime.date) -> str | None:
    """Stato della pratica: ultimo passaggio o stato ricavato dalle RDA (SPEC §5.7)."""
    return acquisti.stato_pratica(oggetto, oggi)


def _competenza(voce: Voce, anno: int) -> Importi:
    """Valore normalizzato sull'anno: vista «competenza» del budget (SPEC §5.2, TC-11)."""
    importi, _ = importi_anno(voce, anno)
    return importi["competenza"]


def _fonte(f: m.Fabbisogno, wbs: list[m.WBS | None]) -> str:
    """Fonte del fabbisogno; altrimenti quella della WBS delle voci; altrimenti «Ordinaria»."""
    if f.fonte_finanziamento_id:
        return f.fonte_finanziamento.nome
    nomi = {w.fonte_finanziamento.nome for w in wbs if w and w.fonte_finanziamento_id}
    return " / ".join(sorted(nomi)) or FONTE_ORDINARIA


class _Somme:
    """Valore contrattuale, normalizzato e WBS delle voci di una riga, per natura."""

    def __init__(self):
        self.importi: dict[str, Importi] = {}
        self.normalizzato: dict[str, Importi] = {}
        self.wbs: dict[str, list[m.WBS | None]] = {}
        self.a_progetto = False

    def aggiungi(self, voce: Voce, classe: adapters.Classificazione, anno: int) -> None:
        self.a_progetto = self.a_progetto or classe.a_progetto
        importi = self.importi.setdefault(classe.natura, dict.fromkeys(LIVELLI, ZERO))
        norm = self.normalizzato.setdefault(classe.natura, dict.fromkeys(LIVELLI, ZERO))
        self.wbs.setdefault(classe.natura, []).append(classe.wbs)
        competenza = _competenza(voce, anno)
        for liv in LIVELLI:
            importi[liv] += valore(voce, liv)
            norm[liv] += competenza[liv]

    def senza_competenza(self) -> None:
        """Toglie le nature senza competenza nell'anno (contratti registrati)."""
        for n in [n for n, norm in self.normalizzato.items() if not any(norm.values())]:
            for d in (self.importi, self.normalizzato, self.wbs):
                del d[n]

    def totale(self, per_natura: dict[str, Importi]) -> Importi:
        return {liv: sum((i[liv] for i in per_natura.values()), ZERO) for liv in LIVELLI}


def _riga(
    f: m.Fabbisogno,
    base: m.Contratto | None,
    p: ContrattoPrevisto,
    durata_mesi: int,
    procedura_default: m.Procedura | None,
    oggi: datetime.date,
    anno: int,
) -> RigaPiano:
    somme = _Somme()
    modelli = {v.pk: v for v in base.voci.all()} if base is not None else {}
    for v in p.voci:
        classe = adapters.classificazione_prevista(f, modelli.get(v.riferimento))
        somme.aggiungi(v, classe, anno)
    importi = somme.totale(somme.importi)
    per_natura, a_progetto = somme.importi, somme.a_progetto
    if base is not None:
        procedura = base.procedura
        lead = adapters.scadenza(base).lead_time_mesi
        # Come la data limite del contratto: fine del periodo precedente − lead time.
        limite = aggiungi_mesi(p.inizio - UN_GIORNO, -lead)
        stato = _ultimo_stato(base, oggi) if p.numero == 1 else None
    else:
        procedura = f.previsto_procedura or procedura_default
        lead = procedura.lead_time_mesi if procedura else 0
        if p.numero == 1:
            # Come nel cruscotto dei fabbisogni nuovi: avvio previsto − lead time.
            limite = aggiungi_mesi(p.inizio, -lead)
            stato = _ultimo_stato(f, oggi)
        else:
            limite = aggiungi_mesi(p.inizio - UN_GIORNO, -lead)
            stato = None
    return RigaPiano(
        fabbisogno=f,
        contratto_uscente=base,
        procedura=procedura,
        lead_time_mesi=lead,
        data_limite=limite,
        avvio=p.inizio,
        fine=p.fine,
        durata_mesi=durata_mesi,
        stato_pratica=stato,
        importi=importi,
        numero_previsto=p.numero,
        natura=next(iter(per_natura)) if len(per_natura) == 1 else m.Contratto.MISTA,
        per_natura=per_natura,
        a_progetto=a_progetto,
        normalizzato=somme.totale(somme.normalizzato),
        normalizzato_per_natura=somme.normalizzato,
        fonti={n: _fonte(f, somme.wbs[n]) for n in per_natura},
    )


def _riga_registrata(
    f: m.Fabbisogno, c: m.Contratto, anno: int, oggi: datetime.date
) -> RigaPiano | None:
    """Contratto già registrato che pesa nell'anno (competenza diversa da zero), o None."""
    voci, _ = adapters.voci_contratto(c)
    modelli = {v.pk: v for v in c.voci.all()}
    somme = _Somme()
    for ve in voci:
        classe = adapters.classificazione(modelli[ve.riferimento])
        if classe.extra_budget is not None:  # Rev19: extra budget fuori dal piano ordini
            continue
        somme.aggiungi(ve, classe, anno)
    somme.senza_competenza()
    if not somme.importi:
        return None
    stipulato = (c.data_stipula is not None and c.data_stipula <= oggi) or c.data_inizio <= oggi
    return RigaPiano(
        fabbisogno=f,
        contratto_uscente=None,
        procedura=c.procedura,
        lead_time_mesi=adapters.scadenza(c).lead_time_mesi,
        data_limite=None,
        avvio=c.data_inizio,
        fine=adapters.data_fine_effettiva(c),
        durata_mesi=c.durata_mesi,
        stato_pratica=None,
        importi=somme.totale(somme.importi),
        numero_previsto=0,
        natura=next(iter(somme.importi)) if len(somme.importi) == 1 else m.Contratto.MISTA,
        per_natura=somme.importi,
        a_progetto=somme.a_progetto,
        fase=REGISTRATO,
        contratto=c,
        stato=STIPULATO if stipulato else IN_STIPULA,
        normalizzato=somme.totale(somme.normalizzato),
        normalizzato_per_natura=somme.normalizzato,
        fonti={n: _fonte(f, somme.wbs[n]) for n in somme.importi},
    )


def calcola_piano(
    anno: int,
    oggi: datetime.date,
    *,
    area: str | tuple[str, ...] = "",
    sottocluster: int | None = None,
    natura: str = "",
) -> PianoOrdini:
    with adapters.parametri_in_cache():
        return _calcola_piano(anno, oggi, area, sottocluster, natura)


def _calcola_piano(anno: int, oggi: datetime.date, area, sottocluster: int | None, natura: str):
    inizio_anno = datetime.date(anno, 1, 1)
    # Un previsto con data limite nell'anno X può partire fino a lead time mesi dopo il 31/12/X.
    orizzonte = max(
        orizzonte_report(anno, oggi),
        aggiungi_mesi(datetime.date(anno, 12, 31), _lead_time_massimo()) + UN_GIORNO,
    )
    recupero = anno == oggi.year  # i ritardi solo nel piano dell'anno in corso
    procedura_default = m.Procedura.objects.filter(codice="da_verificare").first()
    fabbisogni = (
        m.Fabbisogno.objects.filter(archiviato=False)
        .select_related(
            "cluster",
            "previsto_procedura",
            "sottocluster__cluster",
            "fonte_finanziamento",
            "wbs_previsti__fonte_finanziamento",
        )
        .prefetch_related(*adapters.PREFETCH_FABBISOGNO)
    )
    if codici := codici_cluster(area):
        fabbisogni = fabbisogni.filter(cluster__codice__in=codici)
    if sottocluster:
        fabbisogni = fabbisogni.filter(sottocluster_id=sottocluster)
    righe: list[RigaPiano] = []
    for f in fabbisogni.order_by("pk"):
        righe += _righe_previste(f, anno, oggi, orizzonte, procedura_default, recupero)
        righe += _righe_registrate(f, anno, oggi)
    if natura:
        righe = [r for r in righe if natura in r.per_natura]
    righe.sort(key=lambda r: (r.data_ordinamento, r.fabbisogno.descrizione))
    soglie = soglie_valide(inizio_anno)
    da_avviare = [r for r in righe if r.da_avviare]
    return PianoOrdini(anno, righe, soglie, avvisi_frazionamento(da_avviare, soglie))


def _righe_previste(f, anno, oggi, orizzonte, procedura_default, recupero) -> list[RigaPiano]:
    inizio_anno = datetime.date(anno, 1, 1)
    previsti = adapters.previsti_fabbisogno(f, orizzonte)
    if not previsti:
        return []
    base = adapters.contratto_base_previsti(f)
    if base is not None and base.senza_contratto:
        return []  # rinnovi senza contratto: nessun ordine al Procurement (SPEC §5.4, §5.6)
    durata = base.durata_mesi if base is not None else f.previsto_durata_mesi
    righe = []
    for p in previsti:
        r = _riga(f, base, p, durata, procedura_default, oggi, anno)
        if r.data_limite.year > anno:
            continue
        if r.data_limite.year < anno:
            # Procedura da avviare prima: resta da emettere l'ordine, entro l'avvio.
            in_corso = r.avvio >= inizio_anno or (recupero and r.fine >= inizio_anno)
            if not in_corso or r.stato_pratica in PRATICA_CONCLUSA:
                continue
            r.fase = DA_CONCLUDERE
        if recupero:
            non_avviata = r.stato_pratica in (None, m.StatoPratica.Stato.NON_AVVIATA)
            partito = r.avvio <= oggi and r.stato_pratica not in PRATICA_CONCLUSA
            r.in_ritardo = (r.data_limite < oggi and non_avviata) or partito
        righe.append(r)
    return righe


def _righe_registrate(f, anno, oggi) -> list[RigaPiano]:
    """Contratti già registrati con competenza nell'anno; fuori i «senza contratto» (§5.6)."""
    righe = []
    for c in f.contratti.all():
        if c.archiviato or c.senza_contratto or c.data_inizio is None:
            continue
        if (r := _riga_registrata(f, c, anno, oggi)) is not None:
            righe.append(r)
    return righe


def avvisi_frazionamento(righe: list[RigaPiano], soglie: list[m.Soglia]):
    """Gruppi (sottocluster o fornitore) di almeno 2 previsti che sommati raggiungono la soglia.

    Il confronto usa il livello massimo: il valore stimato dell'appalto comprende le
    opzioni. I singoli previsti già oltre soglia sono marcati sulla riga.
    """
    gruppi: dict[tuple[str, str], list[RigaPiano]] = defaultdict(list)
    for r in righe:
        if (sc := r.sottocluster) is not None:
            gruppi[("sottocluster", str(sc))].append(r)
        f = r.fornitore_uscente
        if f is not None and not f.ragione_sociale.startswith("("):
            gruppi[("fornitore", f.ragione_sociale)].append(r)
    avvisi = []
    for s in soglie:
        for r in righe:
            if r.importi[Livello.MASSIMO] >= s.importo:
                r.sopra_soglia.append(s.descrizione)
        for (tipo, nome), membri in sorted(gruppi.items()):
            totale = sum((r.importi[Livello.MASSIMO] for r in membri), ZERO)
            if len(membri) >= 2 and totale >= s.importo:
                avvisi.append(AvvisoFrazionamento(tipo, nome, s, totale, membri))
    return avvisi
