import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounts.roles import ADMIN, EDITOR, READER
from contratti import models as m

from .. import factories as f

PASSWORD = "password-locale-di-prova"
D = datetime.date


@pytest.fixture
def come(client, make_user):
    """Client autenticato con il ruolo indicato."""

    def _login(ruolo):
        nome = f"u_{ruolo.lower()}"
        make_user(nome, role=ruolo, is_superuser=ruolo == ADMIN, is_staff=ruolo == ADMIN)
        client.login(username=nome, password=PASSWORD)
        return client

    return _login


@pytest.fixture
def editor(come):
    return come(EDITOR)


@pytest.fixture
def reader(come):
    return come(READER)


@pytest.fixture
def dati(db):
    """Un fabbisogno con contratto annuale, voce con piano, rata, proroga e proposte."""
    fab = f.fabbisogno(decisione="rinnovare")
    c = f.contratto(
        fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12, numero_contratto="5800000001"
    )
    v = f.voce(c, importo_fisso=Decimal("10000.00"))
    p = f.piano(v, modalita="anticipata", periodicita="annuale")
    rata = f.rata(p, data_fattura=D(2026, 1, 1), data_pagamento_stimata=D(2026, 3, 31))
    altro = f.contratto(fabbisogno=f.fabbisogno("Altro"), numero_contratto="5800000002")
    rag = m.PropostaRaggruppamento.objects.create(motivazione="prova", chiave="k")
    rag.contratti.set([c, altro])
    pred = m.PropostaPredecessore.objects.create(predecessore=c, successore=altro, motivazione="p")
    nuovo = f.fabbisogno(
        "Nuovo servizio",
        previsto_data_avvio=D(2027, 7, 1),
        previsto_durata_mesi=12,
        stima_prossimo_importo=Decimal("5000.00"),
    )
    autore = get_user_model().objects.create_user("autore_import", password=PASSWORD)
    importazione = m.Importazione.objects.create(
        tipo="date_emissione",
        nome_file="date.csv",
        contenuto=b"numero_contratto;data_emissione\n",
        sha256="0" * 64,
        dimensione=0,
        utente=autore,
    )
    return {
        "importazione": importazione,
        "fabbisogno": fab,
        "contratto": c,
        "voce": v,
        "rata": rata,
        "fornitore": c.fornitore,
        "raggruppamento": rag,
        "predecessore": pred,
        "nuovo": nuovo,
    }
