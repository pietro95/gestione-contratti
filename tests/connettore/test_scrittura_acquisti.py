"""F12.2: scrittura del processo d'acquisto dal connettore (SPEC_MCP Rev08 §11.3, §11.5).

Equivalenza con l'interfaccia per ogni tool (stessi dati → stesso stato del database), effetti
nell'anteprima, operazioni su più fatture (D15), permessi; TC-15, TC-16 e TC-18 ricostruiti
via MCP. Dati di fantasia.
"""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.roles import ADMIN, EDITOR
from connettore import protocollo
from connettore.models import OperazioneMCP
from connettore.strumenti import Contesto
from contratti import acquisti, fatture, servizi
from contratti import forms_rda as fr
from contratti import models as m
from tests import factories as f
from tests.connettore.test_scrittura import conteggi
from tests.connettore.test_scrittura_equivalenza import DOMINIO, equivalente
from tests.engine.test_tc17_scheda_sap import TESTO_ATTESO
from tests.engine.test_tc18_fatture import PAC_ATTESO
from tests.test_acquisti import BASE, licenze_cad, tabelle_sap  # noqa: F401

pytestmark = pytest.mark.django_db
D = datetime.date
DOMINIO_ACQUISTI = [
    *DOMINIO,
    m.RichiestaAcquisto,
    m.PosizioneRDA,
    m.EventoRDA,
    m.Fattura,
    m.DocumentoEsecuzione,
]


def oggi() -> datetime.date:
    """Le viste e i servizi usano la data di oggi: anche il connettore, nei test."""
    return timezone.localdate()


def ctx(utente):
    return Contesto(utente, oggi(), scrittura=True, client_id="prova")


def risultato(utente, nome, argomenti):
    messaggio = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": nome, "arguments": argomenti},
    }
    return protocollo.gestisci(messaggio, ctx(utente))[0]["result"]


def ok(utente, nome, argomenti) -> dict:
    r = risultato(utente, nome, argomenti)
    assert not r.get("isError"), r
    return r["structuredContent"]


def errore(utente, nome, argomenti) -> str:
    r = risultato(utente, nome, argomenti)
    assert r["isError"] is True, r
    return r["content"][0]["text"]


def conferma(utente, anteprima: dict) -> dict:
    return ok(utente, "conferma_operazione", {"id_operazione": anteprima["id_operazione"]})


def uguale(client, utente, web, nome, argomenti):
    return equivalente(client, utente, web, nome, argomenti, dominio=DOMINIO_ACQUISTI, oggi=oggi())


def post(valori: dict) -> dict:
    """Valori iniziali (modelli, Decimal, date) come li invia il browser."""
    dati = {}
    for chiave, v in valori.items():
        if v is None:
            dati[chiave] = ""
        elif hasattr(v, "pk"):
            dati[chiave] = v.pk
        elif isinstance(v, bool):
            if v:
                dati[chiave] = "on"
        elif isinstance(v, Decimal):
            dati[chiave] = str(v).replace(".", ",")  # campi localizzati: 1,000 = uno
        else:
            dati[chiave] = str(v)
    return dati


def formset(prefisso: str, righe: list[dict], iniziali: int = 0) -> dict:
    """Formset come lo invia il browser: le righe proposte dalla vista sono «iniziali»."""
    dati = {
        f"{prefisso}-TOTAL_FORMS": str(len(righe)),
        f"{prefisso}-INITIAL_FORMS": str(iniziali),
        f"{prefisso}-MIN_NUM_FORMS": "0",
        f"{prefisso}-MAX_NUM_FORMS": "1000",
    }
    for i, riga in enumerate(righe):
        dati |= {f"{prefisso}-{i}-{k}": v for k, v in post(riga).items()}
    return dati


@pytest.fixture
def admin(make_user):
    return make_user("amministratore", role=ADMIN)


# --- RDA ---------------------------------------------------------------------------------


@pytest.fixture
def rda_bozza(licenze_cad, editor):  # noqa: F811
    fab = licenze_cad[0]
    proposta = acquisti.proposta_richiesta(fab, oggi())
    return acquisti.crea_richiesta(proposta, editor)


def _post_richiesta(rda_o_iniziali, posizioni, iniziali: int, **extra) -> dict:
    valori = (
        {c: getattr(rda_o_iniziali, c) for c in fr.CAMPI_RICHIESTA}
        if isinstance(rda_o_iniziali, m.RichiestaAcquisto)
        else rda_o_iniziali
    )
    return {**post(valori), **formset("pos", posizioni, iniziali), **extra}


def test_crea_rda_con_i_valori_proposti(client, editor, licenze_cad):  # noqa: F811
    fab = licenze_cad[0]
    p = acquisti.proposta_richiesta(fab, oggi())
    iniziali = {
        "descrizione": p.descrizione, "intestazione": p.intestazione,
        "fornitore_proposto": p.fornitore_proposto, "richiedente": p.richiedente,
        "gruppo_acquisti": p.gruppo_acquisti, "percorso_file_server": p.percorso_file_server,
        "rup": p.rup, "cup": p.cup, "note_buyer": "", "allegati": "", "note": "",
    }  # fmt: skip
    posizioni = fr.iniziali_posizioni(p.posizioni)
    dati = _post_richiesta(iniziali, posizioni, len(posizioni), invia="1")
    esito = uguale(
        client, editor, lambda cl: cl.post(f"/rda/nuova/{fab.pk}/", dati),
        "crea_rda", {"fabbisogno_id": fab.pk, "invia": True},
    )  # fmt: skip
    rda = m.RichiestaAcquisto.objects.get()
    assert acquisti.fase(rda) == "inviata" and rda.referente_utente == editor
    assert esito["testo_richiesta"] == acquisti.testo_della_richiesta(rda)


