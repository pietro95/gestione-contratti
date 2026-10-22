"""Adapter: convertono i modelli Django negli input del motore puro (``contratti.engine``).

Qui si leggono il database e i parametri di configurazione; il motore non li vede mai.
"""

import contextlib
import contextvars
import datetime
from dataclasses import dataclass, replace
from decimal import Decimal

from django.db.models import Prefetch

from contratti import models as m
from contratti.engine import previsioni, scadenze
from contratti.engine.date import UN_GIORNO
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import (
    Alert,
    Consuntivo,
    ContrattoBase,
    ContrattoPrevisto,
    Esito,
    Modalita,
    Piano,
    Quota,
    Rata,
    Scadenza,
    TipoConsuntivo,
    Voce,
)

Chiave = m.Parametro.Chiave


# Relazioni lette dal calcolo: da passare a prefetch_related sui contratti.
PREFETCH_CALCOLO = (
    "proroghe",
    Prefetch(
        "voci",
        queryset=m.VoceContratto.objects.select_related(
            "piano_fatturazione",
            "conto",
            "wbs__fonte_finanziamento",
            "conto_rinnovi",
            "wbs_rinnovi__fonte_finanziamento",
            "autorizzazione_extra_budget",
        ),
    ),
    "voci__quote",
    "voci__piano_fatturazione__rate",
    "voci__stanziamenti",
    "fatture",
)


# Da passare a prefetch_related sui fabbisogni per calcolare i previsti senza query.
PREFETCH_FABBISOGNO = (
    Prefetch(
        "contratti",
        queryset=m.Contratto.objects.select_related(
            "procedura", "fornitore", "successore", "confluito_in"
        ).prefetch_related(*PREFETCH_CALCOLO),
    ),
)


class ParametroMancante(LookupError):
    pass


_cache_parametri: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "cache_parametri", default=None
)


@contextlib.contextmanager
def parametri_in_cache():
    """Durante un report i parametri non cambiano: una query per chiave."""
    token = _cache_parametri.set({})
    try:
        yield
    finally:
        _cache_parametri.reset(token)


def parametro(chiave: str, alla_data: datetime.date) -> Decimal:
    """Valore del parametro valido alla data (l'ultimo con ``valido_dal`` ≤ data)."""
    cache = _cache_parametri.get()
    if cache is None:
        return _parametro(chiave, alla_data)
    if chiave not in cache:
        cache[chiave] = list(
            m.Parametro.objects.filter(chiave=chiave)
            .order_by("-valido_dal")
            .values_list("valido_dal", "valore")
        )
    for valido_dal, valore in cache[chiave]:
        if valido_dal <= alla_data:
            return valore
    raise ParametroMancante(f"Parametro {chiave} non definito al {alla_data:%d/%m/%Y}.")


def _parametro(chiave: str, alla_data: datetime.date) -> Decimal:
    p = (
        m.Parametro.objects.filter(chiave=chiave, valido_dal__lte=alla_data)
        .order_by("-valido_dal")
        .first()
    )
    if p is None:
        raise ParametroMancante(f"Parametro {chiave} non definito al {alla_data:%d/%m/%Y}.")
    return p.valore


def adeguamento_alla_data(data: datetime.date) -> Decimal:
    return parametro(Chiave.ADEGUAMENTO_PCT, data)


def piano_engine(piano: m.PianoFatturazione, alla_data: datetime.date) -> Piano:
    """Piano con i default risolti: giorni di pagamento e fine mese."""
    giorni_pagamento = piano.giorni_pagamento
    if giorni_pagamento is None:
        giorni_pagamento = int(parametro(Chiave.GIORNI_PAGAMENTO, alla_data))
    fine_mese = piano.pagamento_fine_mese
    if fine_mese is None:
        fine_mese = parametro(Chiave.PAGAMENTO_FINE_MESE, alla_data) == 1
    return Piano(
        modalita=Modalita(piano.modalita),
        periodicita=piano.periodicita,
        data_prima_fattura=piano.data_prima_fattura,
        giorni_pagamento=giorni_pagamento,
        pagamento_fine_mese=fine_mese,
    )


