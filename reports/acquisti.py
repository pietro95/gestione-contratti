"""Viste del processo d'acquisto (F11.4, SPEC §5.7, §5.8): stato delle RDA, RDA da processare,
fatture da lavorare, contratti da chiudere, anomalie dell'esecuzione.

I valori vengono dal motore (``contratti.engine.acquisti``) attraverso gli adapter: qui si
filtra, si raggruppa e si somma, senza regole nuove.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Prefetch, Q

from contratti import acquisti, adapters, fatture
from contratti import models as m
from contratti.engine import acquisti as motore
from contratti.engine.importi import ZERO

Fase = motore.Fase
Azione = motore.Azione
Passo = motore.PassoFattura

ETICHETTE_AZIONE = {
    Azione.DA_INSERIRE: "Da inserire in SAP",
    Azione.SOLLECITO_RILASCIO: "Da sollecitare per il rilascio",
    Azione.SOLLECITO_PROCUREMENT: "Da sollecitare al Procurement",
}


# --- RDA -------------------------------------------------------------------------------------


@dataclass
class RigaRDA:
    rda: m.RichiestaAcquisto
    fase: Fase
    data_fase: datetime.date | None
    giorni: int | None
    importo: Decimal
    fabbisogno: m.Fabbisogno | None
    fornitore: m.Fornitore | None
    contratti: list[m.Contratto]
    ferma: bool

    @property
    def fase_label(self) -> str:
        return motore.ETICHETTE_FASE[self.fase]

    @property
    def anno(self) -> int:
        return anno_rda(self.rda)


def anno_rda(rda: m.RichiestaAcquisto) -> int:
    """Anno della RDA: dell'inserimento in SAP, o della creazione se non è ancora inserita."""
    return (rda.data_inserimento or rda.data_creazione).year


def qs_rda():
    return acquisti.QS_RDA.select_related(
        "cluster",
        "fabbisogno",
        "contratto_in_scadenza__fabbisogno",
        "contratto_in_scadenza__fornitore",
        "referente_utente",
        "fornitore_proposto",
    ).prefetch_related(
        Prefetch(
            "posizioni",
            queryset=m.PosizioneRDA.objects.select_related("wbs").order_by("numero"),
        )
    )


def riga_rda(rda: m.RichiestaAcquisto, oggi: datetime.date, giorni_ferma: int) -> RigaRDA:
    dati = acquisti.dati_rda(rda)
    fase = motore.fase(dati, oggi)
    data = motore.data_fase(dati, oggi)
    contratti = [c for c in rda.contratti_generati.all() if not c.archiviato]
    fornitore = rda.fornitore_proposto or (contratti[0].fornitore if contratti else None)
    return RigaRDA(
        rda=rda,
        fase=fase,
        data_fase=data,
        giorni=(oggi - data).days if data else None,
        importo=sum((p.importo for p in rda.posizioni.all()), ZERO),
        fabbisogno=rda.fabbisogno_della_pratica(),
        fornitore=fornitore,
        contratti=contratti,
        ferma=motore.rda_ferma(dati, oggi, giorni_ferma),
    )


@dataclass(frozen=True)
class FiltriRDA:
    cluster: tuple[str, ...] = ()  # vuoto = tutti
    sottocluster: int | None = None
    referente: int | None = None
    fasi: tuple[str, ...] = ()
    anno: int | None = None
    fornitore: int | None = None
    wbs: str = ""
    testo: str = ""


