"""F11.4b: import una tantum del Riepilogo RDA Ordini sulla fixture anonimizzata (SPEC §2.3,
§7; decisioni di Pietro del 07/10/2026)."""

import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command

from contratti import acquisti
from contratti import models as m
from contratti.engine.acquisti import Fase
from contratti.importer.riepilogo import importa_riepilogo

from .. import factories as f
from .riepilogo_fixture import crea

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 7)


@pytest.fixture
def registro():
    it, ot = f.cluster("IT"), f.cluster("OT")
    for codice, cluster in (("600010", it), ("600020", ot), ("700001", None)):
        m.ContoCoge.objects.create(
            codice=codice, descrizione=f"Conto {codice}", valido_dal=D(2020, 1, 1),
            cluster=cluster,
        )  # fmt: skip
    m.WBS.objects.create(codice_wbs="WBS-TEST-01", descrizione="WBS di prova", cluster=it)
    m.RichiedenteSAP.objects.create(codice="999901", descrizione="Ufficio di prova")
    a = f.fornitore("Fornitore Prova A S.r.l.")
    esistente = f.contratto(
        fornitore=a, fabbisogno=f.fabbisogno("Servizio OT registrato", cluster=ot),
        numero_contratto="5800000200", data_inizio=D(2025, 7, 1),
    )  # fmt: skip
    f.voce(esistente)
    return {"esistente": esistente, "fornitore_a": a}


@pytest.fixture
def file(tmp_path):
    return crea(tmp_path / "riepilogo.xlsx")


def _codici(report):
    return sorted((a.riga, a.codice) for a in report.anomalie)


def test_import_completo(registro, file):
    report = importa_riepilogo(file, oggi=OGGI)
    c = report.conteggi
    assert (c["rda_lette"], c["rda_create"], c["fuori_perimetro"]) == (6, 4, 2)
    assert (c["contratti_creati"], c["contratti_collegati"], c["fornitori_creati"]) == (4, 1, 1)
    assert c["fatture_create"] == 5
    assert c["contratti_chiusi"] == 4
    codici = _codici(report)
    for atteso in [
        (8, "FUORI_PERIMETRO"),
        (9, "CONTO_CDC_SCAMBIATI"),
        (9, "REFERENTE_MANCANTE"),
        (9, "FORNITORE_CREATO"),
        (9, "CONTRATTO_CREATO"),
        (13, "DATA_NON_LEGGIBILE"),
        (14, "FUORI_PERIMETRO"),
        (16, "CONTRATTO_CREATO"),
    ]:
        assert atteso in codici, atteso
    # Tre contratti chiusi senza attestazione (RDA 5100000101); il collegato ha la ricezione.
    assert [r for r, k in codici if k == "CHIUSO_SENZA_ATTESTAZIONE"] == [9, 9, 9]


def test_rda_e_posizione(registro, file):
    importa_riepilogo(file, oggi=OGGI)
    rda = m.RichiestaAcquisto.objects.get(numero_rda="5100000101")
    assert rda.origine == "import" and rda.referente_utente is None
    assert rda.cluster.codice == "IT" and rda.richiedente.codice == "999901"
    assert rda.data_inserimento == D(2025, 5, 5)
    posizione = rda.posizioni.get()
    # Conto e centro di costo scambiati; importo = importo base del primo contratto.
    assert (posizione.conto.codice, posizione.centro_costo) == ("600010", "10520")
    assert posizione.importo_unitario == Decimal("1000.00")
    # Numero tra apici e WBS: posizione CAPEX.
    progetto = m.RichiestaAcquisto.objects.get(numero_rda="5100000105")
    assert progetto.posizioni.get().wbs.codice_wbs == "WBS-TEST-01"
    # Annullata: nessun contratto, fase annullata.
    annullata = m.RichiestaAcquisto.objects.get(numero_rda="5100000104")
    assert acquisti.fase(annullata, OGGI) == Fase.ANNULLATA