def scadenza(contratto: m.Contratto) -> Scadenza | None:
    """Dati di scadenza; ``None`` se manca la data di inizio (escluso dai calcoli)."""
    if contratto.data_inizio is None:
        return None
    lead_time = contratto.lead_time_mesi_override
    if lead_time is None:
        lead_time = contratto.procedura.lead_time_mesi
    return Scadenza(
        inizio=contratto.data_inizio,
        durata_mesi=contratto.durata_mesi,
        lead_time_mesi=lead_time,
        fine_override=contratto.data_fine_override,
        nuove_date_fine=tuple(p.nuova_data_fine for p in contratto.proroghe.all()),
        tacito_rinnovo=contratto.tacito_rinnovo,
        preavviso_disdetta_giorni=contratto.preavviso_disdetta_giorni,
    )


def _rate_salvate(
    voce: m.VoceContratto,
    consuntivi: dict[int, Consuntivo] | None = None,
    periodi_generati=None,
) -> tuple[Rata, ...] | None:
    """Rate salvate. Il periodo di competenza (Rev22) è quello salvato alla generazione; per
    le rate salvate prima, senza periodo, si ricava rigenerando lo scadenzario (per numero)."""
    piano = getattr(voce, "piano_fatturazione", None)
    if piano is None:
        return None
    consuntivi = consuntivi or {}
    salvate = sorted(piano.rate.all(), key=lambda r: r.numero)
    generati = None
    rate = []
    for r in salvate:
        periodo = (r.periodo_dal, r.periodo_al)
        if r.periodo_dal is None and periodi_generati is not None:
            if generati is None:
                generati = periodi_generati()
            periodo = generati.get(r.numero, (None, None))
        rate.append(
            Rata(
                r.numero,
                r.data_fattura,
                r.data_pagamento_stimata,
                r.importo,
                periodo[0],
                periodo[1],
                consuntivi.get(r.pk),
            )
        )
    return tuple(rate) or None


def _consuntivo_fattura(f: m.Fattura, senza_voce: bool = False) -> Consuntivo | None:
    """Fattura registrata a budget: valore base e periodo di competenza (Rev21).

    Senza valore base non conta (come per il fatturato del contratto); senza competenza si
    usa la data della fattura, segnalato."""
    if f.valore_base is None or f.archiviato or f.fuori_registro:
        return None
    mancante = f.competenza_dal is None
    dal, al = (f.data, f.data) if mancante else (f.competenza_dal, f.competenza_al)
    return Consuntivo(
        TipoConsuntivo.FATTURA, f.valore_base, dal, al, senza_competenza=mancante,
        senza_voce=senza_voce,
    )  # fmt: skip


def _consuntivi_contratto(
    contratto: m.Contratto, voci: list[m.VoceContratto]
) -> tuple[dict[int, Consuntivo], dict[int, list[Consuntivo]]]:
    """Fatture e stanziamenti del contratto: per rata (prendono il posto della rata) e per
    voce (quelli non abbinati a una rata). Fattura prima dello stanziamento sulla stessa rata."""
    per_rata: dict[int, Consuntivo] = {}
    per_voce: dict[int, list[Consuntivo]] = {v.pk: [] for v in voci}
    principale = next((v for v in voci if not v.proroga_id), voci[0] if voci else None)
    fatture = list(contratto.fatture.all())
    con_fattura = {f.rata_id for f in fatture if f.rata_id and not f.archiviato}
    for f in fatture:
        c = _consuntivo_fattura(f)
        if c is None:
            continue
        if f.rata_id:
            per_rata[f.rata_id] = c
        elif f.voce_id in per_voce:
            per_voce[f.voce_id].append(c)
        elif principale is not None:
            per_voce[principale.pk].append(replace(c, senza_voce=len(voci) > 1))
    for v in voci:
        for s in v.stanziamenti.all():
            if s.archiviato or s.fattura_id or s.rata_id in con_fattura:
                continue
            c = Consuntivo(
                TipoConsuntivo.STANZIAMENTO, s.importo, s.competenza_dal, s.competenza_al
            )
            if s.rata_id and s.rata_id not in per_rata:
                per_rata[s.rata_id] = c
            else:
                per_voce[v.pk].append(c)
    return per_rata, per_voce


def periodi_proroghe(contratto: m.Contratto) -> dict[int, tuple[datetime.date, datetime.date]]:
    """Periodo di servizio di ogni proroga: dal giorno dopo la fine precedente."""
    s = scadenza(contratto)
    precedente = scadenze.data_fine_contrattuale(s)
    periodi = {}
    for p in sorted(contratto.proroghe.all(), key=lambda p: (p.nuova_data_fine, p.pk)):
        periodi[p.pk] = (precedente + UN_GIORNO, p.nuova_data_fine)
        precedente = p.nuova_data_fine
    return periodi


