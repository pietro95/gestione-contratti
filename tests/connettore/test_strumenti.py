"""Tool di lettura del connettore (SPEC_MCP §5): stessi dati di selettori e viste."""

import datetime
from decimal import Decimal

import pytest

from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import models as m
from contratti import selettori
from tests import factories as f
from tests.connettore.conftest import chiama

pytestmark = pytest.mark.django_db

OGGI = datetime.date(2026, 10, 5)


def esegui(utente, nome, argomenti=None):
    risposta, esito = protocollo.gestisci(chiama(nome, argomenti), Contesto(utente, OGGI))
    return risposta["result"], esito


def assegna(utente, codice):
    m.AssegnazioneCluster.objects.create(username=utente.username, cluster=f.cluster(codice))


@pytest.fixture
def dati():
    """Un contratto IT scaduto senza rinnovo (rosso) e uno TLC in avvicinamento (giallo)."""
    it = f.contratto(
        fabbisogno=f.fabbisogno("Licenze gestionale di prova", area="IT"),
        data_inizio=datetime.date(2025, 1, 1),
        durata_mesi=12,
        numero_contratto="4600000001",
    )
    f.voce(it, importo_fisso=Decimal("1234.50"))
    tlc = f.contratto(
        fabbisogno=f.fabbisogno("Connettività sedi di prova", area="TLC"),
        fornitore=f.fornitore("Operatore Esempio S.p.A."),
        data_inizio=datetime.date(2026, 1, 1),
        durata_mesi=12,
    )
    return it, tlc


def test_riferimenti(utente_reader, dati):
    assegna(utente_reader, "IT")
    risultato, _ = esegui(utente_reader, "riferimenti")
    dati_ = risultato["structuredContent"]
    propri = {c["codice"]: c["proprio"] for c in dati_["cluster"]}
    assert propri["IT"] is True
    assert not any(v for k, v in propri.items() if k != "IT")
    assert dati_["cluster_propri_definiti"] is True
    assert dati_["alla_data"] == "2026-10-05"
    procedura = next(p for p in dati_["procedure"] if p["codice"] == "affidamento_diretto")
    assert isinstance(procedura["lead_time_mesi"], int)
    for soglia in dati_["soglie"]:
        assert isinstance(soglia["importo"], str)
        assert soglia["importo"].count(".") == 1 and len(soglia["importo"].split(".")[1]) == 2


def test_cerca_come_la_ricerca_web(utente_reader, dati):
    it, _ = dati
    risultato, esito = esegui(utente_reader, "cerca", {"testo": "4600000001"})
    trovati = risultato["structuredContent"]["contratti"]
    attesi = selettori.cerca("4600000001", OGGI)["contratti"]
    assert [c["id"] for c in trovati] == [r.contratto.pk for r in attesi] == [it.pk]
    assert trovati[0]["link"] == f"https://contratti.esempio.test/contratti/{it.pk}/"
    assert trovati[0]["data_fine"] == "2025-12-31"
    assert trovati[0]["stato"] == "scaduto"
    assert esito.elementi == 1
    # Il testo è anche in «content», per i client che non leggono structuredContent.
    assert '"4600000001"' in risultato["content"][0]["text"]


def test_cerca_per_tipo_e_senza_referente(utente_reader, dati):
    risultato, _ = esegui(utente_reader, "cerca", {"testo": "di prova", "tipo": "fabbisogni"})
    dati_ = risultato["structuredContent"]
    assert set(dati_) >= {"fabbisogni"} and "contratti" not in dati_
    assert all("referente" not in fb for fb in dati_["fabbisogni"])


@pytest.mark.parametrize(
    ("argomenti", "messaggio"),
    [
        ({}, "manca l'argomento obbligatorio «testo»"),
        ({"testo": "x"}, "almeno 2 caratteri"),
        ({"testo": "abc", "altro": 1}, "argomento sconosciuto «altro»"),
        ({"testo": "abc", "tipo": "rate"}, "valore non ammesso"),
    ],
)
def test_argomenti_non_validi_come_errore_del_tool(utente_reader, argomenti, messaggio):
    risultato, esito = esegui(utente_reader, "cerca", argomenti)
    assert risultato["isError"] is True
    assert messaggio in risultato["content"][0]["text"]
    assert esito.esito == "errore_tool"


def test_scadenze_di_default_i_cluster_propri(utente_reader, dati):
    it, tlc = dati
    assegna(utente_reader, "IT")
    righe = esegui(utente_reader, "scadenze")[0]["structuredContent"]["righe"]
    assert [(r["id"], r["alert"]) for r in righe] == [(it.pk, "rosso")]
    tutti = esegui(utente_reader, "scadenze", {"cluster": ["tutti"]})[0]["structuredContent"]
    assert {r["id"]: r["alert"] for r in tutti["righe"]} == {it.pk: "rosso", tlc.pk: "giallo"}
    assert tutti["filtri"]["cluster"] == "tutti"


def test_scadenze_uguali_al_cruscotto(utente_reader, dati):
    gruppi = selettori.cruscotto(OGGI, {"area": [], "sottocluster": ""})
    attese = [r.contratto.pk for colore in gruppi for r in gruppi[colore]]
    righe = esegui(utente_reader, "scadenze", {"cluster": ["tutti"]})[0]["structuredContent"]
    assert [r["id"] for r in righe["righe"]] == attese


def test_scadenze_filtri_alert_ed_entro(utente_reader, dati):
    it, tlc = dati
    gialli = esegui(utente_reader, "scadenze", {"cluster": ["tutti"], "alert": ["giallo"]})
    assert [r["id"] for r in gialli[0]["structuredContent"]["righe"]] == [tlc.pk]
    # Entro una data prima della data limite del TLC: resta solo l'IT.
    entro = esegui(utente_reader, "scadenze", {"cluster": ["tutti"], "entro": "2026-01-01"})
    assert [r["id"] for r in entro[0]["structuredContent"]["righe"]] == [it.pk]


def test_scadenze_paginazione(utente_reader, dati):
    prima = esegui(utente_reader, "scadenze", {"cluster": ["tutti"], "limite": 1})[0]
    p1 = prima["structuredContent"]
    assert (len(p1["righe"]), p1["totale"], p1["troncato"]) == (1, 2, True)
    seconda = esegui(
        utente_reader,
        "scadenze",
        {"cluster": ["tutti"], "limite": 1, "cursore": p1["cursore_successivo"]},
    )[0]["structuredContent"]
    assert seconda["troncato"] is False
    assert seconda["righe"][0]["id"] != p1["righe"][0]["id"]


@pytest.mark.parametrize(
    ("argomenti", "messaggio"),
    [
        ({"cluster": ["XX"]}, "Cluster sconosciuti: XX"),
        ({"entro": "31/12/2026"}, "AAAA-MM-GG"),
        ({"cursore": "abc"}, "«cursore» non valido"),
        ({"limite": 1000}, "al massimo 100"),
    ],
)
def test_scadenze_errori(utente_reader, dati, argomenti, messaggio):
    risultato, _ = esegui(utente_reader, "scadenze", argomenti)
    assert risultato["isError"] is True
    assert messaggio in risultato["content"][0]["text"]
