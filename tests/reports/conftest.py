"""Archivio di prova per i report: le due fixture anonimizzate più casi costruiti a mano."""

import datetime
from decimal import Decimal

import pytest

from contratti import adapters, servizi
from contratti import models as m
from contratti.engine import budget as motore
from contratti.importer.carica import importa

from .. import factories as f
from ..importer.conftest import IT, TLC

OGGI = datetime.date(2026, 10, 1)
ANNI = range(2024, 2031)
D = datetime.date


@pytest.fixture
def conti(db):
    return {
        codice: m.ContoCoge.objects.create(
            codice=codice, descrizione=f"Conto {codice}", valido_dal="2020-01-01"
        )
        for codice in ("634935", "627020", "627021", "635220", "627029", "627030", "627031")
    }


@pytest.fixture
def archivio(conti):
    """Fixture importate + un contratto con scadenzario salvato, proroga e un previsto manuale."""
    importa(IT, area="IT", oggi=OGGI)
    importa(TLC, area="TLC", oggi=OGGI)

    fab = f.fabbisogno("Servizio costruito per i report", area=m.Area.TLC, decisione="rinnovare")
    c = f.contratto(
        fabbisogno=fab,
        data_inizio=D(2026, 1, 1),
        durata_mesi=24,
        data_oda=D(2025, 12, 15),
        finanziamento=m.Contratto.Finanziamento.FINANZIATO,
        progetto=m.Progetto.objects.create(codice_wbs="WBS-PROVA", descrizione="Prova"),
    )
    v = f.voce(
        c,
        importo_fisso=Decimal("12000.00"),
        massimale_variabile=Decimal("3000.00"),
        stima_consumo_pct=Decimal("50"),
        conto=conti["627020"],
    )
    f.piano(v, modalita="posticipata", periodicita="trimestrale")
    servizi.genera_scadenzario(v)
    servizi.registra_proroga(
        c,
        {"data_atto": D(2027, 11, 1), "nuova_data_fine": D(2028, 6, 30), "riferimento": "Atto"},
        {"importo_fisso": Decimal("3000.00"), "descrizione": "Proroga", "modalita": "una_tantum"},
    )

    f.fabbisogno(
        "Nuovo servizio previsto a mano",
        decisione="rinnovare",
        previsto_data_avvio=D(2027, 3, 1),
        previsto_durata_mesi=12,
        stima_prossimo_importo=Decimal("50000.00"),
        previsto_modalita="anticipata",
        previsto_periodicita="annuale",
    )
    return c


def voci_motore(anno: int, oggi: datetime.date = OGGI):
    """Voci consolidate e previste dell'anno, raccolte direttamente dagli adapter."""
    with adapters.parametri_in_cache():
        return _voci_motore(anno, oggi)


def _voci_motore(anno, oggi):
    consolidate, previste = [], []
    for c in m.Contratto.objects.filter(
        archiviato=False, fabbisogno__archiviato=False, data_inizio__isnull=False
    ):
        consolidate += adapters.voci_contratto(c)[0]
    orizzonte = max(adapters.orizzonte_default(oggi), D(anno, 12, 31))
    for fab in m.Fabbisogno.objects.filter(archiviato=False):
        for p in adapters.previsti_fabbisogno(fab, orizzonte):
            if p.fine >= D(anno, 1, 1):
                previste += p.voci
    return consolidate, previste


def totali_motore(voci, anno):
    viste, _ = motore.calcola(voci)
    return {vista: viste[vista].per_anno.get(anno, {}) for vista in viste}
