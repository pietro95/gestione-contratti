"""Trasferimento per il pagamento senza RdC/MAP/MIGO, o con documenti non rilasciati su SAP:
avviso e giustificazione obbligatoria. Nomi e codici di fantasia."""

import datetime

import pytest
from django.urls import reverse

from accounts.roles import EDITOR, READER
from contratti import acquisti, fatture
from contratti import models as m
from contratti.engine.acquisti import mancanze_trasferimento

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
PASSWORD = "pw-test-123"


# --- Motore -----------------------------------------------------------------------------------


def test_motore_documenti_completi():
    docs = [("ODA_RDC", D(2026, 3, 1), True), ("MAP", D(2026, 3, 2), True)]
    assert mancanze_trasferimento(docs) == []
    assert (
        mancanze_trasferimento([("ODA_RDC", D(2026, 3, 1), True), ("MIGO", D(2026, 3, 2), False)])
        == []
    )


def test_motore_documenti_mancanti_o_non_rilasciati():
    assert mancanze_trasferimento([]) == ["manca la RdC (ODA/RDC)", "manca il MAP o il MIGO"]
    docs = [("ODA_RDC", D(2026, 3, 1), False), ("MAP", D(2026, 3, 2), False)]
    assert mancanze_trasferimento(docs) == [
        "la RdC non è rilasciata su SAP",
        "il MAP non è rilasciato su SAP",
    ]
    # Il contratto che vale come ODA non chiede la RdC.
    assert mancanze_trasferimento([("MAP", D(2026, 3, 2), True)], contratto_oda=True) == []


# --- Servizio e interfaccia -------------------------------------------------------------------


@pytest.fixture
def fattura(make_user):
    rossi = make_user("rossi", role=EDITOR, password=PASSWORD)
    c = f.contratto()
    fa = m.Fattura.objects.create(
        contratto=c, numero="FA-9", data=D(2026, 3, 1), importo_documento=100,
        data_registrazione=D(2026, 3, 1), referente=rossi,
        data_presa_in_carico=D(2026, 3, 1), esito_convalida="convalidabile",
        data_convalida=D(2026, 3, 1),
    )  # fmt: skip
    return fa


def test_senza_documenti_serve_la_giustificazione(fattura):
    with pytest.raises(acquisti.OperazioneNonAmmessa, match="giustificazione"):
        fatture.trasferisci(fattura, data=D(2026, 3, 20))
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.trasferisci(fattura, data=D(2026, 3, 20), giustificazione="   ")
    fatture.trasferisci(fattura, data=D(2026, 3, 20), giustificazione="Pagamento urgente")
    fattura.refresh_from_db()
    assert fattura.data_trasferimento == D(2026, 3, 20)
    assert fattura.giustificazione_trasferimento == "Pagamento urgente"
    assert fattura.history.first().history_change_reason.startswith("Trasferita senza")
    fatture.annulla_trasferimento(fattura)
    fattura.refresh_from_db()
    assert fattura.giustificazione_trasferimento == ""


def test_documenti_rilasciati_nessuna_giustificazione(fattura):
    c = fattura.contratto
    for tipo in ("ODA_RDC", "MAP"):
        m.DocumentoEsecuzione.objects.create(
            contratto=c, tipo=tipo, data=D(2026, 3, 5), fattura=fattura,
            data_rilascio=D(2026, 3, 6),
        )  # fmt: skip
    assert fatture.mancanze_trasferimento(fattura) == []
    fatture.trasferisci(fattura, data=D(2026, 3, 20), giustificazione="ignorata")
    fattura.refresh_from_db()
    assert fattura.giustificazione_trasferimento == ""


def test_documento_rigettato_conta_come_mancante(fattura):
    m.DocumentoEsecuzione.objects.create(
        contratto=fattura.contratto, tipo="ODA_RDC", data=D(2026, 3, 5), fattura=fattura,
        rigettato_il=D(2026, 3, 6), nota_rigetto="numero errato",
    )  # fmt: skip
    assert "manca la RdC (ODA/RDC)" in fatture.mancanze_trasferimento(fattura)


def test_pagina_avviso_e_nota(client, fattura, make_user):
    make_user("addetto", role=EDITOR, password=PASSWORD)
    m.FunzioneUtente.objects.create(
        username="addetto", funzione=m.FunzioneUtente.Funzione.AMMINISTRAZIONE_ACQUISTI
    )
    client.login(username="addetto", password=PASSWORD)
    url = reverse("contratti:fattura", args=[fattura.pk])
    pagina = client.get(url).content.decode()
    assert "Documenti SAP incompleti" in pagina and 'name="giustificazione"' in pagina
    azione = reverse("contratti:fattura_trasferisci", args=[fattura.pk])
    client.post(azione, {"data": "20/03/2026"})
    fattura.refresh_from_db()
    assert fattura.data_trasferimento is None
    client.post(azione, {"data": "20/03/2026", "giustificazione": "Autorizzato dal RUP"})
    fattura.refresh_from_db()
    assert fattura.data_trasferimento == D(2026, 3, 20)
    assert "Autorizzato dal RUP" in client.get(url).content.decode()


def test_reader_403(client, fattura, make_user):
    make_user("neri", role=READER, password=PASSWORD)
    client.login(username="neri", password=PASSWORD)
    r = client.post(
        reverse("contratti:fattura_trasferisci", args=[fattura.pk]),
        {"data": "20/03/2026", "giustificazione": "x"},
    )
    assert r.status_code == 403
