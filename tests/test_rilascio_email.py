"""Link «Rilascia ora» nelle email di rilascio (SPEC §5.10, Rev43)."""

import datetime
import re
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse

from contratti import acquisti, fatture, promemoria, rilascio_link
from contratti import models as m

from . import factories as f
from .test_notifiche import Tipo, _rda, utenti  # noqa: F401

pytestmark = pytest.mark.django_db
D = datetime.date
LINK = re.compile(r"https://contratti\.esempio\.test(/\S*rilasci/email/\S+/)")


def _link_nel_corpo(msg) -> str:
    trovati = LINK.findall(msg.body)
    assert len(trovati) == 1, msg.body
    return trovati[0]


@pytest.fixture
def rda_inserita(utenti, django_capture_on_commit_callbacks):  # noqa: F811
    rda = _rda(utenti)
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.invia(rda, utenti["ref"])
        acquisti.aggiorna_dati_sap(rda, "5100000099", D(2026, 11, 9), utenti["amm"])
    return rda


@pytest.fixture
def documento_registrato(utenti, django_capture_on_commit_callbacks):  # noqa: F811
    contratto = f.contratto(fornitore=f.fornitore("Fornitore Prova S.r.l."))
    f.voce(contratto)
    fattura = m.Fattura.objects.create(
        fornitore=contratto.fornitore,
        contratto=contratto,
        numero="F-1/2026",
        data=D(2026, 10, 30),
        importo_documento=Decimal("100.00"),
        referente=utenti["ref"],
        data_presa_in_carico=D(2026, 11, 2),
    )
    with django_capture_on_commit_callbacks(execute=True):
        doc = fatture.registra_documento(
            fattura, Tipo.ODA, "4600000001", D(2026, 11, 3), utente=utenti["amm"]
        )
    return doc


def test_email_rda_ha_il_link_di_rilascio(rda_inserita):
    msg = next(x for x in mail.outbox if x.to == ["ril@esempio.test"])
    assert "Rilascia ora" in msg.body
    percorso = _link_nel_corpo(msg)
    assert rilascio_link.leggi(percorso.rstrip("/").rsplit("/", 1)[1]) == (
        rilascio_link.RDA,
        rda_inserita.pk,
    )


def test_il_referente_per_conoscenza_non_riceve_il_link(documento_registrato):
    per_ril = next(x for x in mail.outbox if x.to == ["ril@esempio.test"])
    per_ref = next(x for x in mail.outbox if x.to == ["ref@esempio.test"])
    assert "Rilascia ora" in per_ril.body and "/rilasci/email/" in per_ril.body
    assert "/rilasci/email/" not in per_ref.body and "Per conoscenza" in per_ref.body
    assert "/rilasci/" in per_ref.body  # resta il link alla maschera


def test_link_rilascia_la_rda(client, utenti, rda_inserita):  # noqa: F811
    percorso = _link_nel_corpo(next(x for x in mail.outbox if x.to == ["ril@esempio.test"]))
    client.force_login(utenti["ril"])
    risposta = client.get(percorso)
    assert risposta.status_code == 302 and risposta.url == reverse("contratti:rilasci")
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is not None and rda_inserita.rilasciata_da == utenti["ril"]
    # Secondo clic: nessun errore, nessun doppio rilascio.
    risposta = client.get(percorso, follow=True)
    assert risposta.status_code == 200
    assert "già rilasciata" in " ".join(str(x) for x in risposta.context["messages"])


def test_link_rilascia_il_documento(client, utenti, documento_registrato):  # noqa: F811
    msg = next(x for x in mail.outbox if x.to == ["ril@esempio.test"])
    client.force_login(utenti["ril"])
    assert client.get(_link_nel_corpo(msg)).status_code == 302
    documento_registrato.refresh_from_db()
    assert documento_registrato.data_rilascio is not None
    assert documento_registrato.rilasciato_da == utenti["ril"]


@pytest.mark.parametrize("chi", ["altro", "lettore"])
def test_senza_la_funzione_di_rilascio_403(client, utenti, rda_inserita, chi):  # noqa: F811
    percorso = _link_nel_corpo(next(x for x in mail.outbox if x.to == ["ril@esempio.test"]))
    client.force_login(utenti[chi])
    assert client.get(percorso).status_code == 403
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is None


def test_senza_login_si_passa_dall_accesso_e_non_si_rilascia(client, rda_inserita):
    percorso = _link_nel_corpo(next(x for x in mail.outbox if x.to == ["ril@esempio.test"]))
    risposta = client.get(percorso)
    assert risposta.status_code == 302 and "login" in risposta.url and "next=" in risposta.url
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is None


def test_token_alterato_non_rilascia(client, utenti, rda_inserita):  # noqa: F811
    client.force_login(utenti["ril"])
    risposta = client.get(reverse("contratti:rilascia_da_email", args=["abc:def:ghi"]), follow=True)
    assert "non è valido" in " ".join(str(x) for x in risposta.context["messages"])
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is None


def test_token_scaduto_non_rilascia(client, utenti, rda_inserita, settings):  # noqa: F811
    token = rilascio_link.crea(rilascio_link.RDA, rda_inserita.pk)
    settings.RILASCIO_LINK_GIORNI = -1
    client.force_login(utenti["ril"])
    risposta = client.get(reverse("contratti:rilascia_da_email", args=[token]), follow=True)
    assert "scaduto" in " ".join(str(x) for x in risposta.context["messages"])
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is None


def test_il_token_di_un_tipo_non_vale_per_l_altro(client, utenti, rda_inserita):  # noqa: F811
    # Stesso pk, tipo documento: non esiste un documento con quel pk, non si tocca l'RDA.
    token = rilascio_link.crea(rilascio_link.DOCUMENTO, rda_inserita.pk)
    client.force_login(utenti["ril"])
    client.get(reverse("contratti:rilascia_da_email", args=[token]))
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is None


def test_il_promemoria_ha_un_link_per_ogni_rilascio(rda_inserita, documento_registrato):
    per_addetto, _ = promemoria.messaggi_rilasci(D(2026, 11, 10))
    assert len(LINK.findall(per_addetto.corpo)) == 2