def test_crea_rda_anteprima_con_fase_pratica_e_testo(editor, licenze_cad):  # noqa: F811
    fab, c1, _ = licenze_cad
    prima = conteggi()
    dati = ok(editor, "crea_rda", {
        "fabbisogno_id": fab.pk, "note_buyer": "Si allega preventivo", "invia": True,
        "posizioni": [{"descrizione_breve": "Licenze", "quantita": "2",
                       "importo_unitario": "549.50", "gruppo_merci": "GM-TEST01"}],
    })  # fmt: skip
    assert conteggi() == prima
    processo = dati["effetti"]["processo_acquisto"]
    assert processo["prima"]["pratiche"] == [
        {"tipo": "contratto", "id": c1.pk, "stato": "Non avviata", "data": None}
    ]
    assert processo["dopo"]["rda"][0]["id"] == "nuovo"
    assert processo["dopo"]["rda"][0]["fase"] == "inviata"
    assert processo["dopo"]["rda"][0]["importo"] == "1099.00"
    assert processo["dopo"]["pratiche"][0]["stato"] == "RDA richiesta"
    assert "rda" not in processo["prima"]
    esito = conferma(editor, dati)
    rda = m.RichiestaAcquisto.objects.get(pk=esito["oggetti"][0]["id"])
    assert rda.note_buyer == "Si allega preventivo" and rda.posizioni.count() == 1
    assert rda.history.first().history_change_reason.startswith("MCP crea_rda")


def test_crea_rda_errori_del_form(editor, licenze_cad):  # noqa: F811
    testo = errore(editor, "crea_rda", {
        "fabbisogno_id": licenze_cad[0].pk,
        "posizioni": [{"descrizione_breve": "Senza importo", "quantita": "1"}],
    })  # fmt: skip
    assert "posizioni[0].importo_unitario: Obbligatorio (anche 0)." in testo
    assert "sconosciuto" in errore(editor, "crea_rda", {
        "fabbisogno_id": licenze_cad[0].pk, "richiedente": "000000",
    })  # fmt: skip


def test_modifica_rda(client, editor, rda_bozza):
    posizioni = fr.iniziali_posizioni(rda_bozza.posizioni.order_by("numero"))
    posizioni[1]["importo_unitario"] = Decimal("750.00")
    nuova = {"descrizione_breve": "Formazione", "quantita": "1", "importo_unitario": "100,00",
             "natura": "OPEX"}  # fmt: skip
    rda_bozza.descrizione = "Descrizione cambiata"
    dati = _post_richiesta(rda_bozza, [*posizioni, nuova], len(posizioni))
    uguale(
        client, editor, lambda cl: cl.post(f"/rda/{rda_bozza.pk}/modifica/", dati),
        "modifica_rda",
        {"id": rda_bozza.pk, "descrizione": "Descrizione cambiata",
         "posizioni": [{"numero": 2, "importo_unitario": "750.00"},
                       {"descrizione_breve": "Formazione", "quantita": "1",
                        "importo_unitario": "100.00"}]},
    )  # fmt: skip
    assert rda_bozza.posizioni.count() == 3


def test_modifica_rda_inviata_e_correzione_diretta(editor, rda_bozza):
    acquisti.invia(rda_bozza, editor)
    dati = ok(editor, "modifica_rda", {"id": rda_bozza.pk, "rup": "Bianchi"})
    assert "correzione diretta" in dati["avvisi"][0]
    assert "non ha la posizione 9" in errore(
        editor, "modifica_rda", {"id": rda_bozza.pk, "posizioni": [{"numero": 9}]}
    )
    acquisti.annulla(rda_bozza, "non serve", editor)
    assert "annullata o chiusa" in errore(editor, "modifica_rda", {"id": rda_bozza.pk})


def test_invia_rimanda_annulla(client, editor, rda_bozza):
    uguale(client, editor, lambda cl: cl.post(f"/rda/{rda_bozza.pk}/invia/"),
           "invia_rda", {"id": rda_bozza.pk})  # fmt: skip
    uguale(
        client, editor,
        lambda cl: cl.post(f"/rda/{rda_bozza.pk}/rimanda/", {"nota": "Manca il preventivo"}),
        "rimanda_rda", {"id": rda_bozza.pk, "nota": "Manca il preventivo"},
    )  # fmt: skip
    uguale(
        client, editor,
        lambda cl: cl.post(f"/rda/{rda_bozza.pk}/annulla/", {"nota": "Non serve più"}),
        "annulla_rda", {"id": rda_bozza.pk, "motivo": "Non serve più"},
    )  # fmt: skip
    assert acquisti.fase(rda_bozza) == "annullata"
    assert "già annullata" in errore(editor, "annulla_rda", {"id": rda_bozza.pk, "motivo": "x"})


