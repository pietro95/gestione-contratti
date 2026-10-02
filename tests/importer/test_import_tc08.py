"""TC-08 sul caricamento: raggruppamento in voci, OdA riusato, dry-run, idempotenza."""

import datetime
from decimal import Decimal

import pytest

from contratti import models as m
from contratti.importer.carica import importa

from .conftest import OGGI, riga

pytestmark = pytest.mark.django_db
D = datetime.date


def test_stesso_oda_cig_e_periodo_un_contratto_con_due_voci(excel):
    percorso = excel(
        [
            riga(Descrizione="Hosting", **{"Corrispettivo Minimo": 1000.0}),
            riga(Descrizione="Backup", **{"Corrispettivo Minimo": 250.5}),
        ]
    )
    report = importa(percorso, area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 1
    contratto = m.Contratto.objects.get()
    assert sorted(v.importo_fisso for v in contratto.voci.all()) == [
        Decimal("250.50"),
        Decimal("1000.00"),
    ]
    assert "ODA_RIUSATO" not in report.codici()


def test_stesso_oda_e_cig_periodi_diversi_due_contratti_e_anomalia(excel):
    percorso = excel(
        [
            riga(**{"Data di attivazione": datetime.datetime(2025, 1, 1)}),
            riga(**{"Data di attivazione": datetime.datetime(2026, 1, 1)}),
        ]
    )
    report = importa(percorso, area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 2
    assert report.codici()["ODA_RIUSATO"] == 2


def test_data_mancante_importato_ed_escluso(excel):
    report = importa(excel([riga(**{"Data di attivazione": None})]), area="IT", oggi=OGGI)
    c = m.Contratto.objects.get()
    assert c.data_inizio is None
    assert report.codici()["DATA_MANCANTE"] == 1


def test_conto_sconosciuto_conservato(excel):
    m.ContoCoge.objects.create(codice="600001", descrizione="Fittizio", valido_dal=D(2020, 1, 1))
    report = importa(
        excel([riga(), riga(Contratto="5800000002", Cig="Z000000002", **{"Codice conto": 62700})]),
        area="IT",
        oggi=OGGI,
    )
    conosciuta, sconosciuta = m.VoceContratto.objects.order_by("contratto__numero_contratto")
    assert conosciuta.conto.codice == "600001"
    assert sconosciuta.conto is None
    assert sconosciuta.codice_conto_importato == "62700"
    assert report.codici()["CONTO_SCONOSCIUTO"] == 1


def test_dry_run_non_scrive_e_produce_lo_stesso_report(excel):
    percorso = excel([riga(Cig="B941B595B")])
    prova = importa(percorso, area="IT", dry_run=True, oggi=OGGI)
    assert not m.Contratto.objects.exists()
    assert not m.Fornitore.objects.exists()
    vero = importa(percorso, area="IT", oggi=OGGI)
    assert prova.codici() == vero.codici()
    assert prova.conteggi["contratti_creati"] == vero.conteggi["contratti_creati"] == 1


def test_import_idempotente(excel):
    percorso = excel([riga(), riga(Contratto="5800000002", Cig="Z000000002")])
    importa(percorso, area="IT", oggi=OGGI)
    secondo = importa(percorso, area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 2
    assert m.VoceContratto.objects.count() == 2
    assert m.Fornitore.objects.count() == 1
    assert secondo.conteggi["contratti_creati"] == 0
    assert secondo.conteggi["contratti_gia_presenti"] == 2


def test_reimport_non_sovrascrive_le_modifiche(excel):
    percorso = excel([riga()])
    importa(percorso, area="IT", oggi=OGGI)
    voce = m.VoceContratto.objects.get()
    voce.importo_fisso = Decimal("1500.00")
    voce.save()
    importa(percorso, area="IT", oggi=OGGI)
    voce.refresh_from_db()
    assert voce.importo_fisso == Decimal("1500.00")


def test_mappatura_stati(excel):
    percorso = excel(
        [
            riga(Contratto="5800000001", Stato="Non rinnovare"),
            riga(Contratto="5800000002", Stato="Rinnovato"),
            riga(Contratto="5800000003", Stato="RDA Richiesta"),
            riga(Contratto="5800000004", Stato="RDA Predisposta", Note="5100004438"),
            riga(Contratto="5800000005", Stato="Offerta richiesta", Note="RDA 3563270716"),
            riga(Contratto="5800000006", Stato="Scaduto"),
            riga(Contratto="5800000007", Stato="Chissà"),
        ]
    )
    report = importa(percorso, area="IT", oggi=OGGI)
    c = {x.numero_contratto: x for x in m.Contratto.objects.select_related("fabbisogno")}
    assert c["5800000001"].fabbisogno.decisione == "dismettere"
    assert c["5800000002"].fabbisogno.decisione == "rinnovare"
    assert c["5800000006"].fabbisogno.decisione == "da_valutare"
    # Lo stato della pratica va sul contratto della riga, alla data dell'import.
    assert c["5800000003"].stati_pratica.get().stato == "rda_richiesta"
    assert c["5800000003"].stati_pratica.get().data == OGGI
    assert c["5800000004"].stati_pratica.get().stato == "rda_predisposta"
    assert c["5800000004"].numero_rda == "5100004438"
    assert c["5800000005"].numero_rda == "3563270716"
    assert "RDA 3563270716" in c["5800000005"].note
    assert not c["5800000002"].stati_pratica.exists()
    assert report.codici()["STATO_SCONOSCIUTO"] == 1


def test_valori_assegnati_ai_dati_mancanti(excel):
    importa(excel([riga()]), area="IT", oggi=OGGI)
    c = m.Contratto.objects.select_related("procedura", "fabbisogno__categoria").get()
    assert c.procedura.codice == "da_verificare"
    assert c.procedura.lead_time_mesi == 6
    assert c.fabbisogno.categoria.nome == "Da classificare"
    piano = c.voci.get().piano_fatturazione
    assert piano.modalita == "da_verificare"
    assert c.chiave_import


def test_massimo_sovrascritto_e_incoerente(excel):
    report = importa(
        excel(
            [
                riga(**{"Corrispettivo Massimo": 1000.0}),
                riga(Contratto="5800000002", **{"Corrispettivo Massimo": 2000.0}),
            ]
        ),
        area="IT",
        oggi=OGGI,
    )
    assert report.codici()["MASSIMO_SOVRASCRITTO"] == 2
    assert report.codici()["MASSIMO_INCOERENTE"] == 1
