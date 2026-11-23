"""Richiesta di annullamento del rilascio su SAP con motivazione (SPEC §5.9, Rev56)."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.roles import ADDETTO_AMMINISTRATIVO, EDITOR, READER
from contratti import acquisti, annullamenti, fatture
from contratti import models as m

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
Tipo = m.DocumentoEsecuzione.Tipo
Stato = m.RichiestaAnnullamentoRilascio.Stato
PASSWORD = "password-locale-di-prova"


@pytest.fixture
def scenario(make_user):
    rossi = make_user("rossi", role=EDITOR, email="rossi@esempio.test")
    addetto = make_user("addetto", role=EDITOR, email="addetto@esempio.test")
    amm = make_user("amm", role=EDITOR, email="amm@esempio.test")
    amm.groups.add(Group.objects.get(name=ADDETTO_AMMINISTRATIVO))
    m.FunzioneUtente.objects.create(
        username="addetto", funzione=m.FunzioneUtente.Funzione.RILASCIO_SAP
    )
    contratto = f.contratto(fornitore=f.fornitore("Fornitore Prova S.r.l."))
    fattura = m.Fattura.objects.create(
        fornitore=contratto.fornitore,
        contratto=contratto,
        numero="F-1/2026",
        data=D(2026, 9, 30),
        importo_documento=Decimal("100.00"),
        referente=rossi,
        data_presa_in_carico=D(2026, 10, 1),
        esito_convalida=m.Fattura.Esito.CONVALIDABILE,
        data_convalida=D(2026, 10, 1),
    )
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 10, 2))
    fatture.rilascia_documenti([rdc.pk], addetto, D(2026, 10, 3))
    rdc.refresh_from_db()
    rda = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"),
        origine="manuale",
        descrizione="RDA di prova",
        numero_rda="5100000001",
        data_inserimento=D(2026, 10, 1),
        referente_utente=rossi,
    )
    acquisti.rilascia_rda([rda], addetto, D(2026, 10, 3))
    rda.refresh_from_db()
    mail.outbox.clear()
    return {"fattura": fattura, "rdc": rdc, "rda": rda, "rossi": rossi, "addetto": addetto,
            "amm": amm}  # fmt: skip


def _login(client, nome):
    assert client.login(username=nome, password=PASSWORD)
    return client


def test_richiesta_e_annullamento_del_documento(scenario, django_capture_on_commit_callbacks):
    rdc, rossi, addetto = scenario["rdc"], scenario["rossi"], scenario["addetto"]
    with django_capture_on_commit_callbacks(execute=True):
        richiesta = annullamenti.chiedi(rdc, "  Numero sbagliato su SAP ", rossi, D(2026, 10, 4))
    assert richiesta.stato == Stato.APERTA and richiesta.motivazione == "Numero sbagliato su SAP"
    assert [msg.to for msg in mail.outbox] == [["addetto@esempio.test"]]
    assert "Numero sbagliato su SAP" in mail.outbox[0].body
    assert annullamenti.aperta(rdc) == richiesta
    rdc.refresh_from_db()
    assert rdc.data_rilascio == D(2026, 10, 3)  # la richiesta da sola non cambia niente
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        fatture.annulla_rilascio(rdc, addetto)
    rdc.refresh_from_db()
    richiesta.refresh_from_db()
    assert rdc.data_rilascio is None and rdc in fatture.documenti_da_rilasciare()
    assert richiesta.stato == Stato.ESEGUITA and richiesta.chiusa_da == addetto
    assert annullamenti.aperta(rdc) is None
    assert "Numero sbagliato" in rdc.history.first().history_change_reason
    assert [msg.to for msg in mail.outbox] == [["rossi@esempio.test"]]
    assert "Rilascio annullato" in mail.outbox[0].subject


def test_richiesta_respinta_con_nota(scenario, django_capture_on_commit_callbacks):
    rda, addetto, amm = scenario["rda"], scenario["addetto"], scenario["amm"]
    richiesta = annullamenti.chiedi(rda, "Importo da rivedere", amm)
    with pytest.raises(PermissionDenied):
        annullamenti.respingi(richiesta, "no", scenario["rossi"])
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        annullamenti.respingi(richiesta, "  ", addetto)
    with django_capture_on_commit_callbacks(execute=True):
        annullamenti.respingi(richiesta, "Già passata al Procurement", addetto)
    richiesta.refresh_from_db()
    rda.refresh_from_db()
    assert (
        richiesta.stato == Stato.RESPINTA and richiesta.nota_esito == "Già passata al Procurement"
    )
    assert rda.data_rilascio == D(2026, 10, 3)
    assert [msg.to for msg in mail.outbox] == [["amm@esempio.test"]]
    assert "Già passata al Procurement" in mail.outbox[0].body
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        annullamenti.respingi(richiesta, "di nuovo", addetto)
    # Respinta, se ne può fare un'altra.
    assert annullamenti.chiedi(rda, "Altro motivo", amm).stato == Stato.APERTA


def test_annullamento_della_rda_su_richiesta(scenario):
    rda, addetto = scenario["rda"], scenario["addetto"]
    richiesta = annullamenti.chiedi(rda, "RDA da correggere", scenario["rossi"])
    acquisti.annulla_rilascio_rda(rda, addetto)
    rda.refresh_from_db()
    richiesta.refresh_from_db()
    assert rda.data_rilascio is None and richiesta.stato == Stato.ESEGUITA
    assert acquisti.rda_da_rilasciare() == [rda]


def test_regole_della_richiesta(scenario, make_user):
    rdc, rossi = scenario["rdc"], scenario["rossi"]
    with pytest.raises(acquisti.OperazioneNonAmmessa, match="motivazione"):
        annullamenti.chiedi(rdc, "   ", rossi)
    annullamenti.chiedi(rdc, "Motivo", rossi)
    with pytest.raises(acquisti.OperazioneNonAmmessa, match="già una richiesta"):
        annullamenti.chiedi(rdc, "Ancora", scenario["amm"])
    # Il Reader e chi non lavora nel cluster non chiedono.
    neri = make_user("neri", role=READER)
    assert not annullamenti.puo_chiedere(neri, rdc)
    with pytest.raises(PermissionDenied):
        annullamenti.chiedi(scenario["rda"], "x", neri)
    # Un documento non rilasciato non si annulla.
    map_ = fatture.registra_documento(scenario["fattura"], Tipo.MAP, "5000000001", D(2026, 10, 4))
    with pytest.raises(acquisti.OperazioneNonAmmessa, match="non è rilasciato"):
        annullamenti.chiedi(map_, "x", rossi)


def test_fattura_trasferita_non_si_chiede(scenario):
    fa = scenario["fattura"]
    fatture.trasferisci(fa, scenario["amm"], giustificazione="prova")
    scenario["rdc"].fattura.refresh_from_db()
    with pytest.raises(acquisti.OperazioneNonAmmessa, match="trasferita"):
        annullamenti.chiedi(scenario["rdc"], "x", scenario["rossi"])


def test_una_sola_aperta_anche_nel_database(scenario):
    rdc, rossi = scenario["rdc"], scenario["rossi"]
    annullamenti.chiedi(rdc, "Uno", rossi)
    with pytest.raises(IntegrityError), transaction.atomic():
        m.RichiestaAnnullamentoRilascio.objects.create(
            documento=rdc, motivazione="Due", richiesta_il=D(2026, 10, 5), richiesta_da=rossi
        )


def test_flusso_dalle_pagine(scenario, client):
    rdc, rda = scenario["rdc"], scenario["rda"]
    _login(client, "rossi")
    pagina = client.get(reverse("contratti:fattura", args=[scenario["fattura"].pk])).content
    assert reverse("contratti:rilascio_chiedi_annullamento", args=[rdc.pk]).encode() in pagina
    r = client.post(
        reverse("contratti:rilascio_chiedi_annullamento", args=[rdc.pk]),
        {"motivazione": "Doppio rilascio"},
    )
    assert r.status_code == 302
    client.post(
        reverse("contratti:rilascio_rda_chiedi_annullamento", args=[rda.pk]),
        {"motivazione": "RDA errata"},
    )
    client.logout()
    _login(client, "addetto")
    pagina = client.get(reverse("contratti:rilasci")).content.decode()
    assert "Doppio rilascio" in pagina and "RDA errata" in pagina
    r = client.post(reverse("contratti:rilascio_annulla", args=[rdc.pk]), {"ritorno": "rilasci"})
    assert r.url == reverse("contratti:rilasci")
    richiesta_rda = annullamenti.aperta(rda)
    client.post(reverse("contratti:annullamento_respingi", args=[richiesta_rda.pk]), {"nota": "No"})
    richiesta_rda.refresh_from_db()
    assert richiesta_rda.stato == Stato.RESPINTA
    assert not m.RichiestaAnnullamentoRilascio.objects.filter(stato=Stato.APERTA).exists()


def test_403_per_il_reader_e_per_chi_non_rilascia(scenario, client, make_user):
    rdc, rda = scenario["rdc"], scenario["rda"]
    make_user("neri", role=READER)
    _login(client, "neri")
    for url in (
        reverse("contratti:rilascio_chiedi_annullamento", args=[rdc.pk]),
        reverse("contratti:rilascio_rda_chiedi_annullamento", args=[rda.pk]),
    ):
        assert client.post(url, {"motivazione": "x"}).status_code == 403
    richiesta = annullamenti.chiedi(rdc, "Motivo", scenario["rossi"])
    assert (
        client.post(
            reverse("contratti:annullamento_respingi", args=[richiesta.pk]), {"nota": "x"}
        ).status_code
        == 403
    )
    client.logout()
    _login(client, "rossi")  # Editor del cluster, ma non addetto al rilascio
    assert (
        client.post(
            reverse("contratti:annullamento_respingi", args=[richiesta.pk]), {"nota": "x"}
        ).status_code
        == 403
    )
    richiesta.refresh_from_db()
    assert richiesta.stato == Stato.APERTA
