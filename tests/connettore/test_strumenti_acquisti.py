"""F12.1: tool di lettura del processo d'acquisto (SPEC_MCP Rev08 §11.1, §11.2).

Gli stessi valori dell'interfaccia: TC-15 (fasi), TC-16 (esecuzione), TC-17 (testo della
richiesta), TC-18 (fatture, referente proposto, commento per PAC).
"""

import datetime
import io
from decimal import Decimal

import openpyxl
import pytest
from django.test import Client
from django.urls import reverse

from accounts.roles import EDITOR, READER
from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import acquisti, fatture
from contratti import models as m
from contratti.importer.fatture import importa_fatture
from tests import factories as f
from tests.connettore.conftest import chiama
from tests.engine.test_tc17_scheda_sap import TESTO_ATTESO
from tests.engine.test_tc18_fatture import PAC_ATTESO
from tests.test_acquisti import BASE, tabelle_sap  # noqa: F401
from tests.test_tc18_fatture import file_tc18, registro  # noqa: F401

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 7)


def esegui(utente, nome, argomenti=None, oggi=OGGI):
    risposta, _ = protocollo.gestisci(chiama(nome, argomenti), Contesto(utente, oggi))
    risultato = risposta["result"]
    assert not risultato.get("isError"), risultato
    return risultato["structuredContent"]


def errore(utente, nome, argomenti=None) -> str:
    risposta, _ = protocollo.gestisci(chiama(nome, argomenti), Contesto(utente, OGGI))
    assert risposta["result"]["isError"] is True
    return risposta["result"]["content"][0]["text"]


@pytest.fixture
def lettore(make_user):
    return make_user("lettore_mcp", role=READER)


# --- RDA ------------------------------------------------------------------------------


@pytest.fixture
def rda_tc17(tabelle_sap, make_user):  # noqa: F811
    fornitore, conti = tabelle_sap
    rossi = make_user("rossi_rda", role=EDITOR, first_name="Mario", last_name="Rossi",
                      email="rossi@esempio.test")  # fmt: skip
    rda = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"),
        origine=m.RichiestaAcquisto.Origine.MANUALE,
        referente_utente=rossi,
        intestazione="SWPROVA - Rinnovo licenza CAD (2 postazioni)",
        descrizione="Rinnovo licenza CAD (2 postazioni)",
        fornitore_proposto=fornitore,
        richiedente=m.RichiedenteSAP.objects.get(codice="999901"),
        gruppo_acquisti=m.GruppoAcquisti.objects.get(codice="G01"),
        note_buyer="Si allega preventivo",
        allegati="preventivo nella cartella del file server",
        percorso_file_server=f"{BASE}/2026/2026_09_29_SWPROVA_Rinnovo_licenza_CAD_2_postazioni",
        note="Nota interna da non esporre",
        data_creazione=D(2026, 6, 1),
    )
    for numero, (descrizione, gm, q, prezzo, conto) in enumerate(
        [
            ("SWPROVA - Rinnovo licenza CAD (2 postazioni)", "GM-TEST01", "2", "549.50", "600001"),
            ("Supporto installazione", "GM-TEST02", "2.5", "99.99", "600002"),
        ],
        start=1,
    ):
        m.PosizioneRDA.objects.create(
            rda=rda, numero=numero, descrizione_breve=descrizione,
            gruppo_merci=m.GruppoMerci.objects.get(codice=gm), quantita=Decimal(q),
            importo_unitario=Decimal(prezzo), conto=conti[conto], centro_costo="C0001",
        )  # fmt: skip
    return rda


def test_rda_testo_tc17_e_dati_esposti(rda_tc17, lettore):
    dati = esegui(lettore, "rda", {"id": rda_tc17.pk})
    assert dati["testo_richiesta"] == TESTO_ATTESO == acquisti.testo_della_richiesta(rda_tc17)
    assert dati["importo"] == "1348.98"
    assert [p["quantita"] for p in dati["posizioni"]] == ["2", "2.5"]
    assert dati["fase"] == "bozza" and dati["referente"] == "Mario Rossi"
    campi = {(c.get("posizione"), c["campo"]): c for c in dati["scheda_sap"]}
    assert campi[(2, "Importo unitario")]["valore"] == "99,99"
    assert campi[(2, "Quantità")]["valore"] == "2,5"
    assert campi[(1, "Codice WBS")] == {"posizione": 1, "campo": "Codice WBS", "valore": "--",
                                        "sap": False}  # fmt: skip
    assert dati["testo_libero"]["note_buyer"] == "Si allega preventivo"
    # Minimizzazione (D16): solo il nome del referente, nessuna nota generica.
    testo = str(dati)
    assert "rossi@esempio.test" not in testo and "Nota interna" not in testo


