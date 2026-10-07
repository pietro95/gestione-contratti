"""F11.2: richiesta di RDA dal fabbisogno, scheda SAP, dati SAP, collegamenti, contratto dalla
RDA. Permessi: Reader 403, Editor solo nei propri cluster."""

import datetime
import html
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounts.roles import EDITOR
from contratti import acquisti
from contratti import models as m
from contratti.engine.acquisti import Fase

from .. import factories as f
from ..engine.test_tc17_scheda_sap import TESTO_ATTESO
from .conftest import PASSWORD

pytestmark = pytest.mark.django_db
D = datetime.date
BASE = "smb://nas.esempio.local/Share/ICTDINN/00_IT/RDA_Ordini"


@pytest.fixture
def sap():
    m.RichiedenteSAP.objects.create(
        codice="999901", descrizione="Ufficio di prova", predefinito=True
    )
    m.GruppoAcquisti.objects.create(codice="G01", predefinito=True)
    m.GruppoMerci.objects.create(codice="GM-TEST01", predefinito=True)
    m.GruppoMerci.objects.create(codice="GM-TEST02")
    it = f.cluster("IT")
    it.cartella_rda = BASE
    it.save()
    fornitore = f.fornitore("Software Prova S.r.l.", nome_breve="SWPROVA")
    conti = {
        c: m.ContoCoge.objects.create(
            codice=c, descrizione="Conto di prova", valido_dal=D(2020, 1, 1), cluster=it
        )
        for c in ("600001", "600002")
    }
    return fornitore, conti


@pytest.fixture
def rinnovo(sap):
    """Fabbisogno con un contratto annuale in scadenza (voce con piano anticipato annuale)."""
    fornitore, conti = sap
    fab = f.fabbisogno("Licenze CAD di prova", decisione="rinnovare")
    c1 = f.contratto(fabbisogno=fab, fornitore=fornitore, rup="Rossi")
    voce = f.voce(c1, descrizione="Canone licenze", conto=conti["600001"], centro_costo="C0001")
    f.piano(voce, modalita="anticipata", periodicita="annuale")
    return fab, c1


def _pos(i, **campi):
    return {f"pos-{i}-{k}": v for k, v in campi.items()}


def _post_richiesta(client, url, posizioni, **campi):
    dati = {
        "pos-TOTAL_FORMS": str(len(posizioni)),
        "pos-INITIAL_FORMS": "0",
        "descrizione": "Licenze CAD di prova",
        "intestazione": "SWPROVA - Licenze CAD di prova",
        "richiedente": m.RichiedenteSAP.objects.get(codice="999901").pk,
        "gruppo_acquisti": m.GruppoAcquisti.objects.get(codice="G01").pk,
    }
    for i, p in enumerate(posizioni):
        dati |= _pos(i, **({"natura": "OPEX", "quantita": "1"} | p))
    return client.post(url, dati | campi)


# --- Permessi -------------------------------------------------------------------------------


def _viste_di_modifica(rda, c):
    return [
        ("get", reverse("contratti:rda_nuova", args=[c.fabbisogno.pk])),
        ("post", reverse("contratti:rda_nuova", args=[c.fabbisogno.pk])),
        ("get", reverse("contratti:rda_registra")),
        ("post", reverse("contratti:rda_registra")),
        ("get", reverse("contratti:rda_modifica", args=[rda.pk])),
        ("post", reverse("contratti:rda_modifica", args=[rda.pk])),
        ("post", reverse("contratti:rda_invia", args=[rda.pk])),
        ("post", reverse("contratti:rda_rimanda", args=[rda.pk])),
        ("post", reverse("contratti:rda_annulla", args=[rda.pk])),
        ("post", reverse("contratti:rda_dati_sap", args=[rda.pk])),
        ("post", reverse("contratti:rda_collega_pratica", args=[rda.pk])),
        ("post", reverse("contratti:rda_collega_contratto", args=[rda.pk])),
        ("get", reverse("contratti:rda_contratto", args=[rda.pk])),
        ("post", reverse("contratti:rda_contratto", args=[rda.pk])),
        ("post", reverse("contratti:contratto_collega_rda", args=[c.pk])),
        ("post", reverse("contratti:contratto_scollega_rda", args=[c.pk])),
    ]


@pytest.fixture
def una_rda(rinnovo, make_user):
    _, c1 = rinnovo
    autore = make_user("autore_rda", role=EDITOR)
    rda = acquisti.crea_richiesta(acquisti.proposta_richiesta(c1.fabbisogno), autore)
    return rda, c1