def voce_engine(
    voce: m.VoceContratto,
    inizio: datetime.date,
    fine: datetime.date,
    anno_impegno: int,
    *,
    con_rate_salvate: bool = True,
    consuntivi_rata: dict[int, Consuntivo] | None = None,
    consuntivi: tuple[Consuntivo, ...] = (),
) -> Voce:
    piano = getattr(voce, "piano_fatturazione", None)

    def periodi_generati():
        senza_rate = voce_engine(voce, inizio, fine, anno_impegno, con_rate_salvate=False)
        return {r.numero: (r.periodo_inizio, r.periodo_fine) for r in genera_rate(senza_rate)}

    return Voce(
        importo_fisso=voce.importo_fisso,
        inizio=inizio,
        fine=fine,
        anno_impegno=anno_impegno,
        piano=piano_engine(piano, inizio) if piano else None,
        massimale_variabile=voce.massimale_variabile,
        stima_consumo_pct=voce.stima_consumo_pct,
        stima_consumo_importo=voce.stima_consumo_importo,
        rate=_rate_salvate(voce, consuntivi_rata, periodi_generati) if con_rate_salvate else None,
        quote=tuple(
            Quota(q.dal, q.al, q.importo) for q in sorted(voce.quote.all(), key=lambda q: q.dal)
        ),
        consuntivi=consuntivi if con_rate_salvate else (),
        riferimento=voce.pk,
    )


def voci_contratto(
    contratto: m.Contratto, *, con_rate_salvate: bool = True
) -> tuple[list[Voce], list[Esito]]:
    """Voci con periodo di servizio e anno di impegno (SPEC §5.2, TC-10).

    Voce base: periodo del contratto, impegno nell'anno di emissione del contratto (o dell'inizio).
    Voce di proroga: dal giorno dopo la fine precedente alla nuova fine, impegno
    nell'anno dell'atto.
    """
    s = scadenza(contratto)
    if s is None:
        return [], [Esito("DATA_MANCANTE", f"{contratto}: data di inizio mancante, escluso.")]
    fine_base = scadenze.data_fine_contrattuale(s)
    anno_base = (contratto.data_emissione or contratto.data_inizio).year
    periodi = periodi_proroghe(contratto)
    atti = {p.pk: p.data_atto for p in contratto.proroghe.all()}
    risultato = []
    # .all() e filtri in Python: con PREFETCH_CALCOLO nessuna query per contratto.
    voci = sorted((v for v in contratto.voci.all() if not v.archiviato), key=lambda v: v.pk)
    per_rata, per_voce = _consuntivi_contratto(contratto, voci) if con_rate_salvate else ({}, {})
    for voce in voci:
        if voce.proroga_id:
            inizio, fine = periodi[voce.proroga_id]
            anno = atti[voce.proroga_id].year
        else:
            inizio, fine, anno = contratto.data_inizio, fine_base, anno_base
        risultato.append(
            voce_engine(
                voce,
                inizio,
                fine,
                anno,
                con_rate_salvate=con_rate_salvate,
                consuntivi_rata=per_rata,
                consuntivi=tuple(per_voce.get(voce.pk, ())),
            )
        )
    return risultato, []


def stato_pratica_corrente(contratto: m.Contratto, oggi: datetime.date | None = None) -> str | None:
    """Il più avanzato tra l'ultimo passaggio e lo stato ricavato dalle RDA (SPEC §5.7)."""
    from contratti import acquisti

    return acquisti.stato_pratica(contratto, oggi)


def confluito(contratto: m.Contratto) -> bool:
    """Confluito in un contratto nuovo non archiviato (F9.3): ha un successore."""
    return contratto.confluito_in_id is not None and not contratto.confluito_in.archiviato


def ha_successore(contratto: m.Contratto) -> bool:
    if confluito(contratto):
        return True
    return m.Contratto.objects.filter(predecessore=contratto, archiviato=False).exists()


def alert_contratto(contratto: m.Contratto, oggi: datetime.date) -> Alert | None:
    s = scadenza(contratto)
    if s is None:
        return None
    return scadenze.alert(
        s,
        oggi,
        decisione=contratto.fabbisogno.decisione,
        stato_pratica=stato_pratica_corrente(contratto, oggi),
        ha_successore=ha_successore(contratto),
        finestra_mesi=int(parametro(Chiave.FINESTRA_ALERT_MESI, oggi)),
        una_tantum=contratto.una_tantum,
    )


