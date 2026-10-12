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
Il Procurement ordina sia OPEX sia CAPEX: il piano li contiene entrambi, con i totali per natura.
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
from contratti.engine.tipi import ContrattoPrevisto, Livello
from contratti.selettori import codici_cluster
from reports.budget import LIVELLI, NATURE, orizzonte_report

CATEGORIA_NON_CLASSIFICATA = "Da classificare"
DA_AVVIARE = "da_avviare"
DA_CONCLUDERE = "da_concludere"


@dataclass
class RigaPiano:
    fabbisogno: m.Fabbisogno
    contratto_uscente: m.Contratto | None
    procedura: m.Procedura | None
    lead_time_mesi: int
    data_limite: datetime.date
    avvio: datetime.date
    fine: datetime.date
    durata_mesi: int
    stato_pratica: str | None
    importi: dict[Livello, Decimal]
    numero_previsto: int
    natura: str = m.Natura.OPEX  # OPEX, CAPEX o "OPEX e CAPEX"
    # Importi per natura delle voci (F9.2: un contratto può avere quote OPEX e CAPEX).
    per_natura: dict[str, dict[Livello, Decimal]] = field(default_factory=dict)
    a_progetto: bool = False
    sopra_soglia: list[str] = field(default_factory=list)
    in_ritardo: bool = False
    fase: str = "da_avviare"  # o "da_concludere" (SPEC §5.4 Rev17)

    @property
    def da_avviare(self) -> bool:
        return self.fase == DA_AVVIARE

    @property
    def categoria(self) -> m.Categoria:
        return self.fabbisogno.categoria

    @property
    def fornitore_uscente(self) -> m.Fornitore | None:
        return self.contratto_uscente.fornitore if self.contratto_uscente else None

    @property
    def stato_pratica_label(self) -> str:
        if not self.stato_pratica:
            return "Non avviata"
        return m.StatoPratica.Stato(self.stato_pratica).label


@dataclass
class AvvisoFrazionamento:
    tipo: str  # "categoria" o "fornitore"
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
        return [r for r in self.righe if not r.da_avviare]

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


def _riga(
    f: m.Fabbisogno,
    base: m.Contratto | None,
    p: ContrattoPrevisto,
    durata_mesi: int,
    procedura_default: m.Procedura | None,
    oggi: datetime.date,
) -> RigaPiano:
    importi = {liv: sum((valore(v, liv) for v in p.voci), ZERO) for liv in LIVELLI}
    per_natura: dict[str, dict[Livello, Decimal]] = {}
    a_progetto = False
    modelli = {v.pk: v for v in base.voci.all()} if base is not None else {}
    for v in p.voci:
        classe = adapters.classificazione_prevista(f, modelli.get(v.riferimento))
        a_progetto = a_progetto or classe.a_progetto
        somme = per_natura.setdefault(classe.natura, dict.fromkeys(LIVELLI, ZERO))
        for liv in LIVELLI:
            somme[liv] += valore(v, liv)
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
    )


def calcola_piano(
    anno: int,
    oggi: datetime.date,
    *,
    area: str | tuple[str, ...] = "",
    categoria: int | None = None,
    natura: str = "",
) -> PianoOrdini:
    with adapters.parametri_in_cache():
        return _calcola_piano(anno, oggi, area, categoria, natura)


def _calcola_piano(anno: int, oggi: datetime.date, area, categoria: int | None, natura: str):
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
        .select_related("cluster", "categoria", "previsto_procedura")
        .prefetch_related(*adapters.PREFETCH_FABBISOGNO)
    )
    if codici := codici_cluster(area):
        fabbisogni = fabbisogni.filter(cluster__codice__in=codici)
    if categoria:
        fabbisogni = fabbisogni.filter(categoria_id=categoria)
    righe: list[RigaPiano] = []
    for f in fabbisogni.order_by("pk"):
        previsti = adapters.previsti_fabbisogno(f, orizzonte)
        if not previsti:
            continue
        base = adapters.contratto_base_previsti(f)
        if base is not None and base.senza_contratto:
            continue  # rinnovi senza contratto: nessun ordine al Procurement (SPEC §5.4, §5.6)
        durata = base.durata_mesi if base is not None else f.previsto_durata_mesi
        for p in previsti:
            r = _riga(f, base, p, durata, procedura_default, oggi)
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
    if natura:
        righe = [r for r in righe if natura in r.per_natura]
    righe.sort(key=lambda r: (r.data_limite, r.fabbisogno.descrizione))
    soglie = soglie_valide(inizio_anno)
    da_avviare = [r for r in righe if r.da_avviare]
    return PianoOrdini(anno, righe, soglie, avvisi_frazionamento(da_avviare, soglie))


def avvisi_frazionamento(righe: list[RigaPiano], soglie: list[m.Soglia]):
    """Gruppi (categoria o fornitore) di almeno 2 previsti che sommati raggiungono la soglia.

    Il confronto usa il livello massimo: il valore stimato dell'appalto comprende le
    opzioni. I singoli previsti già oltre soglia sono marcati sulla riga.
    """
    gruppi: dict[tuple[str, str], list[RigaPiano]] = defaultdict(list)
    for r in righe:
        if r.categoria.nome != CATEGORIA_NON_CLASSIFICATA:
            gruppi[("categoria", r.categoria.nome)].append(r)
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
