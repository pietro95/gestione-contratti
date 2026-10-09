"""Intestazione e descrizione breve entro i 40 caratteri di SAP: proposta tagliata, scheda
che segnala le RDA già registrate più lunghe. Dati di fantasia."""

import datetime

import pytest
from django.urls import reverse

from accounts.roles import READER
from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import acquisti
from contratti import models as m
from contratti.engine import acquisti as motore
from tests.connettore.conftest import chiama

from . import factories as f

pytestmark = pytest.mark.django_db
LUNGA = "Servizio di manutenzione evolutiva del gestionale di prova"  # 58 caratteri


def test_taglia_sap():
    assert motore.taglia_sap(LUNGA) == "Servizio di manutenzione evolutiva del g"
    assert motore.taglia_sap("Parola finale con spazio ma di quaranta  caratteri") == (
        "Parola finale con spazio ma di quaranta"
    )  # niente spazi in coda
    assert not motore.oltre_limite_sap("x" * 40) and motore.oltre_limite_sap("x" * 41)


def test_la_proposta_sta_nei_40_caratteri():
    fab = f.fabbisogno(LUNGA)
    c = f.contratto(fabbisogno=fab, fornitore=f.fornitore("Prova S.r.l.", nome_breve="PROVA"))
    f.voce(c, descrizione=LUNGA)
    f.voce(c, descrizione="Assistenza")
    p = acquisti.proposta_richiesta(fab, datetime.date(2026, 10, 9))
    assert p.intestazione == "PROVA - Servizio di manutenzione evoluti"
    assert all(len(x.descrizione_breve) <= 40 for x in p.posizioni)
    assert p.posizioni[0].descrizione_breve == p.intestazione


def test_scheda_segnala_una_rda_gia_registrata_piu_lunga(client, make_user):
    rda = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"), descrizione="RDA storica", intestazione=LUNGA,
        origine=m.RichiestaAcquisto.Origine.MANUALE,
    )  # fmt: skip
    m.PosizioneRDA.objects.create(rda=rda, numero=1, descrizione_breve=LUNGA,
                                  importo_unitario=1)  # fmt: skip
    lettore = make_user("lettore", role=READER)
    client.force_login(lettore)
    pagina = client.get(reverse("contratti:rda", args=[rda.pk])).content.decode()
    assert pagina.count("58 caratteri: SAP ne accetta 40") == 2
    risposta, _ = protocollo.gestisci(
        chiama("rda", {"id": rda.pk}), Contesto(lettore, datetime.date(2026, 10, 9))
    )
    lunghi = [c["campo"] for c in risposta["result"]["structuredContent"]["scheda_sap"]
              if c.get("oltre_40_caratteri")]  # fmt: skip
    assert lunghi == ["Intestazione", "Descrizione breve"]