def orizzonte_default(oggi: datetime.date) -> datetime.date:
    """Fine dell'anno di oggi + orizzonte in anni (default 3)."""
    anni = int(parametro(Chiave.ORIZZONTE_ANNI, oggi))
    return datetime.date(oggi.year + anni, 12, 31)


def _successore_attivo(contratto: m.Contratto) -> bool:
    if confluito(contratto):
        return True
    try:
        return not contratto.successore.archiviato
    except m.Contratto.DoesNotExist:
        return False


def _prefetch_contratti(fabbisogno: m.Fabbisogno) -> bool:
    return "contratti" in getattr(fabbisogno, "_prefetched_objects_cache", {})


def contratti_terminali(fabbisogno: m.Fabbisogno):
    """Contratti del fabbisogno senza successore: da qui partono i rinnovi previsti.

    I contratti una tantum non sono nella catena dei rinnovi e non contano (Rev11). Con
    ``PREFETCH_FABBISOGNO`` già caricato non fa query.
    """
    if _prefetch_contratti(fabbisogno):
        return [
            c
            for c in fabbisogno.contratti.all()
            if not c.archiviato
            and not c.una_tantum
            and c.data_inizio is not None
            and not _successore_attivo(c)
        ]
    return (
        fabbisogno.contratti.filter(archiviato=False, una_tantum=False, data_inizio__isnull=False)
        .exclude(successore__archiviato=False)
        .exclude(confluito_in__archiviato=False)
        .select_related("procedura", "fornitore")
        .prefetch_related(*PREFETCH_CALCOLO)
    )


def contratto_base_previsti(fabbisogno: m.Fabbisogno) -> m.Contratto | None:
    """Contratto da cui partono i previsti: il terminale che scade per ultimo.

    Un fabbisogno non ha contratti paralleli (SPEC §5.3): gli altri terminali sono
    catene interrotte.
    """
    terminali = list(contratti_terminali(fabbisogno))
    if not terminali:
        return None
    return max(terminali, key=lambda c: (scadenze.data_fine_effettiva(scadenza(c)), c.pk))


def previsti_fabbisogno(
    fabbisogno: m.Fabbisogno, orizzonte: datetime.date
) -> list[ContrattoPrevisto]:
    """Contratti previsti del fabbisogno fino all'orizzonte (SPEC §5.3)."""
    if fabbisogno.archiviato:
        return []
    if fabbisogno.una_tantum:
        # Acquisto unico: un solo previsto, finché non è registrato un contratto; mai rinnovi.
        if any(not c.archiviato for c in fabbisogno.contratti.all()):
            return []
        return _previsti_manuali(fabbisogno, orizzonte)
    contratto = contratto_base_previsti(fabbisogno)
    if contratto is None:
        # Con soli contratti una tantum valgono i dati del previsto manuale (Rev11).
        if any(not c.archiviato and not c.una_tantum for c in fabbisogno.contratti.all()):
            return []
        return _previsti_manuali(fabbisogno, orizzonte)
    return previsioni.previsti(
        contratto_base(contratto),
        decisione=fabbisogno.decisione,
        orizzonte=orizzonte,
        adeguamento=adeguamento_alla_data,
        stima_manuale=fabbisogno.stima_prossimo_importo,
    )


def contratto_base(contratto: m.Contratto) -> ContrattoBase:
    """Il contratto come punto di partenza dei rinnovi: voci senza quelle delle proroghe."""
    voci, _ = voci_contratto(contratto, con_rate_salvate=False)
    proroghe = {v.pk for v in contratto.voci.all() if v.proroga_id}
    return ContrattoBase(
        fine_effettiva=scadenze.data_fine_effettiva(scadenza(contratto)),
        durata_mesi=contratto.durata_mesi,
        voci=tuple(v for v in voci if v.riferimento not in proroghe),
    )