def test_reader_riceve_403_e_legge(reader, una_rda):
    rda, c1 = una_rda
    for metodo, url in _viste_di_modifica(rda, c1):
        assert getattr(reader, metodo)(url).status_code == 403, (metodo, url)
    assert reader.get(reverse("contratti:rda_elenco")).status_code == 200
    pagina = reader.get(reverse("contratti:rda", args=[rda.pk])).content.decode()
    assert "Copia testo della richiesta" in pagina and "Invia all&#x27;addetto" not in pagina
    assert acquisti.fase(rda) == Fase.BOZZA


def test_editor_di_un_altro_cluster_riceve_403(una_rda, make_user):
    rda, c1 = una_rda
    tlc = f.cluster("TLC")
    make_user("editor_tlc", role=EDITOR)
    m.AssegnazioneCluster.objects.create(username="editor_tlc", cluster=tlc)
    client = Client()
    client.login(username="editor_tlc", password=PASSWORD)
    for metodo, url in _viste_di_modifica(rda, c1):
        if url == reverse("contratti:rda_registra"):
            continue  # la pagina si apre: il cluster si sceglie tra i propri
        assert getattr(client, metodo)(url).status_code == 403, (metodo, url)


# --- Flusso: richiesta → invio → rimando → invio → dati SAP → contratto --------------------------


def test_flusso_completo(editor, rinnovo):
    fab, c1 = rinnovo
    url = reverse("contratti:rda_nuova", args=[fab.pk])
    pagina = editor.get(url)
    assert pagina.status_code == 200
    proposta = pagina.context["proposta"]
    assert proposta.scopo == "rinnovo" and proposta.contratto_in_scadenza == c1
    assert pagina.context["form"].initial["intestazione"] == "SWPROVA - Licenze CAD di prova"
    risposta = _post_richiesta(
        editor,
        url,
        [{"descrizione_breve": "SWPROVA - Licenze CAD di prova", "importo_unitario": "1.000,00",
          "gruppo_merci": m.GruppoMerci.objects.get(codice="GM-TEST01").pk,
          "conto": m.ContoCoge.objects.get(codice="600001").pk, "centro_costo": "C0001"}],
        contratto=str(c1.pk),
    )  # fmt: skip
    rda = m.RichiestaAcquisto.objects.get()
    assert risposta.status_code == 302 and risposta.url == reverse("contratti:rda", args=[rda.pk])
    assert (rda.scopo, rda.contratto_in_scadenza, rda.referente_utente.username) == (
        "rinnovo", c1, "u_editor",
    )  # fmt: skip
    assert acquisti.fase(rda) == Fase.BOZZA

    editor.post(reverse("contratti:rda_invia", args=[rda.pk]))
    assert acquisti.fase(rda) == Fase.INVIATA
    assert acquisti.stato_pratica(c1) == "rda_richiesta"
    editor.post(reverse("contratti:rda_rimanda", args=[rda.pk]), {"nota": "Manca il preventivo"})
    assert acquisti.fase(rda) == Fase.DA_CORREGGERE
    assert (
        "Manca il preventivo"
        in editor.get(reverse("contratti:rda", args=[rda.pk])).content.decode()
    )

    # Correzione del referente e nuovo invio dal form di modifica.
    pos = rda.posizioni.get()
    modifica = reverse("contratti:rda_modifica", args=[rda.pk])
    risposta = _post_richiesta(
        editor,
        modifica,
        [
            {
                "pk": pos.pk,
                "descrizione_breve": pos.descrizione_breve,
                "importo_unitario": "1100",
                "conto": pos.conto_id,
                "centro_costo": pos.centro_costo,
            }
        ],
        allegati="preventivo nella cartella",
        invia="1",
    )
    assert risposta.status_code == 302
    rda.refresh_from_db()
    assert rda.allegati == "preventivo nella cartella"
    assert rda.posizioni.get().importo_unitario == Decimal("1100.00")
    assert acquisti.fase(rda) == Fase.INVIATA

    editor.post(
        reverse("contratti:rda_dati_sap", args=[rda.pk]),
        {"numero_rda": "5100000001", "data_inserimento": "15/06/2026", "data_rilascio": ""},
    )
    rda.refresh_from_db()
    assert acquisti.fase(rda) == Fase.INSERITA
    assert acquisti.stato_pratica(c1) == "rda_predisposta"
    editor.post(
        reverse("contratti:rda_dati_sap", args=[rda.pk]),
        {
            "numero_rda": "5100000001",
            "data_inserimento": "15/06/2026",
            "data_rilascio": "01/07/2026",
        },
    )
    rda.refresh_from_db()
    assert acquisti.fase(rda) == Fase.RILASCIATA

    # Contratto dalla RDA: rinnovo di C1, voci dalle posizioni, piano del predecessore.
    url_c = reverse("contratti:rda_contratto", args=[rda.pk])
    pagina = editor.get(url_c)
    assert pagina.context["form"].initial["data_inizio"] == D(2027, 1, 1)
    assert pagina.context["form"].initial["modalita"] == "anticipata"
    risposta = editor.post(
        url_c,
        {
            "fornitore": c1.fornitore_id,
            "descrizione": "Licenze CAD di prova",
            "numero_contratto": "5800000099",
            "data_emissione": "20/07/2026",
            "procedura": c1.procedura_id,
            "data_inizio": "01/01/2027",
            "durata_mesi": "12",
            "tipo_acquisto": "servizio",
            "modalita": "anticipata",
            "periodicita": "annuale",
            "voci-TOTAL_FORMS": "1",
            "voci-INITIAL_FORMS": "1",
            "voci-MIN_NUM_FORMS": "1",
            "voci-0-posizione": "1",
            "voci-0-descrizione": "Canone licenze",
            "voci-0-importo_fisso": "1.050,00",
        },
    )
    c2 = m.Contratto.objects.get(numero_contratto="5800000099")
    assert risposta.status_code == 302 and risposta.url == reverse(
        "contratti:contratto", args=[c2.pk]
    )
    assert (c2.predecessore, c2.rda, c2.una_tantum) == (c1, rda, False)
    voce = c2.voci.get()
    assert (voce.conto.codice, voce.centro_costo, voce.importo_fisso) == (
        "600001", "C0001", Decimal("1050.00"),
    )  # fmt: skip
    assert voce.piano_fatturazione.rate.count() == 1
    assert acquisti.differenza_da_rda(c2) == Decimal("-50.00")
    assert acquisti.fase(rda) == Fase.CONTRATTO_EMESSO
    assert not c1.stati_pratica.exists()  # nessun passaggio scritto: lo stato si ricava


