"""Query e righe calcolate per elenchi e cruscotto. I valori derivati vengono dal motore."""

import datetime
from dataclasses import dataclass

from django.db.models import Count, F, Prefetch, Q

from contratti import acquisti, adapters
from contratti import models as m
from contratti.engine import scadenze
from contratti.engine.date import aggiungi_mesi
from contratti.engine.tipi import Alert

ORDINE_ALERT = {Alert.ROSSO: 0, Alert.ARANCIONE: 1, Alert.GIALLO: 2, Alert.VERDE: 3, None: 4}


@dataclass
class RigaContratto:
    contratto: m.Contratto
    fine: datetime.date | None
    data_limite: datetime.date | None
    alert: Alert | None
    stato: str  # attivo / scaduto / futuro / senza_data
    stato_pratica: str | None
    giorni_al_limite: int | None
    previsto_manuale: m.Fabbisogno | None = None  # fabbisogno della riga, senza contratto

    @property
    def stato_pratica_label(self):
        if not self.stato_pratica:
            return "Non avviata"
        return m.StatoPratica.Stato(self.stato_pratica).label


def _stato_temporale(contratto, fine, oggi) -> str:
    if contratto.data_inizio is None or fine is None:
        return "senza_data"
    if oggi < contratto.data_inizio:
        return "futuro"
    if oggi > fine:
        return "scaduto"
    return "attivo"


def contratti_base():
    return (
        m.Contratto.objects.select_related(
            "fabbisogno",
            "fabbisogno__sottocluster",
            "fabbisogno__cluster",
            "fornitore",
            "procedura",
            "confluito_in",
        )
        .prefetch_related(
            "proroghe",
            # Natura e finanziamento del contratto si ricavano dalle voci.
            Prefetch("voci", queryset=m.VoceContratto.objects.select_related("wbs")),
            Prefetch("stati_pratica", queryset=m.StatoPratica.objects.order_by("-data", "-id")),
            acquisti.PREFETCH_PRATICA_CONTRATTO,
        )
        .annotate(
            n_successori=Count("successore", filter=Q(successore__archiviato=False)),
        )
    )


def riga_contratto(c: m.Contratto, oggi: datetime.date, finestra: int) -> RigaContratto:
    s = adapters.scadenza(c)
    stato_pratica = acquisti.stato_pratica(c, oggi)
    if s is None:
        return RigaContratto(c, None, None, None, "senza_data", stato_pratica, None)
    fine = scadenze.data_fine_effettiva(s)
    limite = scadenze.data_riferimento_alert(s)
    colore = scadenze.alert(
        s,
        oggi,
        decisione=c.fabbisogno.decisione,
        stato_pratica=stato_pratica,
        ha_successore=getattr(c, "n_successori", 0) > 0 or adapters.confluito(c),
        finestra_mesi=finestra,
        una_tantum=c.una_tantum,
    )
    return RigaContratto(
        contratto=c,
        fine=fine,
        data_limite=limite,
        alert=colore,
        stato=_stato_temporale(c, fine, oggi),
        stato_pratica=stato_pratica,
        giorni_al_limite=(limite - oggi).days,
    )


def finestra_alert(oggi: datetime.date) -> int:
    return int(adapters.parametro(m.Parametro.Chiave.FINESTRA_ALERT_MESI, oggi))


def righe_contratti(queryset, oggi: datetime.date) -> list[RigaContratto]:
    finestra = finestra_alert(oggi)
    return [riga_contratto(c, oggi, finestra) for c in queryset]


def codici_cluster(valore) -> list[str]:
    """Il filtro «area»: un codice di cluster o una lista di codici; vuoto = tutti."""
    if not valore:
        return []
    return [valore] if isinstance(valore, str) else [v for v in valore if v]