def _previsti_manuali(fabbisogno: m.Fabbisogno, orizzonte: datetime.date):
    if (
        fabbisogno.previsto_data_avvio is None
        # La decisione di continuità non riguarda un acquisto unico.
        or (fabbisogno.decisione == m.Fabbisogno.Decisione.DISMETTERE and not fabbisogno.una_tantum)
        or fabbisogno.previsto_data_avvio > orizzonte
    ):
        return []
    piano = None
    if fabbisogno.previsto_modalita:
        piano = Piano(
            modalita=Modalita(fabbisogno.previsto_modalita),
            periodicita=fabbisogno.previsto_periodicita,
            giorni_pagamento=int(
                parametro(Chiave.GIORNI_PAGAMENTO, fabbisogno.previsto_data_avvio)
            ),
            pagamento_fine_mese=parametro(
                Chiave.PAGAMENTO_FINE_MESE, fabbisogno.previsto_data_avvio
            )
            == 1,
        )
    primo = previsioni.previsto_manuale(
        inizio=fabbisogno.previsto_data_avvio,
        durata_mesi=fabbisogno.previsto_durata_mesi,
        importo=fabbisogno.stima_prossimo_importo or Decimal(0),
        piano=piano,
    )
    if fabbisogno.una_tantum:
        return [primo]
    base = ContrattoBase(primo.fine, fabbisogno.previsto_durata_mesi, primo.voci)
    seguenti = previsioni.previsti(
        base,
        decisione=fabbisogno.decisione,
        orizzonte=orizzonte,
        adeguamento=adeguamento_alla_data,
    )
    return [primo, *(replace(p, numero=i) for i, p in enumerate(seguenti, start=2))]


def data_fine_effettiva(contratto: m.Contratto) -> datetime.date | None:
    s = scadenza(contratto)
    return scadenze.data_fine_effettiva(s) if s else None


def data_limite_avvio(contratto: m.Contratto) -> datetime.date | None:
    s = scadenza(contratto)
    return scadenze.data_limite_avvio(s) if s else None


@dataclass(frozen=True)
class Classificazione:
    """Natura, conto e WBS di una voce (reale o prevista): dicono in quale budget va."""

    natura: str
    conto: m.ContoCoge | None
    wbs: m.WBS | None
    # Rev18: attività spot autorizzata dall'AD, fuori dai budget dei cluster.
    extra_budget: m.AutorizzazioneExtraBudget | None = None

    @property
    def a_progetto(self) -> bool:
        """Su WBS a progetto: fuori dai budget dei cluster (F9.2)."""
        return self.wbs is not None and self.wbs.tipo == m.WBS.Tipo.PROGETTO

    @property
    def finanziamento(self) -> str:
        if self.extra_budget is not None:
            return m.Contratto.Finanziamento.EXTRA_BUDGET
        if self.a_progetto:
            return m.Contratto.Finanziamento.FINANZIATO
        return m.Contratto.Finanziamento.ORDINARIO


def classificazione(voce: m.VoceContratto) -> Classificazione:
    """La voce reale come è registrata."""
    return Classificazione(
        voce.natura,
        voce.conto,
        voce.wbs if voce.wbs_id else None,
        voce.autorizzazione_extra_budget if voce.autorizzazione_extra_budget_id else None,
    )


def classificazione_prevista(
    fabbisogno: m.Fabbisogno, voce: m.VoceContratto | None
) -> Classificazione:
    """Come andrà in budget il rinnovo previsto della voce (F9.2).

    La voce può decidere natura, conto e WBS dei rinnovi; altrimenti valgono i suoi. Un rinnovo
    in OPEX non ha WBS. Per il previsto manuale (fabbisogno nuovo, senza voci) valgono i dati
    del fabbisogno.
    """
    if voce is None:
        natura = fabbisogno.natura_previsti or m.Natura.OPEX
        wbs = fabbisogno.wbs_previsti if natura == m.Natura.CAPEX else None
        return Classificazione(natura, fabbisogno.conto_previsti, wbs)
    natura = voce.natura_rinnovi or voce.natura
    conto = voce.conto_rinnovi if voce.conto_rinnovi_id else voce.conto
    if natura == m.Natura.OPEX:
        wbs = None
    elif voce.wbs_rinnovi_id:
        wbs = voce.wbs_rinnovi
    else:
        wbs = voce.wbs if voce.wbs_id else None
    return Classificazione(natura, conto, wbs)


def natura_previsti(fabbisogno: m.Fabbisogno, base: m.Contratto | None) -> str:
    """Natura complessiva dei rinnovi previsti: OPEX, CAPEX o "OPEX e CAPEX"."""
    if base is None:
        return classificazione_prevista(fabbisogno, None).natura
    nature = {
        classificazione_prevista(fabbisogno, v).natura
        for v in base.voci.all()
        if not v.archiviato and not v.proroga_id
    }
    if len(nature) > 1:
        return m.Contratto.MISTA
    return nature.pop() if nature else m.Natura.OPEX