def stato_rda(filtri: FiltriRDA, oggi: datetime.date) -> list[RigaRDA]:
    """Tutte le RDA non archiviate con i filtri della vista «Stato delle RDA» (SPEC §5.7)."""
    qs = qs_rda()
    if filtri.cluster:
        qs = qs.filter(cluster__codice__in=filtri.cluster)
    qs = acquisti.filtra_rda_per_sottocluster(qs, filtri.sottocluster)
    if filtri.referente:
        qs = qs.filter(referente_utente_id=filtri.referente)
    if filtri.wbs:
        qs = qs.filter(Q(posizioni__wbs__codice_wbs__icontains=filtri.wbs)).distinct()
    if filtri.testo:
        t = filtri.testo
        qs = qs.filter(
            Q(numero_rda__icontains=t)
            | Q(descrizione__icontains=t)
            | Q(intestazione__icontains=t)
            | Q(referente__icontains=t)
        )
    giorni = acquisti.giorni_rda_ferma(oggi)
    righe = [riga_rda(r, oggi, giorni) for r in qs.order_by("-data_creazione", "-pk")]
    if filtri.fasi:
        righe = [r for r in righe if r.fase in filtri.fasi]
    if filtri.anno:
        righe = [r for r in righe if r.anno == filtri.anno]
    if filtri.fornitore:
        righe = [r for r in righe if r.fornitore and r.fornitore.pk == filtri.fornitore]
    return righe


def conteggi_per_fase(righe: list[RigaRDA]) -> list[tuple[str, str, int, Decimal]]:
    """(fase, etichetta, numero, importo) per ogni fase con almeno una RDA, nell'ordine."""
    per_fase = defaultdict(lambda: [0, ZERO])
    for r in righe:
        per_fase[r.fase][0] += 1
        per_fase[r.fase][1] += r.importo
    return [
        (f, etichetta, *per_fase[f])
        for f, etichetta in motore.ETICHETTE_FASE.items()
        if f in per_fase
    ]


def rda_da_processare(
    cluster: tuple[str, ...], oggi: datetime.date, sottocluster: int | None = None
) -> list[tuple[Azione, str, list[RigaRDA]]]:
    """RDA nelle fasi dell'addetto, per azione; in ogni gruppo le ferme e le più vecchie prima."""
    filtri = FiltriRDA(
        cluster=cluster, sottocluster=sottocluster, fasi=tuple(motore.AZIONE_ADDETTO)
    )
    righe = stato_rda(filtri, oggi)
    gruppi = defaultdict(list)
    for r in righe:
        gruppi[motore.azione_addetto(r.fase)].append(r)
    return [
        (
            azione,
            ETICHETTE_AZIONE[azione],
            sorted(gruppi[azione], key=lambda r: (not r.ferma, -(r.giorni or 0))),
        )
        for azione in Azione
    ]


def mie_rda(utente, oggi: datetime.date) -> list[RigaRDA]:
    """Le RDA di cui l'utente è referente, non chiuse né annullate; prima quelle che
    aspettano lui (bozza, da correggere)."""
    righe = stato_rda(FiltriRDA(referente=utente.pk), oggi)
    righe = [r for r in righe if r.fase not in (Fase.CHIUSA, Fase.ANNULLATA)]
    return sorted(righe, key=lambda r: (not motore.attende_referente(r.fase), r.rda.pk))


# --- Fatture -------------------------------------------------------------------------------


@dataclass
class RigaFattura:
    fattura: m.Fattura
    passo: Passo | None
    giorni: int
    ferma: bool
    contratto_proposto: m.Contratto | None = None
    referente_proposto: object = None

    @property
    def passo_label(self) -> str:
        return motore.ETICHETTE_PASSO[self.passo] if self.passo else "Trasferita"


def _righe_fatture(qs, oggi: datetime.date, *, proposte=False) -> list[RigaFattura]:
    lista = list(qs.order_by("data_registrazione", "pk"))
    giorni = acquisti.giorni_fattura_ferma(oggi)
    contratti = fatture.contratti_proposti(lista) if proposte else {}
    referenti = fatture.referenti_proposti(lista) if proposte else {}
    righe = []
    for f in lista:
        lav = fatture.lavorazione(f)
        documenti = fatture.documenti_fattura(f)
        righe.append(
            RigaFattura(
                fattura=f,
                passo=motore.passo_fattura(documenti, oggi, f.data_trasferimento, lav),
                giorni=(oggi - f.data_registrazione).days,
                ferma=motore.fattura_ferma(
                    f.data_registrazione, documenti, oggi, giorni, f.data_trasferimento, lav
                ),
                contratto_proposto=contratti.get(f.pk),
                referente_proposto=referenti.get(f.pk),
            )
        )
    return righe


