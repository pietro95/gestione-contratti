"""Query e righe calcolate per elenchi e cruscotto. I valori derivati vengono dal motore."""

import datetime
from dataclasses import dataclass

from django.db.models import Count, F, Prefetch, Q

from contratti import adapters
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
    spesa_ricorrente: bool = False  # promemoria di una spesa senza contratto (F9.5)

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
            "fabbisogno__categoria",
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
        )
        .annotate(
            n_successori=Count("successore", filter=Q(successore__archiviato=False)),
        )
    )


def riga_contratto(c: m.Contratto, oggi: datetime.date, finestra: int) -> RigaContratto:
    s = adapters.scadenza(c)
    stato_pratica = next(iter(c.stati_pratica.all()), None)
    stato_pratica = stato_pratica.stato if stato_pratica else None
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
            senza_contratto=False,
            previsto_data_avvio__isnull=False,
            contratti__isnull=True,
        )
        .select_related("previsto_procedura", "categoria")
        .prefetch_related(
            Prefetch("stati_pratica", queryset=m.StatoPratica.objects.order_by("-data", "-id"))
        )
    )
    if codici := codici_cluster(filtri.get("area")):
        qs = qs.filter(cluster__codice__in=codici)
    if filtri.get("categoria"):
        qs = qs.filter(categoria_id=filtri["categoria"])
    default = m.Procedura.objects.filter(codice="da_verificare").first()
    righe = []
    for f in qs:
        procedura = f.previsto_procedura or default
        lead = procedura.lead_time_mesi if procedura else 0
        ultimo = next(iter(f.stati_pratica.all()), None)
        stato = ultimo.stato if ultimo else None
        colore = scadenze.alert_previsto_manuale(
            f.previsto_data_avvio,
            lead,
            oggi,
            decisione=f.decisione,
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


def righe_spese_ricorrenti(oggi: datetime.date, filtri: dict) -> list[RigaContratto]:
    """Promemoria delle spese senza contratto: solo 🟡 prima della prossima spesa (§5.6)."""
    qs = m.Fabbisogno.objects.filter(archiviato=False, senza_contratto=True)
    if codici := codici_cluster(filtri.get("area")):
        qs = qs.filter(cluster__codice__in=codici)
    if filtri.get("categoria"):
        qs = qs.filter(categoria_id=filtri["categoria"])
    righe = []
    for f in qs.select_related("spesa_fornitore"):
        colore, prossima = adapters.promemoria_spesa(f, oggi)
        if colore is None:
            continue
        righe.append(
            RigaContratto(
                contratto=None,
                fine=prossima,
                data_limite=prossima,
                alert=colore,
                stato="attivo",
                stato_pratica=None,
                giorni_al_limite=(prossima - oggi).days,
                previsto_manuale=f,
                spesa_ricorrente=True,
            )
        )
    return righe


def contratti_terminali():
    """Contratti senza successore attivo: sono quelli che possono avere un alert."""
    return (
        contratti_base()
        .filter(archiviato=False, data_inizio__isnull=False)
        .exclude(successore__archiviato=False)
        .exclude(confluito_in__archiviato=False)
    )


def cruscotto(oggi: datetime.date, filtri: dict) -> dict[Alert, list[RigaContratto]]:
    qs = contratti_terminali().filter(fabbisogno__archiviato=False)
    if codici := codici_cluster(filtri.get("area")):
        qs = qs.filter(fabbisogno__cluster__codice__in=codici)
    if filtri.get("categoria"):
        qs = qs.filter(fabbisogno__categoria_id=filtri["categoria"])
    gruppi: dict[Alert, list[RigaContratto]] = {
        Alert.ROSSO: [],
        Alert.ARANCIONE: [],
        Alert.GIALLO: [],
    }
    righe = (
        righe_contratti(qs, oggi)
        + righe_previsti_manuali(oggi, filtri)
        + righe_spese_ricorrenti(oggi, filtri)
    )
    for riga in righe:
        if riga.alert in gruppi:
            gruppi[riga.alert].append(riga)
    for righe in gruppi.values():
        righe.sort(key=lambda r: (r.data_limite or datetime.date.max))
    return gruppi


def voci_piano_da_verificare(codici: list[str] | None = None):
    """Voci attive senza piano di fatturazione reale: il loro fatturato è un pro-rata.

    Le più pesanti prima (fisso + massimale): sono quelle che spostano di più il budget.
    ``codici``: cluster da mostrare; vuoto = tutti.
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
    return qs