def test_dati_sap_e_contratti_proposti(client, editor, rda_bozza, licenze_cad):  # noqa: F811
    acquisti.invia(rda_bozza, editor)
    altro = f.contratto(fabbisogno=licenze_cad[0], numero_rda="5100000099")
    dati = {"numero_rda": "5100000099", "data_inserimento": "01/10/2026", "data_rilascio": ""}
    uguale(
        client, editor, lambda cl: cl.post(f"/rda/{rda_bozza.pk}/dati-sap/", dati),
        "dati_sap_rda",
        {"id": rda_bozza.pk, "numero_rda": "5100000099", "data_inserimento": "2026-10-01"},
    )  # fmt: skip
    rda_bozza.refresh_from_db()
    assert acquisti.fase(rda_bozza) == "inserita"
    anteprima = ok(editor, "dati_sap_rda", {"id": rda_bozza.pk, "data_rilascio": "2026-10-02"})
    assert f"id {altro.pk}" in anteprima["avvisi"][0]
    dopo = anteprima["effetti"]["processo_acquisto"]["dopo"]["rda"][0]
    assert dopo["fase"] == "rilasciata"


def test_registra_rda(client, editor, tabelle_sap):  # noqa: F811
    dati = {"cluster": f.cluster("IT").pk, "descrizione": "RDA storica", "numero_rda":
            "5100000016", "data_inserimento": "01/09/2026", "referente": "Rossi"}  # fmt: skip
    uguale(
        client, editor, lambda cl: cl.post("/rda/registra/", dati), "registra_rda",
        {"cluster": "IT", "descrizione": "RDA storica", "numero_rda": "5100000016",
         "data_inserimento": "2026-09-01", "referente": "Rossi"},
    )  # fmt: skip


def test_collega_rda(client, editor, licenze_cad):  # noqa: F811
    fab, c1, _ = licenze_cad
    rda = m.RichiestaAcquisto.objects.create(
        cluster=fab.cluster, descrizione="RDA a mano", numero_rda="5100000016",
        origine=m.RichiestaAcquisto.Origine.MANUALE,
    )  # fmt: skip
    uguale(
        client, editor,
        lambda cl: cl.post(f"/rda/{rda.pk}/pratica/", {"contratto": c1.pk, "fabbisogno": ""}),
        "collega_rda", {"id": rda.pk, "operazione": "pratica", "contratto_id": c1.pk},
    )  # fmt: skip
    nuovo = f.contratto(fabbisogno=fab, data_inizio=D(2027, 1, 1))
    uguale(
        client, editor, lambda cl: cl.post(f"/rda/{rda.pk}/collega/", {"contratto": nuovo.pk}),
        "collega_rda", {"id": rda.pk, "operazione": "contratto", "contratto_id": nuovo.pk},
    )  # fmt: skip
    uguale(
        client, editor,
        lambda cl: cl.post(f"/contratti/{nuovo.pk}/scollega-rda/"),
        "collega_rda",
        {"id": rda.pk, "operazione": "scollega_contratto", "contratto_id": nuovo.pk},
    )  # fmt: skip


def test_registra_contratto_da_rda(client, editor, rda_bozza, licenze_cad):  # noqa: F811
    c1 = licenze_cad[1]
    iniziali = acquisti.iniziali_contratto(rda_bozza, oggi())
    voci = [
        {"posizione": p.numero, "descrizione": p.descrizione_breve,
         "importo_fisso": p.importo - p.di_cui_variabile,
         "massimale_variabile": p.di_cui_variabile}
        for p in rda_bozza.posizioni.order_by("numero")
    ]  # fmt: skip
    extra = {"numero_contratto": "5800000099", "cig": "B000000001"}
    dati = {**post(iniziali), **post(extra), **formset("voci", voci, len(voci))}
    dati["voci-MIN_NUM_FORMS"] = "1"
    esito = uguale(
        client, editor, lambda cl: cl.post(f"/rda/{rda_bozza.pk}/contratto/", dati),
        "registra_contratto_da_rda", {"id": rda_bozza.pk, **extra},
    )  # fmt: skip
    nuovo = m.Contratto.objects.get(rda=rda_bozza)
    assert nuovo.predecessore == c1
    assert esito["esito"] == "eseguita"


def test_registra_contratto_da_rda_anteprima(editor, rda_bozza, licenze_cad):  # noqa: F811
    c1 = licenze_cad[1]
    anteprima = ok(editor, "registra_contratto_da_rda", {
        "id": rda_bozza.pk, "numero_contratto": "5800000099", "cig": "B000000001",
    })  # fmt: skip
    pratica = anteprima["effetti"]["processo_acquisto"]["dopo"]["pratiche"][0]
    assert pratica == {"tipo": "contratto", "id": c1.pk, "stato": "Contratto emesso",
                       "data": pratica["data"]}  # fmt: skip
    contratti = anteprima["effetti"]["processo_acquisto"]["dopo"]["contratti"]
    assert contratti[0]["id"] == "nuovo"
    assert contratti[0]["differenza_da_rda"] == "0.00"
    assert anteprima["effetti"]["fabbisogni"][0]["contratti"]