def fatture_da_lavorare(oggi: datetime.date) -> dict[Passo, list[RigaFattura]]:
    """Fatture non trasferite e non fuori registro, per passo da fare (SPEC §5.7)."""
    qs = fatture.QS_FATTURE.filter(
        archiviato=False, fuori_registro=False, data_trasferimento__isnull=True
    )
    gruppi: dict[Passo, list[RigaFattura]] = {p: [] for p in Passo}
    for r in _righe_fatture(qs, oggi, proposte=True):
        if r.passo is not None:
            gruppi[r.passo].append(r)
    for righe in gruppi.values():
        righe.sort(key=lambda r: (not r.ferma, -r.giorni))
    return gruppi


def fatture_proposte_a(utente, oggi: datetime.date) -> list[RigaFattura]:
    qs = fatture.QS_FATTURE.filter(archiviato=False, fuori_registro=False, referente__isnull=True)
    return [r for r in _righe_fatture(qs, oggi, proposte=True) if r.referente_proposto == utente]


def mie_fatture(utente, oggi: datetime.date) -> list[RigaFattura]:
    qs = fatture.QS_FATTURE.filter(
        archiviato=False,
        fuori_registro=False,
        referente=utente,
        data_trasferimento__isnull=True,
    )
    righe = [r for r in _righe_fatture(qs, oggi) if r.passo is not None]
    aspettano = {Passo.ASSEGNAZIONE, Passo.CONVALIDA}
    return sorted(righe, key=lambda r: (r.passo not in aspettano, -r.giorni))


VISTE_FATTURE = {
    "da_prendere": "Da prendere in carico",
    "mie": "Le mie fatture",
    "tutte": "Tutte le fatture",
}


def riga_fattura(f: m.Fattura, oggi, contratto_proposto=None, referente_proposto=None) -> dict:
    passo = fatture.passo_fattura(f, oggi)
    return {
        "f": f,
        "passo": passo,
        "passo_label": motore.ETICHETTE_PASSO[passo] if passo else "Trasferita",
        "giorni": (oggi - f.data_registrazione).days,
        "ferma": not f.fuori_registro and fatture.ferma(f, oggi),
        "contratto_proposto": contratto_proposto,
        "referente_proposto": referente_proposto,
        "anomalie": fatture.anomalie(f),
    }


@dataclass
class ElencoFatture:
    vista: str
    righe: list[dict]
    proposte_a_me: int
    solo_proposte: bool


def elenco_fatture(
    utente,
    oggi: datetime.date,
    vista: str = "da_prendere",
    *,
    testo: str = "",
    passo: str = "",
    proposte: bool | None = None,
    fuori_registro: bool = False,
    archiviate: bool = False,
) -> ElencoFatture:
    """Le tre viste delle fatture (SPEC §5.7, Rev15). ``proposte`` None: «proposte a me»
    attivo di default per chi ha almeno una proposta."""
    vista = vista if vista in VISTE_FATTURE else "da_prendere"
    qs = fatture.QS_FATTURE.all()
    if vista == "da_prendere":
        qs = qs.filter(referente__isnull=True, fuori_registro=False, archiviato=False)
    elif vista == "mie":
        qs = qs.filter(
            referente=utente, fuori_registro=False, archiviato=False,
            data_trasferimento__isnull=True,
        )  # fmt: skip
    else:
        if not archiviate:
            qs = qs.filter(archiviato=False)
        if not fuori_registro:
            qs = qs.filter(fuori_registro=False)
    if testo := testo.strip():
        qs = qs.filter(
            Q(numero__icontains=testo)
            | Q(fornitore__ragione_sociale__icontains=testo)
            | Q(fornitore__nome_breve__icontains=testo)
            | Q(contratto__numero_contratto__icontains=testo)
            | Q(documenti__numero__icontains=testo)
        ).distinct()
    lista = list(qs.order_by("data", "pk"))
    contratti = fatture.contratti_proposti(lista) if vista != "mie" else {}
    referenti = fatture.referenti_proposti(lista) if vista != "mie" else {}
    proposte_a_me = sum(1 for u in referenti.values() if u == utente)
    solo = vista == "da_prendere" and (proposte is True or (proposte is None and proposte_a_me > 0))
    righe = [riga_fattura(f, oggi, contratti.get(f.pk), referenti.get(f.pk)) for f in lista]
    if solo:
        righe = [r for r in righe if r["referente_proposto"] == utente]
    if passo:
        righe = [r for r in righe if (r["passo"] or "trasferita") == passo]
    return ElencoFatture(vista, righe, proposte_a_me, solo)


