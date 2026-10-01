"""Piano ordini dell'anno X per il Procurement (SPEC §5.4).

Una riga per ogni contratto previsto (automatico o manuale) con avvio del servizio
nell'anno X: è lo stesso criterio dell'impegno dei previsti, quindi il totale del piano
coincide con l'impegno previsionale dell'anno.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q

from contratti import adapters
from contratti import models as m
from contratti.engine.budget import valore
from contratti.engine.date import UN_GIORNO, aggiungi_mesi
from contratti.engine.importi import ZERO
from contratti.engine.tipi import ContrattoPrevisto, Livello
from reports.budget import LIVELLI, orizzonte_report

CATEGORIA_NON_CLASSIFICATA = "Da classificare"


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
    sopra_soglia: list[str] = field(default_factory=list)

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

    def totali(self) -> dict[Livello, Decimal]:
        totali = dict.fromkeys(LIVELLI, ZERO)
        for r in self.righe:
            for livello in LIVELLI:
                totali[livello] += r.importi[livello]
        return totali


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


def _ultimo_stato(oggetto) -> str | None:
    ultimo = oggetto.stati_pratica.order_by("-data", "-id").first()
    return ultimo.stato if ultimo else None


def _riga(
    f: m.Fabbisogno,
    base: m.Contratto | None,
    p: ContrattoPrevisto,
    durata_mesi: int,
    procedura_default: m.Procedura | None,
) -> RigaPiano:
    importi = {liv: sum((valore(v, liv) for v in p.voci), ZERO) for liv in LIVELLI}
    if base is not None:
        procedura = base.procedura
        lead = adapters.scadenza(base).lead_time_mesi
        # Come la data limite del contratto: fine del periodo precedente − lead time.
        limite = aggiungi_mesi(p.inizio - UN_GIORNO, -lead)
        stato = _ultimo_stato(base) if p.numero == 1 else None
    else:
        procedura = f.previsto_procedura or procedura_default
        lead = procedura.lead_time_mesi if procedura else 0
        if p.numero == 1:
            # Come nel cruscotto dei fabbisogni nuovi: avvio previsto − lead time.
            limite = aggiungi_mesi(p.inizio, -lead)
            stato = _ultimo_stato(f)
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
    )


def calcola_piano(
    anno: int, oggi: datetime.date, *, area: str = "", categoria: int | None = None
) -> PianoOrdini:
    with adapters.parametri_in_cache():
        return _calcola_piano(anno, oggi, area, categoria)


def _calcola_piano(anno: int, oggi: datetime.date, area: str, categoria: int | None):
    orizzonte = orizzonte_report(anno, oggi)
    procedura_default = m.Procedura.objects.filter(codice="da_verificare").first()
    fabbisogni = (
        m.Fabbisogno.objects.filter(archiviato=False)
        .select_related("categoria", "previsto_procedura")
        .prefetch_related(*adapters.PREFETCH_FABBISOGNO)
    )
    if area:
        fabbisogni = fabbisogni.filter(area=area)
    if categoria:
        fabbisogni = fabbisogni.filter(categoria_id=categoria)
    righe: list[RigaPiano] = []
    for f in fabbisogni.order_by("pk"):
        previsti = [p for p in adapters.previsti_fabbisogno(f, orizzonte) if p.inizio.year == anno]
        if not previsti:
            continue
        base = adapters.contratto_base_previsti(f)
        durata = base.durata_mesi if base is not None else f.previsto_durata_mesi
        righe += [_riga(f, base, p, durata, procedura_default) for p in previsti]
    righe.sort(key=lambda r: (r.data_limite, r.fabbisogno.descrizione))
    soglie = soglie_valide(datetime.date(anno, 1, 1))
    return PianoOrdini(anno, righe, soglie, avvisi_frazionamento(righe, soglie))


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