def righe_previsti_manuali(oggi: datetime.date, filtri: dict) -> list[RigaContratto]:
    """Fabbisogni nuovi (senza contratti) con previsto manuale, per il cruscotto."""
    finestra = finestra_alert(oggi)
    qs = (
        m.Fabbisogno.objects.filter(
            archiviato=False,
            previsto_data_avvio__isnull=False,
            contratti__isnull=True,
        )
        .select_related("previsto_procedura", "sottocluster")
        .prefetch_related(
            Prefetch("stati_pratica", queryset=m.StatoPratica.objects.order_by("-data", "-id")),
            acquisti.PREFETCH_PRATICA_FABBISOGNO,
        )
    )
    if codici := codici_cluster(filtri.get("area")):
        qs = qs.filter(cluster__codice__in=codici)
    if filtri.get("sottocluster"):
        qs = qs.filter(sottocluster_id=filtri["sottocluster"])
    default = m.Procedura.objects.filter(codice="da_verificare").first()
    righe = []
    for f in qs:
        procedura = f.previsto_procedura or default
        lead = procedura.lead_time_mesi if procedura else 0
        stato = acquisti.stato_pratica(f, oggi)
        colore = scadenze.alert_previsto_manuale(
            f.previsto_data_avvio,
            lead,
            oggi,
            # Un acquisto unico va avviato comunque: la decisione di continuità non conta.
            decisione=m.Fabbisogno.Decisione.DA_VALUTARE if f.una_tantum else f.decisione,
            stato_pratica=stato,
            finestra_mesi=finestra,
        )
        limite = aggiungi_mesi(f.previsto_data_avvio, -lead)
        righe.append(
            RigaContratto(
                contratto=None,
                fine=f.previsto_data_avvio,
                data_limite=limite,
                alert=colore,
                stato="futuro",
                stato_pratica=stato,
                giorni_al_limite=(limite - oggi).days,
                previsto_manuale=f,
            )
        )
    return righe


def contratti_terminali():
    """Contratti senza successore attivo: sono quelli che possono avere un alert.

    I contratti una tantum non si rinnovano e non vanno in alert (Rev11).
    """
    return (
        contratti_base()
        .filter(archiviato=False, una_tantum=False, data_inizio__isnull=False)
        .exclude(successore__archiviato=False)
        .exclude(confluito_in__archiviato=False)
    )


def cruscotto(oggi: datetime.date, filtri: dict) -> dict[Alert, list[RigaContratto]]:
    qs = contratti_terminali().filter(fabbisogno__archiviato=False)
    if codici := codici_cluster(filtri.get("area")):
        qs = qs.filter(fabbisogno__cluster__codice__in=codici)
    if filtri.get("sottocluster"):
        qs = qs.filter(fabbisogno__sottocluster_id=filtri["sottocluster"])
    gruppi: dict[Alert, list[RigaContratto]] = {
        Alert.ROSSO: [],
        Alert.ARANCIONE: [],
        Alert.GIALLO: [],
    }
    righe = righe_contratti(qs, oggi) + righe_previsti_manuali(oggi, filtri)
    for riga in righe:
        if riga.alert in gruppi:
            gruppi[riga.alert].append(riga)
    for righe in gruppi.values():
        righe.sort(key=lambda r: r.data_limite or datetime.date.max)
    return gruppi


def voci_piano_da_verificare(codici: list[str] | None = None, sottocluster: int | None = None):
    """Voci attive senza piano di fatturazione reale: il fatturato è a mesi frazionati.

    Le più pesanti prima (fisso + massimale): sono quelle che spostano di più il budget.
    ``codici``: cluster da mostrare, ``sottocluster``: id del sottocluster; vuoto = tutti.
    """
    qs = (
        m.VoceContratto.objects.filter(
            archiviato=False, contratto__archiviato=False, contratto__fabbisogno__archiviato=False
        )
        .filter(
            Q(piano_fatturazione__isnull=True)
            | Q(piano_fatturazione__modalita=m.ModalitaFatturazione.DA_VERIFICARE)
        )
        .select_related("contratto__fabbisogno", "contratto__fornitore", "piano_fatturazione")
        .annotate(peso=F("importo_fisso") + F("massimale_variabile"))
        .order_by("-peso", "contratto__fabbisogno__descrizione", "pk")
    )
    if codici:
        qs = qs.filter(contratto__fabbisogno__cluster__codice__in=codici)
    if sottocluster:
        qs = qs.filter(contratto__fabbisogno__sottocluster_id=sottocluster)
    return qs


