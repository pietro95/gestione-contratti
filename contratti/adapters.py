"""Adapter: convertono i modelli Django negli input del motore puro (``contratti.engine``).

Qui si leggono il database e i parametri di configurazione; il motore non li vede mai.
"""

import datetime
from dataclasses import replace
from decimal import Decimal

from contratti import models as m
from contratti.engine import previsioni, scadenze
from contratti.engine.date import UN_GIORNO
from contratti.engine.tipi import (
    Alert,
    ContrattoBase,
    ContrattoPrevisto,
    Esito,
    Modalita,
    Piano,
    Rata,
    Scadenza,
    Voce,
)

Chiave = m.Parametro.Chiave


class ParametroMancante(LookupError):
    pass


def parametro(chiave: str, alla_data: datetime.date) -> Decimal:
    """Valore del parametro valido alla data (l'ultimo con ``valido_dal`` ≤ data)."""
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
    """Piano con i default risolti: giorni di pagamento, fine mese, adeguamento."""
    giorni_pagamento = piano.giorni_pagamento
    if giorni_pagamento is None:
        giorni_pagamento = int(parametro(Chiave.GIORNI_PAGAMENTO, alla_data))
    fine_mese = piano.pagamento_fine_mese
    if fine_mese is None:
        fine_mese = parametro(Chiave.PAGAMENTO_FINE_MESE, alla_data) == 1
    adeguamento = Decimal(0)
    if piano.adeguamento == m.PianoFatturazione.Adeguamento.PERCENTUALE:
        adeguamento = piano.adeguamento_pct
    elif piano.adeguamento == m.PianoFatturazione.Adeguamento.ISTAT:
        # Senza l'indice reale si usa la percentuale del parametro (SPEC §5.2).
        adeguamento = adeguamento_alla_data(alla_data)
    return Piano(
        modalita=Modalita(piano.modalita),
        periodicita=piano.periodicita,
        data_prima_fattura=piano.data_prima_fattura,
        giorni_pagamento=giorni_pagamento,
        pagamento_fine_mese=fine_mese,
        adeguamento_pct=adeguamento,
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
        nuove_date_fine=tuple(contratto.proroghe.values_list("nuova_data_fine", flat=True)),
        tacito_rinnovo=contratto.tacito_rinnovo,
        preavviso_disdetta_giorni=contratto.preavviso_disdetta_giorni,
    )


def _rate_salvate(voce: m.VoceContratto) -> tuple[Rata, ...] | None:
    piano = getattr(voce, "piano_fatturazione", None)
    if piano is None:
        return None
    rate = tuple(
        Rata(r.numero, r.data_fattura, r.data_pagamento_stimata, r.importo)
        for r in piano.rate.order_by("numero")
    )
    return rate or None


def periodi_proroghe(contratto: m.Contratto) -> dict[int, tuple[datetime.date, datetime.date]]:
    """Periodo di servizio di ogni proroga: dal giorno dopo la fine precedente."""
    s = scadenza(contratto)
    precedente = scadenze.data_fine_contrattuale(s)
    periodi = {}
    for p in contratto.proroghe.order_by("nuova_data_fine"):
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
) -> Voce:
    piano = getattr(voce, "piano_fatturazione", None)
    return Voce(
        importo_fisso=voce.importo_fisso,
        inizio=inizio,
        fine=fine,
        anno_impegno=anno_impegno,
        piano=piano_engine(piano, inizio) if piano else None,
        massimale_variabile=voce.massimale_variabile,
        stima_consumo_pct=voce.stima_consumo_pct,
        stima_consumo_importo=voce.stima_consumo_importo,
        rate=_rate_salvate(voce) if con_rate_salvate else None,
        riferimento=voce.pk,
    )


