"""Valori iniziali caricati dalla data migration e permessi dei ruoli."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import Group

from contratti import models as m

pytestmark = pytest.mark.django_db


def test_procedure_iniziali_provvisorie():
    lead_time = dict(m.Procedura.objects.values_list("codice", "lead_time_mesi"))
    assert lead_time == {
        "affidamento_diretto": 2,
        "mepa_oda": 3,
        "rdo": 4,
        "negoziata": 6,
        "aperta": 9,
        "adesione_convenzione": 2,
        "da_verificare": 6,  # migration 0008, per l'import Excel
    }
    assert not m.Procedura.objects.filter(provvisorio=False).exists()


def test_parametri_iniziali_provvisori():
    valori = dict(m.Parametro.objects.values_list("chiave", "valore"))
    assert valori == {
        "giorni_pagamento": Decimal("60"),
        "pagamento_fine_mese": Decimal("1"),
        "adeguamento_pct": Decimal("0"),
        "finestra_alert_mesi": Decimal("3"),
        "orizzonte_anni": Decimal("3"),
    }
    assert set(valori) == set(m.Parametro.Chiave.values)
    assert not m.Parametro.objects.filter(provvisorio=False).exists()


def test_soglia_affidamento_diretto():
    soglia = m.Soglia.objects.get(codice="affidamento_diretto_servizi_forniture")
    assert soglia.importo == Decimal("140000.00")
    assert soglia.provvisorio


def test_categorie_iniziali():
    assert set(m.Categoria.objects.values_list("nome", flat=True)) == {
        "Licenze software",
        "Manutenzione hardware",
        "Connettività",
        "Servizi professionali",
        "Noleggio",
        "Da classificare",  # migration 0008, per l'import Excel
    }


def test_nessun_conto_reale_caricato():
    # Il piano dei conti reale si carica sulla VM, mai dal repository.
    assert not m.ContoCoge.objects.exists()


def _codenames(group_name):
    return set(Group.objects.get(name=group_name).permissions.values_list("codename", flat=True))


def test_reader_solo_lettura():
    perms = _codenames("Reader")
    assert perms
    assert all(p.startswith("view_") for p in perms)
    assert "view_contratto" in perms and "view_rata" in perms and "view_quotaperiodo" in perms


def test_editor_aggiunge_e_modifica_il_dominio():
    perms = _codenames("Editor")
    for azione in ("add", "change", "view"):
        for modello in (
            "contratto",
            "vocecontratto",
            "fabbisogno",
            "fornitore",
            "rata",
            "quotaperiodo",
        ):
            assert f"{azione}_{modello}" in perms
    # La configurazione la cambia solo Admin.
    for modello in ("procedura", "soglia", "parametro", "contocoge"):
        assert f"change_{modello}" not in perms
        assert f"view_{modello}" in perms


@pytest.mark.parametrize("gruppo", ["Editor", "Reader"])
def test_nessuno_puo_cancellare(gruppo):
    assert not any(p.startswith("delete_") for p in _codenames(gruppo))