# Ricerca globale (barra superiore e connettore MCP): stessi criteri e stessi limiti.
LIMITE_CERCA = {"contratti": 25, "fabbisogni": 15, "fornitori": 15, "rda": 15, "fatture": 15}


def cerca(q: str, oggi: datetime.date) -> dict[str, list]:
    """Contratti (come righe calcolate), fabbisogni e fornitori che contengono ``q``.

    Meno di 2 caratteri: nessun risultato. Gli archiviati in fondo.
    """
    risultati = {"contratti": [], "fabbisogni": [], "fornitori": [], "rda": [], "fatture": []}
    q = q.strip()
    if len(q) < 2:
        return risultati
    contratti = contratti_base().filter(
        Q(descrizione__icontains=q)
        | Q(fabbisogno__descrizione__icontains=q)
        | Q(numero_contratto__icontains=q)
        | Q(cig__icontains=q)
        | Q(numero_rda__icontains=q)
        | Q(fornitore__ragione_sociale__icontains=q)
    )
    risultati["contratti"] = righe_contratti(
        contratti.order_by("archiviato", "-data_inizio")[: LIMITE_CERCA["contratti"]], oggi
    )
    risultati["fabbisogni"] = list(
        m.Fabbisogno.objects.filter(Q(descrizione__icontains=q) | Q(referente__icontains=q))
        .select_related("sottocluster", "cluster")
        .order_by("archiviato", "descrizione")[: LIMITE_CERCA["fabbisogni"]]
    )
    risultati["fornitori"] = list(
        m.Fornitore.objects.filter(
            Q(ragione_sociale__icontains=q)
            | Q(partita_iva__icontains=q)
            | Q(codice_sap__icontains=q)
        ).order_by("archiviato", "ragione_sociale")[: LIMITE_CERCA["fornitori"]]
    )
    risultati["rda"] = list(
        m.RichiestaAcquisto.objects.filter(
            Q(numero_rda__icontains=q) | Q(descrizione__icontains=q) | Q(intestazione__icontains=q)
        )
        .select_related("cluster")
        .order_by("archiviato", "-data_creazione")[: LIMITE_CERCA["rda"]]
    )
    # F11.3: numero di fattura e numeri dei documenti SAP (RdC/ODA, MAP, MIGO).
    risultati["fatture"] = list(
        m.Fattura.objects.filter(Q(numero__icontains=q) | Q(documenti__numero__icontains=q))
        .select_related("fornitore", "contratto")
        .distinct()
        .order_by("archiviato", "-data")[: LIMITE_CERCA["fatture"]]
    )
    return risultati


def catena(contratto: m.Contratto) -> list[m.Contratto]:
    """Contratti della catena dei rinnovi, dal più vecchio al più recente."""
    prima, c, visti = [], contratto.predecessore, {contratto.pk}
    while c is not None and c.pk not in visti and len(prima) < 20:
        prima.insert(0, c)
        visti.add(c.pk)
        c = c.predecessore
    dopo, c = [], m.Contratto.objects.filter(predecessore=contratto).first()
    while c is not None and c.pk not in visti and len(dopo) < 20:
        dopo.append(c)
        visti.add(c.pk)
        c = m.Contratto.objects.filter(predecessore=c).first()
    return [*prima, contratto, *dopo]


def previsti_dopo(contratto: m.Contratto, oggi: datetime.date):
    """Rinnovi previsti, se questo è il contratto da cui partono."""
    base = adapters.contratto_base_previsti(contratto.fabbisogno)
    if base is None or base.pk != contratto.pk:
        return []
    return adapters.previsti_fabbisogno(contratto.fabbisogno, adapters.orizzonte_default(oggi))