def test_contratti_creati_e_collegati(registro, file):
    importa_riepilogo(file, oggi=OGGI)
    rda = m.RichiestaAcquisto.objects.get(numero_rda="5100000101")
    creati = list(m.Contratto.objects.filter(rda=rda).order_by("numero_contratto"))
    assert [c.numero_contratto for c in creati] == ["5800000101", "5800000102", "5800000103"]
    primo = creati[0]
    assert primo.una_tantum and primo.data_inizio == D(2025, 5, 12)
    assert primo.fabbisogno.descrizione == "Acquisti una tantum IT (dal Riepilogo)"
    assert primo.fabbisogno.categoria.nome == "Da classificare"
    assert primo.data_chiusura == OGGI
    assert primo.fornitore.ragione_sociale == "Fornitore Prova B S.r.l."
    assert primo.voci.get().importo_fisso == Decimal("1000.00")
    # Contratto con inizio e fine: non una tantum, fine come nel file; fornitore riconosciuto.
    progetto = m.Contratto.objects.get(numero_contratto="5800000300")
    assert not progetto.una_tantum and progetto.data_fine_override == D(2026, 9, 30)
    assert progetto.fornitore == registro["fornitore_a"]
    assert progetto.voci.get().importo_fisso == Decimal("1234.50")
    assert progetto.voci.get().massimale_variabile == Decimal("765.50")
    # Contratto già registrato: collegato alla RDA, chiuso con il modello di ricezione.
    esistente = registro["esistente"]
    esistente.refresh_from_db()
    assert esistente.rda.numero_rda == "5100000102"
    assert esistente.data_chiusura == OGGI


def test_fatture_e_documenti(registro, file):
    importa_riepilogo(file, oggi=OGGI)
    c1, c2, c3 = m.Contratto.objects.filter(rda__numero_rda="5100000101").order_by(
        "numero_contratto"
    )
    f1 = c1.fatture.get()
    # Data seriale di Excel, valore base = imponibile, convalidata, trasferita (nota).
    assert (f1.numero, f1.data, f1.valore_base) == ("F-1", D(2025, 5, 31), Decimal("1000.00"))
    assert f1.esito_convalida == "convalidabile" and f1.data_trasferimento == f1.data
    f2 = c2.fatture.get()
    assert f2.importo_documento == Decimal("2308.60") and f2.data_trasferimento is not None
    # Riga senza contratto: la fattura va all'ultimo contratto sopra nella stessa RDA.
    f3 = c3.fatture.get()
    assert f3.numero == "F-3" and f3.data_trasferimento is None
    ddt = c3.documenti_esecuzione.get(tipo="DDT")
    assert (ddt.numero, ddt.data) == ("616/25", D(2025, 5, 27))  # data seriale
    # Numeri SAP legati alla fattura della riga.
    assert c1.documenti_esecuzione.get(tipo="ODA_RDC").fattura == f1
    assert sorted(c2.documenti_esecuzione.filter(tipo="MAP").values_list("numero", flat=True)) == [
        "1000000001",
        "1000000002",
    ]
    # Più fatture in una cella; ricezione finale; MIGO.
    esistente = registro["esistente"]
    assert sorted(esistente.fatture.values_list("numero", flat=True)) == ["FA-10", "FA-11"]
    assert esistente.documenti_esecuzione.get(tipo="RICEZIONE").finale
    assert esistente.documenti_esecuzione.filter(tipo="MIGO").count() == 1


def test_dry_run_e_idempotenza(registro, file):
    report = importa_riepilogo(file, dry_run=True, oggi=OGGI)
    assert report.conteggi["rda_create"] == 4
    assert not m.RichiestaAcquisto.objects.exists()
    importa_riepilogo(file, oggi=OGGI)
    contratti, fatture = m.Contratto.objects.count(), m.Fattura.objects.count()
    report = importa_riepilogo(file, oggi=OGGI)
    assert (report.conteggi["rda_create"], report.conteggi["rda_gia_presenti"]) == (0, 4)
    assert (m.Contratto.objects.count(), m.Fattura.objects.count()) == (contratti, fatture)


def test_comando(registro, file, capsys):
    call_command("import_riepilogo", str(file), "--dry-run")
    assert "rda_create 4" in capsys.readouterr().out