# --- Contratti da chiudere e anomalie dell'esecuzione (SPEC §5.8) ------------------------


@dataclass
class RigaEsecuzione:
    contratto: m.Contratto
    fine: datetime.date | None
    riepilogo: acquisti.RiepilogoEsecuzione
    anomalie_fatture: list[tuple[m.Fattura, list[str]]] = field(default_factory=list)

    @property
    def motivo_label(self) -> str:
        motivo = self.riepilogo.motivo_da_chiudere
        return motore.ETICHETTE_MOTIVO[motivo] if motivo else ""


def _contratti(cluster: tuple[str, ...], sottocluster: int | None = None):
    qs = (
        m.Contratto.objects.filter(archiviato=False)
        .select_related("fornitore", "fabbisogno__cluster", "procedura")
        .prefetch_related(
            "voci", "proroghe", "fatture", "documenti_esecuzione", "fatturato_pregresso"
        )
    )
    if cluster:
        qs = qs.filter(fabbisogno__cluster__codice__in=cluster)
    if sottocluster:
        qs = qs.filter(fabbisogno__sottocluster_id=sottocluster)
    return qs.order_by("fabbisogno__descrizione", "pk")


def contratti_da_chiudere(
    cluster: tuple[str, ...], oggi: datetime.date, sottocluster: int | None = None
) -> list[RigaEsecuzione]:
    """Non chiusi, con la prestazione finita (fine effettiva < oggi), con il motivo."""
    righe = []
    for c in _contratti(cluster, sottocluster).filter(data_chiusura__isnull=True):
        fine = adapters.data_fine_effettiva(c)
        if fine is None or fine >= oggi:
            continue
        riepilogo = acquisti.riepilogo_esecuzione(c, oggi)
        if riepilogo.motivo_da_chiudere is not None:
            righe.append(RigaEsecuzione(c, fine, riepilogo))
    ordine = list(motore.MotivoChiusura)
    return sorted(righe, key=lambda r: (ordine.index(r.riepilogo.motivo_da_chiudere), r.fine))


def anomalie_esecuzione(
    cluster: tuple[str, ...], oggi: datetime.date, sottocluster: int | None = None
) -> list[RigaEsecuzione]:
    """Contratti con anomalie dell'esecuzione o fatture con anomalie (SPEC §5.8)."""
    righe = []
    candidati = (
        _contratti(cluster, sottocluster)
        .filter(
            Q(fatture__isnull=False)
            | Q(fatturato_pregresso__isnull=False)
            | Q(data_chiusura__isnull=False)
        )
        .distinct()
    )
    for c in candidati:
        riepilogo = acquisti.riepilogo_esecuzione(c, oggi)
        di_fatture = [
            (f, codici)
            for f in c.fatture.all()
            if not f.archiviato and (codici := fatture.anomalie(f))
        ]
        if riepilogo.anomalie or di_fatture:
            righe.append(RigaEsecuzione(c, adapters.data_fine_effettiva(c), riepilogo, di_fatture))
    return righe


# Segnalata sulla fattura (quale manca): nel conteggio non si ripete per il contratto.
PER_FATTURA = frozenset({"VALORE_BASE_MANCANTE"})


def conteggi_anomalie(righe: list[RigaEsecuzione]) -> dict[str, int]:
    """Codice → contratti con l'anomalia; per le anomalie delle fatture, fatture."""
    conteggi: dict[str, int] = defaultdict(int)
    for r in righe:
        for codice in r.riepilogo.anomalie:
            if codice not in PER_FATTURA:
                conteggi[codice] += 1
        for _f, codici in r.anomalie_fatture:
            for codice in codici:
                conteggi[codice] += 1
    return dict(sorted(conteggi.items()))