def test_acquisto_aggiuntivo_e_primo_acquisto(editor, rinnovo):
    fab, c1 = rinnovo
    pagina = editor.get(reverse("contratti:rda_nuova", args=[fab.pk]) + "?aggiuntivo=1")
    assert pagina.context["proposta"].scopo == "aggiuntivo"
    _post_richiesta(
        editor,
        reverse("contratti:rda_nuova", args=[fab.pk]),
        [{"descrizione_breve": "Licenze in più", "importo_unitario": "300"}],
        aggiuntivo="1",
        invia="1",
    )
    rda = m.RichiestaAcquisto.objects.get()
    assert (rda.scopo, rda.fabbisogno, rda.contratto_in_scadenza) == ("aggiuntivo", fab, None)
    assert acquisti.stato_pratica(c1) is None
    rda.numero_rda, rda.data_inserimento = "5100000002", D(2026, 6, 1)
    rda.save()
    pagina = editor.get(reverse("contratti:rda_contratto", args=[rda.pk]))
    assert pagina.context["form"].initial["una_tantum"] is True
    assert pagina.context["form"].initial["modalita"] == "una_tantum"

    nuovo = f.fabbisogno("Fabbisogno nuovo", stima_prossimo_importo=Decimal("5000"))
    pagina = editor.get(reverse("contratti:rda_nuova", args=[nuovo.pk]))
    assert pagina.context["proposta"].scopo == "primo_acquisto"
    assert pagina.context["formset"].initial[0]["importo_unitario"] == Decimal("5000")


def test_richiesta_senza_posizioni_rifiutata(editor, rinnovo):
    fab, _ = rinnovo
    risposta = _post_richiesta(editor, reverse("contratti:rda_nuova", args=[fab.pk]), [{}])
    assert risposta.status_code == 200
    assert "almeno una posizione" in risposta.content.decode()
    assert not m.RichiestaAcquisto.objects.exists()


def test_scheda_sap_e_testo_copiato_uguale_a_tc17(editor, sap):
    fornitore, conti = sap
    rda = m.RichiestaAcquisto.objects.create(
        origine="manuale",
        cluster=f.cluster("IT"),
        intestazione="SWPROVA - Rinnovo licenza CAD (2 postazioni)",
        descrizione="Rinnovo licenza CAD (2 postazioni)",
        fornitore_proposto=fornitore,
        richiedente=m.RichiedenteSAP.objects.get(codice="999901"),
        gruppo_acquisti=m.GruppoAcquisti.objects.get(codice="G01"),
        note_buyer="Si allega preventivo",
        allegati="preventivo nella cartella del file server",
        percorso_file_server=f"{BASE}/2026/2026_09_29_SWPROVA_Rinnovo_licenza_CAD_2_postazioni",
    )
    for numero, (descr, gm, q, prezzo, conto) in enumerate(
        [
            ("SWPROVA - Rinnovo licenza CAD (2 postazioni)", "GM-TEST01", "2", "549.50", "600001"),
            ("Supporto installazione", "GM-TEST02", "2.5", "99.99", "600002"),
        ],
        start=1,
    ):
        m.PosizioneRDA.objects.create(
            rda=rda, numero=numero, descrizione_breve=descr,
            gruppo_merci=m.GruppoMerci.objects.get(codice=gm), quantita=Decimal(q),
            importo_unitario=Decimal(prezzo), conto=conti[conto], centro_costo="C0001",
        )  # fmt: skip
    risposta = editor.get(reverse("contratti:rda", args=[rda.pk]))
    assert risposta.context["testo"] == TESTO_ATTESO
    pagina = risposta.content.decode()
    inizio = pagina.index('id="testo-richiesta"')
    contenuto = pagina[pagina.index(">", inizio) + 1 : pagina.index("</textarea>", inizio)]
    assert html.unescape(contenuto) == TESTO_ATTESO
    assert 'data-copia-testo="549,50"' in pagina and 'data-copia-testo="2,5"' in pagina
    assert 'data-copia-testo="999901"' in pagina


