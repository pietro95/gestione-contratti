"""Equivalenza con l'interfaccia (SPEC_MCP §8.4): stessi dati → stesso stato del database.

Ogni caso esegue l'operazione dalla vista web in una transazione annullata, ne fotografa i
dati di dominio, poi la esegue dal connettore (anteprima + conferma) e confronta.
"""

import datetime
from decimal import Decimal

import pytest
from django.db import transaction

from accounts.roles import EDITOR
from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import forms, servizi
from contratti import models as m
from tests import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 5)
DOMINIO = [
    m.Fornitore,
    m.Fabbisogno,
    m.Contratto,
    m.VoceContratto,
    m.PianoFatturazione,
    m.Rata,
    m.StatoPratica,
    m.Proroga,
    m.QuotaPeriodo,
    m.OpzioneContratto,
]
ESCLUSI = {"id", "registrato_il"}


def stato() -> dict:
    return {
        M._meta.label: sorted(
            tuple(repr(getattr(o, c.attname)) for c in M._meta.fields if c.attname not in ESCLUSI)
            for o in M.objects.all()
        )
        for M in DOMINIO
    }


def mcp(utente, nome, argomenti) -> dict:
    c = Contesto(utente, OGGI, scrittura=True, client_id="prova")

    def chiama(n, a):
        messaggio = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": n, "arguments": a},
        }
        r = protocollo.gestisci(messaggio, c)[0]["result"]
        assert not r.get("isError"), r
        return r["structuredContent"]

    codice = chiama(nome, argomenti)["id_operazione"]
    return chiama("conferma_operazione", {"id_operazione": codice})


@pytest.fixture
def editor(make_user, client):
    utente = make_user("redattore", role=EDITOR)
    client.force_login(utente)
    return utente


def equivalente(client, editor, web, nome, argomenti):
    iniziale = stato()
    with transaction.atomic():
        risposta = web(client)
        assert risposta.status_code in (200, 302), risposta.content[:300]
        atteso = stato()
        transaction.set_rollback(True)
    assert stato() == iniziale
    assert atteso != iniziale, "la vista web non ha modificato niente"
    mcp(editor, nome, argomenti)
    assert stato() == atteso


@pytest.fixture
def contratto():
    c = f.contratto(data_inizio=D(2025, 6, 1), durata_mesi=12, descrizione="Canone di prova")
    v = f.voce(c, importo_fisso=Decimal("1200.00"))
    f.piano(v, modalita="anticipata", periodicita="trimestrale")
    return c


# --- A ------------------------------------------------------------------------------------------


def test_avanza_pratica(client, editor, contratto):
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/pratica/contratto/{contratto.pk}/",
            {"stato": "offerta_richiesta", "data": "05/10/2026", "note": "chiesta"},
        ),
        "avanza_pratica",
        {"contratto_id": contratto.pk, "stato": "offerta_richiesta", "data": "2026-10-05",
         "note": "chiesta"},
    )  # fmt: skip


def test_genera_scadenzario(client, editor, contratto):
    voce = contratto.voci.get()
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/voci/{voce.pk}/scadenzario/"),
        "genera_scadenzario",
        {"voce_id": voce.pk},
    )


def test_modifica_rata(client, editor, contratto):
    voce = contratto.voci.get()
    rata = servizi.genera_scadenzario(voce)[0]
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/rate/{rata.pk}/",
            {
                "data_fattura": rata.data_fattura.strftime("%d/%m/%Y"),
                "data_pagamento_stimata": rata.data_pagamento_stimata.strftime("%d/%m/%Y"),
                "importo": "350,00",
                "consuntivo": "on",
                "numero_fattura": "F-1",
            },
        ),
        "modifica_rata",
        {"id": rata.pk, "importo": "350.00", "consuntivo": True, "numero_fattura": "F-1"},
    )


# --- B ------------------------------------------------------------------------------------------


def test_crea_fornitore(client, editor):
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            "/fornitori/nuovo/",
            {"ragione_sociale": "Nuovo Fornitore S.r.l.", "partita_iva": "01234567890",
             "codice_sap": "100200", "note": ""},
        ),
        "crea_fornitore",
        {"ragione_sociale": "Nuovo Fornitore S.r.l.", "partita_iva": "01234567890",
         "codice_sap": "100200"},
    )  # fmt: skip


def test_modifica_fornitore(client, editor):
    fornitore = f.fornitore("Vecchia Ragione S.r.l.", partita_iva="09876543210")
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/fornitori/{fornitore.pk}/modifica/",
            {"ragione_sociale": "Nuova Ragione S.r.l.", "partita_iva": "09876543210",
             "codice_sap": "", "note": ""},
        ),
        "modifica_fornitore",
        {"id": fornitore.pk, "ragione_sociale": "Nuova Ragione S.r.l."},
    )  # fmt: skip


