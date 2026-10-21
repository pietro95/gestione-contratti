"""Spese extra budget (Rev18): per un'autorizzazione dell'AD, le voci collegate e gli importi
anno per anno, come le Spese per WBS. Le voci extra budget sono fuori dai budget dei cluster.

Il **consumato** è il massimo contrattuale delle voci collegate (fisso + massimale variabile),
cioè quanto impegna l'azienda; oltre l'importo autorizzato si mostra un avviso, non si blocca.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from contratti import adapters
from contratti import models as m
from contratti.engine.acquisti import formato_euro
from contratti.engine.importi import ZERO
from contratti.engine.tipi import Livello
from reports.wbs import RigaWBS, importi_per_anno

_VOCI_ATTIVE = Q(voci__archiviato=False, voci__contratto__archiviato=False)


def consumato(autorizzazione: m.AutorizzazioneExtraBudget) -> Decimal:
    """Massimo contrattuale (fisso + massimale) delle voci attive collegate."""
    totale = m.VoceContratto.objects.filter(
        autorizzazione_extra_budget=autorizzazione, archiviato=False, contratto__archiviato=False
    ).aggregate(t=Sum(F("importo_fisso") + F("massimale_variabile")))["t"]
    return totale or ZERO


def avviso_sforamento(autorizzazione: m.AutorizzazioneExtraBudget, usato: Decimal) -> str:
    if usato <= autorizzazione.importo_autorizzato:
        return ""
    autorizzato = autorizzazione.importo_autorizzato
    return (
        f"Le voci collegate impegnano {formato_euro(usato)}, oltre l'importo autorizzato "
        f"dall'AD ({formato_euro(autorizzato)}) di {formato_euro(usato - autorizzato)}."
    )


@dataclass
class SpeseExtraBudget:
    autorizzazione: m.AutorizzazioneExtraBudget
    vista: str
    livello: Livello
    consumato: Decimal = ZERO
    righe: list[RigaWBS] = field(default_factory=list)
    esclusi: list[str] = field(default_factory=list)

    @property
    def anni(self) -> list[int]:
        return sorted({a for r in self.righe for a in r.per_anno})

    def totali(self) -> dict[int, Decimal]:
        return {a: sum((r.per_anno.get(a, ZERO) for r in self.righe), ZERO) for a in self.anni}

    @property
    def totale(self) -> Decimal:
        return sum(self.totali().values(), ZERO)

    @property
    def residuo(self) -> Decimal:
        return self.autorizzazione.importo_autorizzato - self.consumato

    @property
    def avviso(self) -> str:
        return avviso_sforamento(self.autorizzazione, self.consumato)


def spese_extra_budget(
    autorizzazione: m.AutorizzazioneExtraBudget,
    vista: str = "cassa",
    livello: Livello = Livello.PROBABILE,
) -> SpeseExtraBudget:
    risultato = SpeseExtraBudget(autorizzazione, vista, livello, consumato(autorizzazione))
    contratti = (
        m.Contratto.objects.filter(
            archiviato=False,
            voci__autorizzazione_extra_budget=autorizzazione,
            voci__archiviato=False,
        )
        .distinct()
        .select_related("fabbisogno__cluster", "fornitore", "procedura")
        .prefetch_related(*adapters.PREFETCH_CALCOLO)
        .order_by("data_inizio", "pk")
    )
    with adapters.parametri_in_cache():
        for c in contratti:
            if c.data_inizio is None:
                risultato.esclusi.append(str(c))
                continue
            voci_engine, _ = adapters.voci_contratto(c)
            modelli = {v.pk: v for v in c.voci.all()}
            for ve in voci_engine:
                voce = modelli[ve.riferimento]
                if voce.autorizzazione_extra_budget_id != autorizzazione.pk:
                    continue
                per_anno = importi_per_anno(ve, vista, livello)
                risultato.righe.append(RigaWBS(voce, c, ve.inizio, ve.fine, per_anno))
    return risultato


def elenco_autorizzazioni(
    codici_cluster: list[str], archiviate: bool = False, sottocluster: int | None = None
):
    """Autorizzazioni con numero di voci e consumato; di default dei cluster dati.

    Con ``sottocluster``: solo quelle con almeno una voce di un fabbisogno di quel
    sottocluster; numero di voci e consumato contano solo quelle voci.
    """
    zero = Value(ZERO, output_field=DecimalField(max_digits=14, decimal_places=2))
    voci = _VOCI_ATTIVE
    if sottocluster:
        voci = voci & Q(voci__contratto__fabbisogno__sottocluster_id=sottocluster)
    qs = m.AutorizzazioneExtraBudget.objects.select_related("cluster").annotate(
        n_voci=Count("voci", filter=voci, distinct=True),
        consumato=Coalesce(
            Sum(F("voci__importo_fisso") + F("voci__massimale_variabile"), filter=voci),
            zero,
        ),
    )
    if sottocluster:
        qs = qs.filter(n_voci__gt=0)
    if not archiviate:
        qs = qs.filter(archiviato=False)
    if codici_cluster:
        qs = qs.filter(cluster__codice__in=codici_cluster)
    return qs.order_by("-data_autorizzazione", "codice")