# --- Fatture ------------------------------------------------------------------------------


@pytest.fixture
def registro_fatture(make_user, editor):
    """Due contratti dello stesso fornitore (IT); fatture da prendere in carico."""
    rossi = make_user("rossi", role=EDITOR)
    fornitore = f.fornitore("Fornitore Prova A S.r.l.")
    fab = f.fabbisogno("Servizio A", referente_utente=rossi)
    c = f.contratto(fornitore=fornitore, fabbisogno=fab, data_inizio=D(2026, 1, 1),
                    durata_mesi=12)  # fmt: skip
    voce = f.voce(c, importo_fisso=Decimal("1200.00"))
    f.piano(voce, modalita="anticipata", periodicita="trimestrale")
    servizi.genera_scadenzario(voce)
    nuove = [
        m.Fattura.objects.create(
            fornitore=fornitore,
            numero=f"FA-{i}/2026",
            data=D(2026, 9, i),
            importo_documento=Decimal("300.00"),
        )  # fmt: skip
        for i in (1, 2, 3)
    ]
    return {"c": c, "voce": voce, "fatture": nuove, "rossi": rossi, "fornitore": fornitore}


def _in_carico(fattura, utente, contratto=None):
    fatture.prendi_in_carico([fattura.pk], utente)
    fattura = fatture.QS_FATTURE.get(pk=fattura.pk)
    if contratto is not None:
        fatture.assegna_contratto(fattura, contratto)
    return fatture.QS_FATTURE.get(pk=fattura.pk)


def test_registra_fattura(client, editor, registro_fatture):
    c, fornitore = registro_fatture["c"], registro_fatture["fornitore"]
    uguale(
        client, editor,
        lambda cl: cl.post("/fatture/nuova/", {"fornitore": fornitore.pk, "numero": "FB-1",
                                               "data": "01/10/2026",
                                               "importo_documento": "1.220,00"}),
        "registra_fattura",
        {"fornitore_id": fornitore.pk, "numero": "FB-1", "data": "2026-10-01",
         "importo_documento": "1220.00"},
    )  # fmt: skip
    uguale(
        client, editor,
        lambda cl: cl.post(f"/contratti/{c.pk}/fattura/", {"numero": "FB-2",
                                                           "data": "02/10/2026",
                                                           "importo_documento": "10"}),
        "registra_fattura",
        {"contratto_id": c.pk, "numero": "FB-2", "data": "2026-10-02",
         "importo_documento": "10"},
    )  # fmt: skip
    testo = errore(editor, "registra_fattura", {
        "fornitore_id": fornitore.pk, "numero": "FA-1/2026", "data": "2026-10-01",
        "importo_documento": "1",
    })  # fmt: skip
    assert "Fattura già registrata per questo fornitore." in testo


def test_prendi_in_carico_multipla(client, editor, registro_fatture):
    pks = [x.pk for x in registro_fatture["fatture"]]
    fatture.prendi_in_carico([pks[2]], registro_fatture["rossi"])
    uguale(
        client, editor,
        lambda cl: cl.post("/fatture/azione/", {"azione": "prendi", "fattura": pks}),
        "prendi_in_carico", {"fatture_ids": pks},
    )  # fmt: skip


def test_fuori_registro_multipla(client, editor, registro_fatture):
    pks = [x.pk for x in registro_fatture["fatture"][:2]]
    uguale(
        client, editor,
        lambda cl: cl.post("/fatture/azione/", {"azione": "fuori_registro", "fattura": pks}),
        "segna_fuori_registro", {"fatture_ids": pks},
    )  # fmt: skip
    uguale(
        client, editor,
        lambda cl: cl.post(f"/fatture/{pks[0]}/fuori-registro/", {"valore": "0"}),
        "segna_fuori_registro", {"fatture_ids": [pks[0]], "fuori_registro": False},
    )  # fmt: skip


def test_assegna_ai_referenti_proposti(client, admin, registro_fatture):
    client.force_login(admin)
    pks = [x.pk for x in registro_fatture["fatture"]]
    esito = uguale(
        client, admin,
        lambda cl: cl.post("/fatture/azione/", {"azione": "assegna_proposti", "fattura": pks}),
        "assegna_ai_referenti_proposti", {"fatture_ids": pks},
    )  # fmt: skip
    assert m.Fattura.objects.filter(referente=registro_fatture["rossi"]).count() == 3
    assert esito["esito"] == "eseguita"


def test_lascia_e_riassegna(client, admin, registro_fatture):
    client.force_login(admin)
    fa = _in_carico(registro_fatture["fatture"][0], registro_fatture["rossi"])
    uguale(client, admin, lambda cl: cl.post(f"/fatture/{fa.pk}/lascia/"),
           "lascia_fattura", {"id": fa.pk})  # fmt: skip
    rossi = registro_fatture["rossi"]
    uguale(
        client, admin, lambda cl: cl.post(f"/fatture/{fa.pk}/riassegna/", {"utente": rossi.pk}),
        "riassegna_fattura", {"id": fa.pk, "username": "rossi"},
    )  # fmt: skip
    assert "Utente sconosciuto o non attivo: nessuno." in errore(
        admin, "riassegna_fattura", {"id": fa.pk, "username": "nessuno"}
    )


