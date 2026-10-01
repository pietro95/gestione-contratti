"""Conferma e scarto delle proposte d'import: mai applicate in automatico."""

import datetime

import pytest
from django.urls import reverse

from contratti import models as m
from contratti.importer.carica import importa
from contratti.importer.proposte import (
    PropostaNonApplicabile,
    conferma_predecessore,
    conferma_raggruppamento,
    scarta,
)

from .conftest import OGGI, riga

pytestmark = pytest.mark.django_db


@pytest.fixture
def catena(excel):
    percorso = excel(
        [
            riga(Contratto="5800000001", **{"Data di attivazione": datetime.datetime(2024, 1, 1)}),
            riga(Contratto="5800000002", **{"Data di attivazione": datetime.datetime(2025, 1, 1)}),
            riga(
                Contratto="5800000003",
                Stato="Non rinnovare",
                **{"Data di attivazione": datetime.datetime(2026, 1, 1)},
            ),
        ]
    )
    importa(percorso, area="IT", oggi=OGGI)
    return m.PropostaRaggruppamento.objects.get()


def test_una_proposta_di_raggruppamento_e_due_di_catena(catena):
    assert catena.contratti.count() == 3
    assert m.PropostaPredecessore.objects.count() == 2
    assert m.Fabbisogno.objects.count() == 3


def test_conferma_raggruppamento(catena):
    fabbisogno = conferma_raggruppamento(catena)
    assert set(m.Contratto.objects.values_list("fabbisogno", flat=True)) == {fabbisogno.pk}
    # Destinazione: il fabbisogno del contratto più recente (con la sua decisione).
    assert fabbisogno.decisione == "dismettere"
    assert m.Fabbisogno.objects.filter(archiviato=True).count() == 2
    catena.refresh_from_db()
    assert catena.stato == "confermata"
    with pytest.raises(PropostaNonApplicabile):
        conferma_raggruppamento(catena)


def test_predecessore_richiede_prima_il_raggruppamento(catena):
    proposta = m.PropostaPredecessore.objects.first()
    with pytest.raises(PropostaNonApplicabile, match="raggruppamento"):
        conferma_predecessore(proposta)


def test_conferma_catena(catena):
    conferma_raggruppamento(catena)
    for proposta in m.PropostaPredecessore.objects.all():
        conferma_predecessore(proposta)
    c1, c2, c3 = m.Contratto.objects.order_by("data_inizio")
    assert (c2.predecessore, c3.predecessore) == (c1, c2)


def test_scarta(catena):
    scarta(catena)
    catena.refresh_from_db()
    assert catena.stato == "scartata"
    assert m.Fabbisogno.objects.filter(archiviato=False).count() == 3


def test_admin_azione_conferma(admin_client, catena):
    url = reverse("admin:contratti_propostaraggruppamento_changelist")
    risposta = admin_client.post(
        url, {"action": "conferma_raggruppamenti", "_selected_action": [catena.pk]}, follow=True
    )
    assert risposta.status_code == 200
    catena.refresh_from_db()
    assert catena.stato == "confermata"
    assert (
        admin_client.get(reverse("admin:contratti_propostapredecessore_changelist")).status_code
        == 200
    )


def test_admin_errore_mostrato(admin_client, catena):
    proposta = m.PropostaPredecessore.objects.first()
    url = reverse("admin:contratti_propostapredecessore_changelist")
    risposta = admin_client.post(
        url, {"action": "conferma_predecessori", "_selected_action": [proposta.pk]}, follow=True
    )
    assert "conferma prima il raggruppamento" in risposta.content.decode()