def test_rda_fasi_tc15(rda_tc17, lettore, make_user):
    addetto = make_user("addetto_mcp", role=EDITOR)
    acquisti.invia(rda_tc17, rda_tc17.referente_utente, D(2026, 6, 2))
    acquisti.rimanda(rda_tc17, "Manca il preventivo", addetto, D(2026, 6, 3))
    dati = esegui(lettore, "rda", {"id": rda_tc17.pk})
    assert dati["fase"] == "da_correggere"
    assert dati["storico"][0]["testo_libero"] == "Manca il preventivo"
    assert dati["storico"][0]["utente"] == "addetto_mcp"
    acquisti.invia(rda_tc17, rda_tc17.referente_utente, D(2026, 6, 4))
    acquisti.aggiorna_dati_sap(rda_tc17, "5100000001", D(2026, 6, 15), None)
    # TC-15 (e): ferma al 16/07/2026, non al 15/07/2026.
    assert not esegui(lettore, "rda", {"id": rda_tc17.pk}, D(2026, 7, 15))["ferma"]
    dati = esegui(lettore, "rda", {"id": rda_tc17.pk}, D(2026, 7, 16))
    assert (dati["fase"], dati["ferma"], dati["numero_rda"]) == ("inserita", True, "5100000001")


def test_elenco_rda_come_la_vista_e_l_export(rda_tc17, lettore, make_user):
    acquisti.aggiorna_dati_sap(rda_tc17, "5100000001", D(2026, 6, 15), None)
    altra = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("TLC"), origine="manuale", descrizione="Altra", numero_rda="5100000002",
        data_inserimento=D(2025, 12, 1),
    )  # fmt: skip
    m.PosizioneRDA.objects.create(
        rda=altra, numero=1, descrizione_breve="X", importo_unitario=Decimal("10.00")
    )
    dati = esegui(lettore, "elenco_rda", {"cluster": ["tutti"]})
    assert dati["totale"] == 2 and dati["totale_importo"] == "1358.98"
    assert {x["fase"]: x["rda"] for x in dati["per_fase"]} == {"inserita": 2}
    assert esegui(lettore, "elenco_rda", {"cluster": ["TLC"]})["totale"] == 1
    assert esegui(lettore, "elenco_rda", {"cluster": ["tutti"], "anno": 2025})["totale"] == 1
    mie = esegui(rda_tc17.referente_utente, "elenco_rda", {"cluster": ["tutti"],
                                                          "referente": "me"})  # fmt: skip
    assert [r["id"] for r in mie["righe"]] == [rda_tc17.pk]
    # Stesso totale dell'export XLSX della vista «Stato delle RDA».
    client = Client()
    client.force_login(lettore)
    risposta = client.get(reverse("reports:stato_rda") + "?area=tutti&formato=xlsx")
    ws = openpyxl.load_workbook(io.BytesIO(risposta.content))["Stato delle RDA"]
    totale = [r for r in ws.iter_rows(values_only=True) if r[0] == "Totale"][0]
    assert Decimal(str(totale[13])) == Decimal(dati["totale_importo"])


# --- Fatture (TC-18) ------------------------------------------------------------------


def test_fatture_tc18(registro, tmp_path, lettore):  # noqa: F811
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    rossi, bianchi = registro["rossi"], registro["bianchi"]
    da_prendere = esegui(rossi, "elenco_fatture", {"vista": "da_prendere"})
    # «Proposte a me» attivo di default: rossi vede solo la 13/2026.
    assert da_prendere["solo_proposte_a_me"] is True
    assert [r["numero"] for r in da_prendere["righe"]] == ["13/2026"]
    tutte = esegui(lettore, "elenco_fatture", {"vista": "da_prendere"})
    assert {r["numero"]: r["referente_proposto"] for r in tutte["righe"]} == {
        "FA-1/2026": "bianchi", "13/2026": "rossi", "76 In attesa di nota credito": "bianchi",
        "99": None,
    }  # fmt: skip
    # Lavorazione della 13/2026 fino al commento per PAC (TC-18).
    f13 = m.Fattura.objects.get(numero="13/2026")
    fatture.prendi_in_carico([f13.pk], rossi, OGGI)
    fatture.assegna_contratto(fatture.QS_FATTURE.get(pk=f13.pk), registro["cs"])
    f13 = fatture.QS_FATTURE.get(pk=f13.pk)
    dati = esegui(lettore, "fattura", {"id": f13.pk})
    assert (dati["passo"], dati["in_carico_a"], dati["valore_base_proposto"]) == (
        "convalida", "rossi", "1679.83",
    )  # fmt: skip
    fatture.convalida(f13, "convalidabile", data=OGGI)
    fatture.aggiorna_importi(
        f13,
        Decimal("1504.17"),
        Decimal("173.66"),
        Decimal("2.00"),
        competenza=(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)),
    )
    for tipo, numero in (("ODA_RDC", "RDC-0001"), ("MAP", "MAP-0001")):
        fatture.registra_documento(fatture.QS_FATTURE.get(pk=f13.pk), tipo, numero, OGGI)
    m.DocumentoEsecuzione.objects.filter(fattura=f13).update(data_rilascio=OGGI)
    dati = esegui(lettore, "fattura", {"id": f13.pk})
    assert dati["commento_pac"] == PAC_ATTESO
    assert dati["indicazioni_validazione"] == (
        "Valore base da prelevare € 1.504,17. COGE: 600010, CDC: C0001, WBS: WBS-TEST-01"
    )
    assert dati["passo"] == "trasferimento" and dati["anomalie"] == []
    mie = esegui(rossi, "elenco_fatture", {"vista": "mie"})
    assert [r["numero"] for r in mie["righe"]] == ["13/2026"]
    # Esecuzione del contratto: fatturato sui valori base.
    esec = esegui(lettore, "esecuzione", {"contratto_id": registro["cs"].pk})
    assert esec["fatturato"] == "2504.17"
    cerca = esegui(lettore, "cerca", {"testo": "RDC-0001", "tipo": "fatture"})
    assert [x["numero"] for x in cerca["fatture"]] == ["13/2026"]
    assert (
        esegui(bianchi, "elenco_fatture", {"vista": "da_prendere", "proposte_a_me": False})[
            "totale"
        ]
        == 3
    )