def test_assegna_contratto_e_scollega(client, editor, registro_fatture):
    c = registro_fatture["c"]
    fa = _in_carico(registro_fatture["fatture"][0], editor)
    uguale(
        client, editor,
        lambda cl: cl.post(f"/fatture/{fa.pk}/contratto/", {"contratto": c.pk, "voce": ""}),
        "assegna_contratto_fattura", {"id": fa.pk, "contratto_id": c.pk},
    )  # fmt: skip
    anteprima = ok(editor, "assegna_contratto_fattura", {"id": fa.pk, "scollega": True})
    processo = anteprima["effetti"]["processo_acquisto"]
    assert processo["prima"]["fatture"][0]["passo"] == "convalida"
    assert processo["dopo"]["fatture"][0]["passo"] == "assegnazione"
    uguale(
        client, editor, lambda cl: cl.post(f"/fatture/{fa.pk}/contratto/", {"scollega": "1"}),
        "assegna_contratto_fattura", {"id": fa.pk, "scollega": True},
    )  # fmt: skip


def test_convalida_importi_documenti_trasferimento(client, editor, registro_fatture):
    c, voce = registro_fatture["c"], registro_fatture["voce"]
    fa = _in_carico(registro_fatture["fatture"][0], editor, c)
    uguale(
        client, editor,
        lambda cl: cl.post(f"/fatture/{fa.pk}/convalida/", {
            "esito_convalida": "in_attesa", "nota_convalida": "prove in campo",
            "bloccata_fino_al": "20/10/2026"}),
        "convalida_fattura",
        {"id": fa.pk, "esito_convalida": "in_attesa", "nota_convalida": "prove in campo",
         "bloccata_fino_al": "2026-10-20"},
    )  # fmt: skip
    rata = m.Rata.objects.filter(piano__voce=voce).order_by("data_fattura").first()
    uguale(
        client, editor,
        lambda cl: cl.post(f"/fatture/{fa.pk}/importi/", {
            "valore_base": "300,00", "oneri": "", "bollo": "", "voce": voce.pk,
            "rata": rata.pk}),
        "importi_fattura", {"id": fa.pk, "rata_id": rata.pk},
    )  # fmt: skip
    rata.refresh_from_db()
    assert rata.consuntivo and rata.numero_fattura == "FA-1/2026"
    uguale(
        client, editor,
        lambda cl: cl.post(f"/fatture/{fa.pk}/documento/", {
            "tipo": "ODA_RDC", "numero": "RDC-1", "data": "05/10/2026"}),
        "documento_fattura",
        {"id": fa.pk, "tipo": "ODA_RDC", "numero": "RDC-1", "data": "2026-10-05"},
    )  # fmt: skip
    data = oggi().strftime("%d/%m/%Y")
    uguale(
        client, editor, lambda cl: cl.post(f"/fatture/{fa.pk}/trasferimento/", {"data": data}),
        "trasferisci_fattura", {"id": fa.pk},
    )  # fmt: skip
    uguale(
        client, editor,
        lambda cl: cl.post(f"/fatture/{fa.pk}/trasferimento/", {"annulla": "1"}),
        "trasferisci_fattura", {"id": fa.pk, "annulla": True},
    )  # fmt: skip


def test_permessi_sulle_fatture(make_user, editor, registro_fatture):
    c = registro_fatture["c"]
    fa = _in_carico(registro_fatture["fatture"][0], registro_fatture["rossi"])
    # Senza contratto la lavora solo chi la ha in carico (o Admin e addetto).
    assert "non puoi modificare questa fattura" in errore(
        editor, "assegna_contratto_fattura", {"id": fa.pk, "contratto_id": c.pk}
    )
    assert "non puoi modificare questa fattura" in errore(
        editor, "convalida_fattura", {"id": fa.pk, "esito_convalida": "convalidabile"}
    )
    assert "non puoi modificare questa fattura" in errore(editor, "lascia_fattura", {"id": fa.pk})
    assert "non puoi modificare questa fattura" in errore(
        editor, "riassegna_fattura", {"id": fa.pk, "username": "redattore"}
    )
    assert "Solo l'Admin e l'addetto" in errore(
        editor, "assegna_ai_referenti_proposti", {"fatture_ids": [fa.pk]}
    )
    # Fattura abbinata a un contratto IT: un Editor TLC non la tocca, nemmeno fuori registro.
    fatture.assegna_contratto(fa, c)
    verdi = make_user("verdi", role=EDITOR)
    m.AssegnazioneCluster.objects.create(username="verdi", cluster=f.cluster("TLC"))
    testo = errore(verdi, "segna_fuori_registro", {"fatture_ids": [fa.pk]})
    assert "contratto di un cluster che non ti è assegnato" in testo
    assert "non puoi modificare" in errore(verdi, "trasferisci_fattura", {"id": fa.pk})


def test_piu_di_50_fatture(editor, registro_fatture):
    testo = errore(editor, "prendi_in_carico", {"fatture_ids": list(range(1, 52))})
    assert testo.endswith("«fatture_ids»: al massimo 50 elementi.")
    assert not OperazioneMCP.objects.exists()