def voci_contratto(
    contratto: m.Contratto, *, con_rate_salvate: bool = True
) -> tuple[list[Voce], list[Esito]]:
    """Voci con periodo di servizio e anno di impegno (SPEC §5.2, TC-10).

    Voce base: periodo del contratto, impegno nell'anno dell'OdA (o dell'inizio).
    Voce di proroga: dal giorno dopo la fine precedente alla nuova fine, impegno
    nell'anno dell'atto.
    """
    s = scadenza(contratto)
    if s is None:
        return [], [Esito("DATA_MANCANTE", f"{contratto}: data di inizio mancante, escluso.")]
    fine_base = scadenze.data_fine_contrattuale(s)
    anno_base = (contratto.data_oda or contratto.data_inizio).year
    periodi = periodi_proroghe(contratto)
    atti = dict(contratto.proroghe.values_list("pk", "data_atto"))
    risultato = []
    voci = contratto.voci.filter(archiviato=False).select_related("piano_fatturazione")
    for voce in voci.order_by("id"):
        if voce.proroga_id:
            inizio, fine = periodi[voce.proroga_id]
            anno = atti[voce.proroga_id].year
        else:
            inizio, fine, anno = contratto.data_inizio, fine_base, anno_base
        risultato.append(voce_engine(voce, inizio, fine, anno, con_rate_salvate=con_rate_salvate))
    return risultato, []


def stato_pratica_corrente(contratto: m.Contratto) -> str | None:
    ultimo = contratto.stati_pratica.order_by("-data", "-id").first()
    return ultimo.stato if ultimo else None


def ha_successore(contratto: m.Contratto) -> bool:
    return m.Contratto.objects.filter(predecessore=contratto, archiviato=False).exists()


def alert_contratto(contratto: m.Contratto, oggi: datetime.date) -> Alert | None:
    s = scadenza(contratto)
    if s is None:
        return None
    return scadenze.alert(
        s,
        oggi,
        decisione=contratto.fabbisogno.decisione,
        stato_pratica=stato_pratica_corrente(contratto),
        ha_successore=ha_successore(contratto),
        finestra_mesi=int(parametro(Chiave.FINESTRA_ALERT_MESI, oggi)),
    )


def orizzonte_default(oggi: datetime.date) -> datetime.date:
    """Fine dell'anno di oggi + orizzonte in anni (default 3)."""
    anni = int(parametro(Chiave.ORIZZONTE_ANNI, oggi))
    return datetime.date(oggi.year + anni, 12, 31)


def contratti_terminali(fabbisogno: m.Fabbisogno):
    """Contratti del fabbisogno senza successore: da qui partono i rinnovi previsti."""
    return (
        fabbisogno.contratti.filter(archiviato=False, data_inizio__isnull=False)
        .exclude(successore__archiviato=False)
        .select_related("procedura")
    )


def previsti_fabbisogno(
    fabbisogno: m.Fabbisogno, orizzonte: datetime.date
) -> list[ContrattoPrevisto]:
    """Contratti previsti del fabbisogno fino all'orizzonte (SPEC §5.3)."""
    if fabbisogno.archiviato:
        return []
    terminali = list(contratti_terminali(fabbisogno))
    if not terminali:
        if fabbisogno.contratti.filter(archiviato=False).exists():
            return []
        return _previsti_manuali(fabbisogno, orizzonte)

    # Un fabbisogno non ha contratti paralleli (SPEC §5.3): i previsti partono dal
    # contratto terminale che scade per ultimo; gli altri sono catene interrotte.
    contratto = max(terminali, key=lambda c: (scadenze.data_fine_effettiva(scadenza(c)), c.pk))
    voci, _ = voci_contratto(contratto, con_rate_salvate=False)
    proroghe = set(contratto.voci.exclude(proroga=None).values_list("pk", flat=True))
    base = ContrattoBase(
        fine_effettiva=scadenze.data_fine_effettiva(scadenza(contratto)),
        durata_mesi=contratto.durata_mesi,
        voci=tuple(v for v in voci if v.riferimento not in proroghe),
    )
    return previsioni.previsti(
        base,
        decisione=fabbisogno.decisione,
        orizzonte=orizzonte,
        adeguamento=adeguamento_alla_data,
        stima_manuale=fabbisogno.stima_prossimo_importo,
    )


def _previsti_manuali(fabbisogno: m.Fabbisogno, orizzonte: datetime.date):
    if (
        fabbisogno.previsto_data_avvio is None
        or fabbisogno.decisione == m.Fabbisogno.Decisione.DISMETTERE
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