def _dati_fabbisogno(**kw):
    dati = {
        "descrizione": "Servizio nuovo di prova",
        "cluster": f.cluster("IT").pk,
        "categoria": m.Categoria.objects.get(nome="Da classificare").pk,
        "decisione": m.Fabbisogno.Decisione.DA_VALUTARE,
    }
    return {k: v for k, v in (dati | kw).items() if v is not None}


def test_crea_fabbisogno(client, editor):
    equivalente(
        client,
        editor,
        lambda cl: cl.post("/fabbisogni/nuovo/", _dati_fabbisogno()),
        "crea_fabbisogno",
        {"descrizione": "Servizio nuovo di prova", "cluster": "IT"},
    )


def test_crea_fabbisogno_con_previsto_manuale(client, editor):
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            "/fabbisogni/nuovo/",
            _dati_fabbisogno(
                decisione="rinnovare",
                stima_prossimo_importo="12.000,00",
                previsto_data_avvio="01/03/2027",
                previsto_durata_mesi=12,
                previsto_modalita="anticipata",
                previsto_periodicita="annuale",
            ),
        ),
        "crea_fabbisogno",
        {
            "descrizione": "Servizio nuovo di prova",
            "cluster": "IT",
            "decisione": "rinnovare",
            "stima_prossimo_importo": "12000.00",
            "previsto_data_avvio": "2027-03-01",
            "previsto_durata_mesi": 12,
            "previsto_modalita": "anticipata",
            "previsto_periodicita": "annuale",
        },
    )


def test_modifica_fabbisogno(client, editor, contratto):
    fab = contratto.fabbisogno
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/fabbisogni/{fab.pk}/modifica/",
            _dati_fabbisogno(
                descrizione=fab.descrizione,
                categoria=fab.categoria_id,
                decisione="dismettere",
                stima_prossimo_importo="900,00",
            ),
        ),
        "modifica_fabbisogno",
        {"id": fab.pk, "decisione": "dismettere", "stima_prossimo_importo": "900.00"},
    )


def test_stessi_errori_del_form(editor):
    dati = _dati_fabbisogno(previsto_data_avvio="2027-01-01")
    form = forms.FabbisognoForm(dati, utente=editor)
    assert not form.is_valid()
    c = Contesto(editor, OGGI, scrittura=True)
    messaggio = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "crea_fabbisogno",
            "arguments": {"descrizione": "X", "cluster": "IT", "previsto_data_avvio": "2027-01-01"},
        },
    }
    testo = protocollo.gestisci(messaggio, c)[0]["result"]["content"][0]["text"]
    for errore in form.non_field_errors():
        assert errore in testo


# --- Archiviazione ------------------------------------------------------------------------------


def test_archivia_e_ripristina(client, editor, contratto):
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/archivia/contratto/{contratto.pk}/"),
        "archivia",
        {"tipo": "contratto", "id": contratto.pk},
    )
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/archivia/contratto/{contratto.pk}/", {"ripristina": "1"}),
        "ripristina",
        {"tipo": "contratto", "id": contratto.pk},
    )


# --- D. Catena ----------------------------------------------------------------------------------


@pytest.fixture
def catena():
    fab = f.fabbisogno("Servizio con due periodi")
    primo = f.contratto(fabbisogno=fab, data_inizio=D(2025, 1, 1), durata_mesi=12)
    secondo = f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12)
    return primo, secondo


def test_collega_e_scollega(client, editor, catena):
    primo, secondo = catena
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/contratti/{primo.pk}/collega/", {"successore": secondo.pk}),
        "collega_rinnovo",
        {"contratto_id": primo.pk, "successore_id": secondo.pk},
    )
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/contratti/{secondo.pk}/scollega/"),
        "scollega_predecessore",
        {"contratto_id": secondo.pk},
    )


def test_confluisci_e_togli(client, editor, catena):
    primo, secondo = catena
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/contratti/{secondo.pk}/confluiti/", {"confluiti": [primo.pk]}),
        "confluisci",
        {"contratto_id": secondo.pk, "confluiti_ids": [primo.pk]},
    )
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/contratti/{primo.pk}/togli-confluenza/"),
        "togli_confluenza",
        {"contratto_id": primo.pk},
    )


def test_collega_un_candidato_non_ammesso(editor, catena):
    primo, secondo = catena
    c = Contesto(editor, OGGI, scrittura=True)
    messaggio = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "collega_rinnovo",
            "arguments": {"contratto_id": secondo.pk, "successore_id": primo.pk},
        },
    }
    r = protocollo.gestisci(messaggio, c)[0]["result"]
    assert r["isError"] and "Candidati" in r["content"][0]["text"]