def test_conferma_rifiutata_per_intero_se_una_fattura_cambia(editor, registro_fatture):
    pks = [x.pk for x in registro_fatture["fatture"]]
    anteprima = ok(editor, "prendi_in_carico", {"fatture_ids": pks})
    assert [r["esito"] for r in anteprima["esito_per_fattura"]] == ["applicata"] * 3
    fatture.prendi_in_carico([pks[1]], registro_fatture["rossi"])  # nel frattempo
    testo = errore(editor, "conferma_operazione", {"id_operazione": anteprima["id_operazione"]})
    assert "modificati dopo l'anteprima" in testo
    assert not m.Fattura.objects.filter(referente=editor).exists()


# --- TC-18 via MCP ------------------------------------------------------------------------


def test_tc18_via_mcp(make_user, editor, registro_fatture):
    """Presa in carico multipla con il rifiuto «già in carico a …», referente proposto,
    convalida bloccata, commento per PAC identico."""
    rossi = registro_fatture["rossi"]
    it = f.cluster("IT")
    conto = m.ContoCoge.objects.create(
        codice="600010", descrizione="Conto di prova", valido_dal=D(2020, 1, 1), cluster=it
    )
    wbs = m.WBS.objects.create(codice_wbs="WBS-TEST-01", descrizione="WBS di prova", cluster=it)
    studio = f.fornitore("Studio Prova", nome_breve="STUDIOP")
    cs = f.contratto(fornitore=studio, fabbisogno=f.fabbisogno("Consulenza S"))
    f.voce(cs, natura=m.Natura.CAPEX, conto=conto, centro_costo="C0001", wbs=wbs,
           importo_fisso=Decimal("5000.00"))  # fmt: skip
    f13 = m.Fattura.objects.create(fornitore=studio, numero="13/2026", data=D(2026, 9, 28),
                                   importo_documento=Decimal("1679.83"))  # fmt: skip
    fa1 = registro_fatture["fatture"][0]
    fatture.prendi_in_carico([fa1.pk], rossi)
    # Referente proposto per l'altra fattura dello stesso fornitore: rossi (lettura).
    fa2 = registro_fatture["fatture"][1]
    assert ok(editor, "fattura", {"id": fa2.pk})["referente_proposto"] == "rossi"
    anteprima = ok(editor, "prendi_in_carico", {"fatture_ids": [f13.pk, fa1.pk]})
    assert anteprima["esito_per_fattura"] == [
        {"id": f13.pk, "numero": "13/2026", "esito": "applicata"},
        {"id": fa1.pk, "numero": "FA-1/2026", "esito": "rifiutata",
         "motivo": "già in carico a rossi"},
    ]  # fmt: skip
    conferma(editor, anteprima)
    assert m.Fattura.objects.get(pk=fa1.pk).referente == rossi
    conferma(editor, ok(editor, "assegna_contratto_fattura", {"id": f13.pk, "contratto_id": cs.pk}))
    # Convalida bloccata: resta al passo «convalida» fino alla data.
    conferma(editor, ok(editor, "convalida_fattura", {
        "id": f13.pk, "esito_convalida": "in_attesa",
        "nota_convalida": "in attesa di prove di funzionamento in campo",
        "bloccata_fino_al": "2099-12-31",
    }))  # fmt: skip
    assert ok(editor, "fattura", {"id": f13.pk})["passo"] == "convalida"
    conferma(editor, ok(editor, "convalida_fattura", {
        "id": f13.pk, "esito_convalida": "convalidabile", "bloccata_fino_al": None,
    }))  # fmt: skip
    anteprima = ok(editor, "importi_fattura", {
        "id": f13.pk, "valore_base": "1504.17", "oneri": "173.66", "bollo": "2.00",
    })  # fmt: skip
    dopo = anteprima["effetti"]["processo_acquisto"]["dopo"]
    assert dopo["fatture"][0]["anomalie"] == []
    assert dopo["contratti"][0]["fatturato"] == "1504.17"
    conferma(editor, anteprima)
    conferma(editor, ok(editor, "documento_fattura",
                        {"id": f13.pk, "tipo": "ODA_RDC", "numero": "RDC-0001"}))  # fmt: skip
    anteprima = ok(editor, "documento_fattura", {"id": f13.pk, "tipo": "MAP", "numero": "MAP-0001"})
    assert anteprima["effetti"]["processo_acquisto"]["dopo"]["fatture"][0]["commento_pac"] == (
        PAC_ATTESO
    )
    assert anteprima["effetti"]["processo_acquisto"]["dopo"]["fatture"][0]["passo"] == (
        "trasferimento"
    )
    conferma(editor, anteprima)
    assert ok(editor, "fattura", {"id": f13.pk})["commento_pac"] == PAC_ATTESO


# --- Esecuzione e chiusura (TC-16) --------------------------------------------------------