def test_rda_a_mano_poi_collegata(editor, rinnovo):
    fab, c1 = rinnovo
    risposta = editor.post(
        reverse("contratti:rda_registra"),
        {
            "cluster": f.cluster("IT").pk,
            "descrizione": "RDA già in SAP",
            "referente": "Referente di prova",
            "numero_rda": "5100000077",
            "data_inserimento": "02/02/2026",
        },
    )
    rda = m.RichiestaAcquisto.objects.get(numero_rda="5100000077")
    assert risposta.status_code == 302 and rda.origine == "manuale"
    assert acquisti.fase(rda) == Fase.INSERITA
    assert acquisti.stato_pratica(c1) is None
    editor.post(reverse("contratti:rda_collega_pratica", args=[rda.pk]), {"contratto": c1.pk})
    rda.refresh_from_db()
    assert (rda.contratto_in_scadenza, rda.scopo) == (c1, "rinnovo")
    assert acquisti.stato_pratica(c1) == "rda_predisposta"
    # Il contratto con lo stesso n. RDA scritto: proposta di collegamento, dai due lati.
    vecchio = f.contratto(fabbisogno=fab, numero_rda="5100000077", data_inizio=D(2025, 1, 1))
    pagina = editor.get(reverse("contratti:rda", args=[rda.pk]))
    assert vecchio in pagina.context["proposti"]
    assert (
        editor.get(reverse("contratti:contratto", args=[vecchio.pk])).context["rda_proposta"] == rda
    )
    editor.post(reverse("contratti:contratto_collega_rda", args=[vecchio.pk]), {"rda": rda.pk})
    vecchio.refresh_from_db()
    assert vecchio.rda == rda
    editor.post(reverse("contratti:contratto_scollega_rda", args=[vecchio.pk]))
    vecchio.refresh_from_db()
    assert vecchio.rda is None
    editor.post(
        reverse("contratti:rda_collega_contratto", args=[rda.pk]), {"contratto": vecchio.pk}
    )
    vecchio.refresh_from_db()
    assert vecchio.rda == rda


def test_annulla_e_pagine(editor, una_rda):
    rda, c1 = una_rda
    editor.post(reverse("contratti:rda_annulla", args=[rda.pk]), {"nota": ""})
    assert acquisti.fase(rda) == Fase.BOZZA  # motivo obbligatorio
    editor.post(reverse("contratti:rda_annulla", args=[rda.pk]), {"nota": "Non serve più"})
    assert acquisti.fase(rda) == Fase.ANNULLATA
    assert editor.get(reverse("contratti:rda_modifica", args=[rda.pk])).status_code == 302
    elenco = editor.get(reverse("contratti:rda_elenco"), {"fase": "annullata"})
    assert [r["rda"] for r in elenco.context["pagina"]] == [rda]
    fab = editor.get(reverse("contratti:fabbisogno", args=[c1.fabbisogno.pk]))
    assert [x["rda"] for x in fab.context["richieste"]] == [rda]
    assert (
        "Nuova richiesta di RDA"
        in editor.get(reverse("contratti:contratto", args=[c1.pk])).content.decode()
    )


def test_ricerca_per_numero_rda(editor, una_rda):
    rda, _ = una_rda
    rda.numero_rda = "5100000123"
    rda.save()
    risposta = editor.get(reverse("contratti:cerca"), {"q": "5100000123"})
    assert risposta.context["risultati"]["rda"] == [rda]


def test_pratica_a_mano_solo_offerte(editor, dati):
    c = dati["contratto"]
    url = reverse("contratti:pratica_avanza", args=["contratto", c.pk])
    editor.post(url, {"stato": "rda_richiesta", "data": "01/09/2026"})
    assert not c.stati_pratica.exists()
    editor.post(url, {"stato": "offerta_ricevuta", "data": "01/09/2026"})
    assert c.stati_pratica.get().stato == "offerta_ricevuta"
