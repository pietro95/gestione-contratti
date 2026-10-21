"""Rev25: import della struttura dal riepilogo del budget (valori fittizi)."""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounts.roles import ADMIN, EDITOR
from contratti import models as m
from contratti.importer import tabelle
from contratti.importer.struttura_budget import (
    chiave,
    frase,
    importa_struttura_budget,
    leggi,
    nome_e_nota,
)

from .. import factories as f
from . import struttura_budget_fixture as fixture

pytestmark = pytest.mark.django_db
D = datetime.date
PASSWORD = "password-locale-di-prova"


@pytest.fixture
def file(tmp_path):
    return fixture.crea(tmp_path / "budget.xlsx")


def test_nomi_e_note():
    assert nome_e_nota("SICUREZZA FISICA\n(videosorveglianza, antintrusione)") == (
        "Sicurezza fisica",
        "videosorveglianza, antintrusione",
    )
    assert nome_e_nota("SICUREZZA \n(Holding)") == ("Sicurezza (Holding)", "")
    assert nome_e_nota("IT") == ("IT", "")
    assert nome_e_nota("INNOVAZIONE (PoC, scale-up)") == ("Innovazione", "PoC, scale-up")
    assert frase("TELECOMUNICAZIONI") == "Telecomunicazioni" and frase("ICT") == "ICT"
    assert chiave(" Impianti  è ") == "impianti e"


def test_lettura_con_celle_unite(file):
    righe, anno = leggi(file)
    assert anno == 2026
    per = {r.numero: r for r in righe}
    # riga 7: OPEX, cluster e sottocluster ereditati dalle celle unite
    assert (per[7].cluster, per[7].owner, per[7].natura) == ("ALFA", "Mario Rossi", m.Natura.OPEX)
    assert per[6].conti == [("600001", "SERVIZI INTERNET")]
    assert per[6].wbs == ("VJ/00022/001", "Ricerca e sviluppo")
    assert per[10].da_evitare and per[10].wbs[0] == "VJ/00024/001"
    # conti multipli in una cella, con la descrizione di ciascuno
    assert per[17].conti == [("600040", "MATERIALI DI CONSUMO"), ("600041", "SCAVI")]
    # «(non utile)»: WBS del terzo livello, descrizione del primo
    assert per[15].wbs == ("SI.98.MS001.01.9900", "MANUTENZIONE IN CORSO")
    assert per[15].conti == [("600031", "ACQUISTI MATERIALI")]
    assert 20 not in per and all(r.numero < 20 for r in righe)  # si ferma al totale


def test_import_crea_la_struttura(file):
    m.Cluster.objects.create(codice="BE", nome="Beta")  # riconosciuto per nome
    r = importa_struttura_budget(file)
    assert r.conteggi["cluster_creati"] == 2  # ALFA e GAMMA
    assert m.Cluster.objects.get(codice="ALFA").nome == "Alfa"
    sotto = {(s.cluster.codice, s.nome): s for s in m.Sottocluster.objects.all()}
    assert set(sotto) == {
        ("ALFA", "Servizi rete"), ("ALFA", "Elaborazione"),
        ("BE", "Sicurezza fisica"), ("BE", "Sicurezza integrata (intelligence)"),
        ("BE", "Sicurezza (Holding)"), ("BE", "Impianti elettrici"),
        ("GAMMA", "Innovazione"),
    }  # fmt: skip
    assert sotto[("BE", "Sicurezza fisica")].note == "videosorveglianza, antintrusione"
    assert sotto[("BE", "Sicurezza fisica")].owner == "Anna Bianchi"
    # conti: ognuno dei cluster in cui compare; validi dal 1/1/2026
    c = m.ContoCoge.objects.get(codice="600001")
    assert [x.codice for x in c.clusters.all()] == ["ALFA"] and c.valido_dal == D(2026, 1, 1)
    assert m.ContoCoge.objects.get(codice="600010").descrizione == "ACQUISTO MATERIALE"
    assert m.ContoCoge.objects.get(codice="600041").descrizione == "SCAVI"
    assert r.conteggi["conti_creati"] == 8
    # WBS: nuove, di cluster
    w = m.WBS.objects.get(codice_wbs="SI.98.MS001.01.9900")
    assert w.tipo == m.WBS.Tipo.CLUSTER and w.cluster.codice == "BE"
    assert m.WBS.objects.get(codice_wbs="VJ/00022/001").descrizione == "Ricerca e sviluppo"
    codici = r.codici()
    assert codici["WBS_DA_EVITARE"] == 1 and codici["OWNER_DA_ASSEGNARE"] == 6
    assert codici["CONTO_DA_DEFINIRE"] >= 1