# --- Esecuzione e viste (TC-16) -------------------------------------------------------


@pytest.fixture
def f1():
    c = f.contratto(
        fabbisogno=f.fabbisogno("Forniture di prova"), una_tantum=True,
        data_inizio=D(2026, 3, 2), durata_mesi=1, numero_contratto="5800000016",
    )  # fmt: skip
    f.voce(c, importo_fisso=Decimal("10000.00"), massimale_variabile=Decimal("2000.00"))
    for numero, data, valore in (("FA-1", D(2026, 3, 15), 4000), ("FA-2", D(2026, 4, 20), 5000)):
        m.Fattura.objects.create(
            contratto=c,
            numero=numero,
            data=data,
            importo_documento=valore,
            valore_base=valore,
            competenza_dal=data,
            competenza_al=data,
        )
    return c


def test_esecuzione_e_viste_tc16(f1, lettore):
    dati = esegui(lettore, "esecuzione", {"contratto_id": f1.pk}, D(2026, 4, 25))
    assert (dati["fatturato"], dati["residuo_fisso"], dati["residuo_massimo"]) == (
        "9000.00", "1000.00", "3000.00",
    )  # fmt: skip
    assert (dati["avanzamento_pct"], dati["da_chiudere"]) == (90, "Attestazione mancante")
    chiudere = esegui(lettore, "contratti_da_chiudere", {"cluster": ["tutti"]}, D(2026, 4, 25))
    assert chiudere["per_motivo"] == {"Attestazione mancante": 1}
    m.Fattura.objects.create(
        contratto=f1, numero="FA-3", data=D(2026, 5, 5), importo_documento=3500,
        valore_base=3500, competenza_dal=D(2026, 5, 5), competenza_al=D(2026, 5, 5),
    )  # fmt: skip
    anomalie = esegui(lettore, "anomalie_esecuzione", {"cluster": ["tutti"]}, D(2026, 5, 6))
    assert anomalie["conteggi"] == {"FATTURATO_OLTRE_MASSIMO": 1}
    cruscotto = esegui(lettore, "cruscotto_acquisti", {"cluster": ["tutti"]}, D(2026, 5, 6))
    assert [r["contratto"]["id"] for r in cruscotto["contratti_da_chiudere"]] == [f1.pk]
    dettaglio = esegui(lettore, "contratto", {"id": f1.pk})
    assert dettaglio["una_tantum"] is True and dettaglio["tipo_acquisto"] == "servizio"


def test_riferimenti_e_tools_list(tabelle_sap, lettore):  # noqa: F811
    dati = esegui(lettore, "riferimenti")
    predefiniti = [r["codice"] for r in dati["richiedenti_sap"] if r["predefinito"]]
    assert predefiniti == [m.RichiedenteSAP.predefinito_attivo().codice]
    assert [s["codice"] for s in dati["scopi_rda"]] == ["rinnovo", "primo_acquisto", "aggiuntivo"]
    risposta, _ = protocollo.gestisci(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, Contesto(lettore, OGGI)
    )
    nomi = {t["name"] for t in risposta["result"]["tools"]}
    nuovi = {
        "rda", "elenco_rda", "fattura", "elenco_fatture", "esecuzione",
        "cruscotto_acquisti", "contratti_da_chiudere", "anomalie_esecuzione",
    }  # fmt: skip
    assert nuovi <= nomi
    assert errore(lettore, "rda", {"id": 999999}).startswith("Nessun RDA con id 999999")