@pytest.fixture
def una_tantum(editor):
    fornitore = f.fornitore("Fornitore Prova A S.r.l.")
    rda = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"), descrizione="Forniture di prova", numero_rda="5100000016",
        origine=m.RichiestaAcquisto.Origine.MANUALE, data_inserimento=D(2026, 2, 20),
        data_rilascio=D(2026, 2, 25),
    )  # fmt: skip
    m.PosizioneRDA.objects.create(rda=rda, numero=1, descrizione_breve="Hardware",
                                  quantita=Decimal("1"), importo_unitario=Decimal("12000.00"),
                                  di_cui_variabile=Decimal("2000.00"))  # fmt: skip
    c = f.contratto(fornitore=fornitore, data_inizio=D(2026, 3, 2), durata_mesi=1,
                    una_tantum=True, rda=rda)  # fmt: skip
    f.voce(c, importo_fisso=Decimal("10000.00"), massimale_variabile=Decimal("2000.00"))
    for numero, data, importo in (
        ("FA-1", D(2026, 3, 15), "4000"),
        ("FA-2", D(2026, 4, 20), "5000"),
    ):
        m.Fattura.objects.create(fornitore=fornitore, contratto=c, numero=numero, data=data,
                                 importo_documento=Decimal(importo),
                                 valore_base=Decimal(importo))  # fmt: skip
    return c


def test_documento_esecuzione_e_chiusura(client, editor, una_tantum):
    c = una_tantum
    anteprima = ok(editor, "documento_esecuzione", {
        "contratto_id": c.pk, "tipo": "ATTESTAZIONE", "data": "2026-04-28", "finale": True,
    })  # fmt: skip
    processo = anteprima["effetti"]["processo_acquisto"]
    assert processo["prima"]["contratti"][0]["fatturato"] == "9000.00"
    assert processo["prima"]["contratti"][0]["residuo_fisso"] == "1000.00"
    assert processo["dopo"]["contratti"][0]["da_chiudere"] is not None
    uguale(
        client, editor,
        lambda cl: cl.post(f"/contratti/{c.pk}/documento/", {
            "tipo": "ATTESTAZIONE", "numero": "", "data": "28/04/2026", "importo": "",
            "voce": "", "finale": "on", "note": ""}),
        "documento_esecuzione",
        {"contratto_id": c.pk, "tipo": "ATTESTAZIONE", "data": "2026-04-28", "finale": True},
    )  # fmt: skip
    anteprima = ok(editor, "chiudi_contratto", {"contratto_id": c.pk})
    processo = anteprima["effetti"]["processo_acquisto"]
    assert processo["prima"]["contratti"][0]["fase_rda"] == "In esecuzione"
    assert processo["dopo"]["contratti"][0]["fase_rda"] == "Chiusa"
    assert processo["dopo"]["rda"][0]["fase"] == "chiusa"
    uguale(client, editor, lambda cl: cl.post(f"/contratti/{c.pk}/chiudi/"),
           "chiudi_contratto", {"contratto_id": c.pk})  # fmt: skip
    assert "chiuso: prima si annulla" in errore(editor, "documento_esecuzione", {
        "contratto_id": c.pk, "tipo": "DDT", "data": "2026-05-01",
    })  # fmt: skip
    uguale(client, editor, lambda cl: cl.post(f"/contratti/{c.pk}/chiudi/", {"annulla": "1"}),
           "annulla_chiusura", {"contratto_id": c.pk})  # fmt: skip


def test_tc15_fasi_via_mcp(editor, rda_bozza):
    """TC-15: bozza → inviata → da correggere → inviata → inserita → rilasciata."""
    fasi = []
    for nome, argomenti in (
        ("invia_rda", {}),
        ("rimanda_rda", {"nota": "Manca il preventivo"}),
        ("invia_rda", {}),
        ("dati_sap_rda", {"numero_rda": "5100000001"}),
        ("dati_sap_rda", {"data_rilascio": oggi().isoformat()}),
    ):
        conferma(editor, ok(editor, nome, {"id": rda_bozza.pk, **argomenti}))
        fasi.append(ok(editor, "rda", {"id": rda_bozza.pk})["fase"])
    assert fasi == ["inviata", "da_correggere", "inviata", "inserita", "rilasciata"]
    assert ok(editor, "rda", {"id": rda_bozza.pk})["pratica"]["stato"]["stato"] == ("RDA approvata")


def test_tc17_testo_della_richiesta_via_mcp(editor, tabelle_sap):  # noqa: F811
    """Il testo della richiesta creata via MCP è quello di TC-17."""
    fornitore, conti = tabelle_sap
    fab = f.fabbisogno("Licenze CAD")
    m.RichiedenteSAP.objects.filter(codice="999901").update(predefinito=True)
    anteprima = ok(editor, "crea_rda", {
        "fabbisogno_id": fab.pk,
        "intestazione": "SWPROVA - Rinnovo licenza CAD (2 postazioni)",
        "descrizione": "Rinnovo licenza CAD (2 postazioni)",
        "fornitore_proposto": fornitore.pk, "richiedente": "999901", "gruppo_acquisti": "G01",
        "note_buyer": "Si allega preventivo",
        "allegati": "preventivo nella cartella del file server",
        "percorso_file_server":
            f"{BASE}/2026/2026_09_29_SWPROVA_Rinnovo_licenza_CAD_2_postazioni",
        "posizioni": [
            {"descrizione_breve": "SWPROVA - Rinnovo licenza CAD (2 postazioni)",
             "gruppo_merci": "GM-TEST01", "quantita": "2", "importo_unitario": "549.50",
             "conto": conti["600001"].pk, "centro_costo": "C0001"},
            {"descrizione_breve": "Supporto installazione", "gruppo_merci": "GM-TEST02",
             "quantita": "2.5", "importo_unitario": "99.99", "conto": conti["600002"].pk,
             "centro_costo": "C0001"},
        ],
    })  # fmt: skip
    esito = conferma(editor, anteprima)
    assert esito["testo_richiesta"] == TESTO_ATTESO
    quantita = [c for c in anteprima["modifiche"] if c["oggetto"] == "posizione della RDA"][1][
        "campi"
    ]["quantita"]
    assert quantita == "2.5"  # quantità, non importo: niente arrotondamento ai centesimi