def test_idempotente_e_anteprima_non_scrive(file):
    cluster = m.Cluster.objects.count()
    anteprima = importa_struttura_budget(file, dry_run=True)
    assert anteprima.conteggi["conti_creati"] > 0
    assert m.Cluster.objects.count() == cluster and not m.ContoCoge.objects.exists()
    importa_struttura_budget(file)
    seconda = importa_struttura_budget(file)
    assert not any(v for k, v in seconda.conteggi.items())


def test_esistenti_si_riconoscono_e_non_si_alterano(file):
    alfa = f.cluster("ALF")
    alfa.nome = "Alfa"
    alfa.save()
    esistente = m.Sottocluster.objects.create(cluster=alfa, nome="Elaborazione")
    f.cluster("OLD")
    conto = f.conto("600001", "Descrizione SAP", D(2020, 1, 1), cluster=f.cluster("OLD"))
    progetto = m.WBS.objects.create(
        codice_wbs="VJ/00007/001", descrizione="Progetto", tipo=m.WBS.Tipo.PROGETTO
    )
    wbs_cluster = m.WBS.objects.create(
        codice_wbs="VJ/00022/001", descrizione="Descrizione SAP", tipo=m.WBS.Tipo.CLUSTER,
        cluster=f.cluster("OLD"),
    )  # fmt: skip
    r = importa_struttura_budget(file)
    assert m.Cluster.objects.filter(nome__iexact="Alfa").count() == 1
    esistente.refresh_from_db()
    assert (
        esistente.owner == "Mario Rossi"
        and m.Sottocluster.objects.filter(nome="Elaborazione").count() == 1
    )
    conto.refresh_from_db()  # solo i cluster cambiano
    assert conto.descrizione == "Descrizione SAP" and [x.codice for x in conto.clusters.all()] == [
        "ALF"
    ]
    assert m.ContoCoge.objects.filter(codice="600001").count() == 1
    progetto.refresh_from_db()
    assert progetto.tipo == m.WBS.Tipo.PROGETTO and r.codici()["WBS_A_PROGETTO"] == 1
    wbs_cluster.refresh_from_db()
    assert wbs_cluster.cluster.codice == "ALF" and wbs_cluster.descrizione == "Descrizione SAP"


def test_owner_riconosciuto_tra_gli_utenti(file, make_user):
    u = make_user("m.rossi")
    u.first_name, u.last_name = "Mario", "Rossi"
    u.save()
    r = importa_struttura_budget(file)
    messaggi = [a.messaggio for a in r.anomalie if a.codice == "OWNER_DA_ASSEGNARE"]
    assert any("m.rossi" in t for t in messaggi) and any("non riconosciuto" in t for t in messaggi)
    assert not m.AssegnazioneCluster.objects.exists()  # nessun permesso dato in automatico


def test_cluster_con_codice_inutilizzabile_blocca_tutto(tmp_path):
    percorso = fixture.crea(tmp_path / "b.xlsx")
    import openpyxl

    wb = openpyxl.load_workbook(percorso)
    wb.active["A12"] = "UN CLUSTER CON NOME TROPPO LUNGO"
    wb.save(percorso)
    cluster = m.Cluster.objects.count()
    with pytest.raises(tabelle.FileNonValido, match="Crealo prima"):
        importa_struttura_budget(percorso)
    assert m.Cluster.objects.count() == cluster and not m.Sottocluster.objects.exists()


def test_file_non_riconosciuto(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active["A1"] = "niente"
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(tabelle.FileNonValido, match="intestazioni"):
        importa_struttura_budget(tmp_path / "x.xlsx")


def test_import_dall_interfaccia_solo_admin(file, make_user):
    make_user("amm", role=ADMIN, is_superuser=True, is_staff=True)
    make_user("ed", role=EDITOR)
    contenuto = open(file, "rb").read()
    url = reverse("contratti:importazione_carica", args=["struttura_budget"])
    ed = Client()
    ed.login(username="ed", password=PASSWORD)
    assert (
        ed.post(url, {"struttura_budget-file": SimpleUploadedFile("b.xlsx", contenuto)}).status_code
        == 403
    )
    admin = Client()
    admin.login(username="amm", password=PASSWORD)
    risposta = admin.post(url, {"struttura_budget-file": SimpleUploadedFile("b.xlsx", contenuto)})
    imp = m.Importazione.objects.get()
    assert risposta.status_code == 302 and imp.stato == m.Importazione.Stato.ANTEPRIMA
    admin.post(reverse("contratti:importazione_conferma", args=[imp.pk]))
    assert m.Sottocluster.objects.filter(nome="Innovazione").exists()
