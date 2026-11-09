"""Contratto che vale come ODA (Rev41): spunta sul contratto e dalla scheda della fattura."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.roles import EDITOR
from contratti import fatture
from contratti import models as m
from contratti.engine.acquisti import PassoFattura

from .. import factories as f
from .conftest import PASSWORD
from .test_fatture import scenario  # noqa: F401

pytestmark = pytest.mark.django_db


def _convalidata(fa, c, referente):
    fa.contratto, fa.referente = c, referente
    fa.data_presa_in_carico = fa.data
    fa.esito_convalida = "convalidabile"
    fa.data_convalida = fa.data
    fa.save()
    return fatture.QS_FATTURE.get(pk=fa.pk)


def _client(username):
    client = Client()
    assert client.login(username=username, password=PASSWORD)
    return client


def test_il_referente_spunta_dalla_fattura_e_il_passo_salta_la_rdc(scenario):  # noqa: F811
    fa, c = scenario["fattura"], scenario["contratto"]
    fa = _convalidata(fa, c, scenario["referente"])
    assert fatture.passo_fattura(fa) == PassoFattura.RDC
    client = _client("rossi")
    pagina = client.get(reverse("contratti:fattura", args=[fa.pk])).content.decode()
    assert "Il contratto vale come ODA" in pagina
    risposta = client.post(reverse("contratti:fattura_oda", args=[fa.pk]), {"vale_come_oda": "1"})
    assert risposta.status_code == 302
    c.refresh_from_db()
    assert c.vale_come_oda is True
    assert fatture.passo_fattura(fatture.QS_FATTURE.get(pk=fa.pk)) == PassoFattura.MAP_MIGO
    assert c.history.first().history_change_reason.startswith("Vale come ODA")
    # Si toglie: torna il passo RdC.
    client.post(reverse("contratti:fattura_oda", args=[fa.pk]), {"vale_come_oda": "0"})
    c.refresh_from_db()
    assert c.vale_come_oda is False
    assert fatture.passo_fattura(fatture.QS_FATTURE.get(pk=fa.pk)) == PassoFattura.RDC


def test_vale_per_tutte_le_fatture_del_contratto(scenario):  # noqa: F811
    fa, c = scenario["fattura"], scenario["contratto"]
    fa = _convalidata(fa, c, scenario["referente"])
    altra = m.Fattura.objects.create(
        fornitore=fa.fornitore,
        numero="14/2026",
        data=fa.data,
        importo_documento=fa.importo_documento,
    )
    altra = _convalidata(altra, c, scenario["referente"])
    fatture.segna_vale_come_oda(fa, True)
    assert fatture.passo_fattura(fatture.QS_FATTURE.get(pk=altra.pk)) == PassoFattura.MAP_MIGO


def test_senza_contratto_non_si_spunta(scenario):  # noqa: F811
    fa = scenario["fattura"]
    assert fa.contratto_id is None
    assert not fatture.puo_segnare_oda(scenario["referente"], fa)
    risposta = _client("rossi").post(
        reverse("contratti:fattura_oda", args=[fa.pk]), {"vale_come_oda": "1"}
    )
    assert risposta.status_code == 403


def test_un_editor_estraneo_senza_la_fattura_in_carico_riceve_403(scenario, make_user):  # noqa: F811
    fa, c = scenario["fattura"], scenario["contratto"]
    fa = _convalidata(fa, c, scenario["referente"])
    make_user("verdi", role=EDITOR)
    m.AssegnazioneCluster.objects.create(username="verdi", cluster=f.cluster("TLC"))
    risposta = _client("verdi").post(
        reverse("contratti:fattura_oda", args=[fa.pk]), {"vale_come_oda": "1"}
    )
    assert risposta.status_code == 403
    c.refresh_from_db()
    assert c.vale_come_oda is False


def test_il_campo_e_nel_modulo_del_contratto(scenario):  # noqa: F811
    c = scenario["contratto"]
    pagina = _client("rossi").get(reverse("contratti:contratto_modifica", args=[c.pk]))
    assert pagina.status_code == 200
    assert "vale_come_oda" in pagina.content.decode()