def test_editor_di_un_altro_cluster(make_user, rda_bozza, una_tantum):
    verdi = make_user("verdi", role=EDITOR)
    m.AssegnazioneCluster.objects.create(username="verdi", cluster=f.cluster("TLC"))
    for nome, argomenti in (
        ("modifica_rda", {"id": rda_bozza.pk, "rup": "X"}),
        ("invia_rda", {"id": rda_bozza.pk}),
        ("chiudi_contratto", {"contratto_id": una_tantum.pk}),
        ("documento_esecuzione", {"contratto_id": una_tantum.pk, "tipo": "DDT",
                                  "data": "2026-05-01"}),
    ):  # fmt: skip
        assert "cluster che non puoi modificare" in errore(verdi, nome, argomenti)
    assert "Scegli un'opzione valida" in errore(verdi, "registra_rda", {
        "cluster": "IT", "descrizione": "X", "numero_rda": "5100000001",
    })  # fmt: skip


@pytest.mark.parametrize(
    ("nome", "argomenti"),
    [
        ("modifica_rda", lambda d: {"id": d["rda"].pk, "posizioni": [
            {"descrizione_breve": "Nuova", "quantita": "1", "importo_unitario": "10.00"}]}),
        ("invia_rda", lambda d: {"id": d["rda"].pk}),
        ("dati_sap_rda", lambda d: {"id": d["rda"].pk, "numero_rda": "5100000001"}),
        ("registra_contratto_da_rda", lambda d: {"id": d["rda"].pk, "cig": "B000000001",
                                                 "numero_contratto": "5800000001"}),
        ("prendi_in_carico", lambda d: {"fatture_ids": [x.pk for x in d["fatture"]]}),
        ("registra_fattura", lambda d: {"contratto_id": d["c"].pk, "numero": "X-1",
                                        "data": "2026-10-01", "importo_documento": "5"}),
        ("chiudi_contratto", lambda d: {"contratto_id": d["c"].pk}),
    ],
)  # fmt: skip
def test_l_anteprima_non_scrive_niente(editor, rda_bozza, registro_fatture, nome, argomenti):
    prima = conteggi()
    dati = ok(editor, nome, argomenti({"rda": rda_bozza, **registro_fatture}))
    assert conteggi() == prima
    assert dati["id_operazione"] and dati["modifiche"]
    assert dati["effetti"]["processo_acquisto"]["dopo"]


def test_con_l_utente_postgresql_del_container_mcp(editor, rda_bozza, registro_fatture):
    """I privilegi di ``ruolo_db_mcp`` bastano a tutto il processo (anteprime e conferme)."""
    from django.core.management import call_command
    from django.db import connection

    from tests.connettore.test_ruolo_db import RUOLO, URL

    call_command("ruolo_db_mcp", url=URL)
    c, fa = registro_fatture["c"], registro_fatture["fatture"][0]
    passi = [
        ("invia_rda", {"id": rda_bozza.pk}),
        ("dati_sap_rda", {"id": rda_bozza.pk, "numero_rda": "5100000001"}),
        ("registra_contratto_da_rda", {"id": rda_bozza.pk, "cig": "B000000001",
                                       "numero_contratto": "5800000001"}),
        ("registra_fattura", {"contratto_id": c.pk, "numero": "X-1", "data": "2026-10-01",
                              "importo_documento": "5"}),
        ("prendi_in_carico", {"fatture_ids": [fa.pk]}),
        ("assegna_contratto_fattura", {"id": fa.pk, "contratto_id": c.pk}),
        ("convalida_fattura", {"id": fa.pk, "esito_convalida": "convalidabile"}),
        ("importi_fattura", {"id": fa.pk}),
        ("documento_fattura", {"id": fa.pk, "tipo": "ODA_RDC", "numero": "RDC-1"}),
        ("trasferisci_fattura", {"id": fa.pk}),
        ("documento_esecuzione", {"contratto_id": c.pk, "tipo": "DDT", "data": "2026-10-01"}),
        ("chiudi_contratto", {"contratto_id": c.pk}),
    ]  # fmt: skip
    with connection.cursor() as cursore:
        cursore.execute(f'SET ROLE "{RUOLO}"')
    try:
        for nome, argomenti in passi:
            conferma(editor, ok(editor, nome, argomenti))
    finally:
        with connection.cursor() as cursore:
            cursore.execute("RESET ROLE")
    assert m.Fattura.objects.get(pk=fa.pk).data_trasferimento is not None
