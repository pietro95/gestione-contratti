# ruff: noqa: F811
"""Rigetto dei rilasci SAP di RDA, RdC e MAP (SPEC Rev49): servizi, maschera, email."""

import datetime
from decimal import Decimal

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from contratti import acquisti, fatture, notifiche
from contratti import models as m
from contratti.engine.acquisti import Fase, PassoFattura

from . import factories as f
from .test_notifiche import utenti  # noqa: F401

pytestmark = pytest.mark.django_db
D = datetime.date
Tipo = m.DocumentoEsecuzione.Tipo
NOTA = "Manca il centro di costo sul documento."


@pytest.fixture
def fattura(utenti):
    contratto = f.contratto(fornitore=f.fornitore("Fornitore Prova S.r.l."))
    f.voce(contratto)
    return m.Fattura.objects.create(
        fornitore=contratto.fornitore,
        contratto=contratto,
        numero="F-1/2026",
        data=D(2026, 10, 30),
        importo_documento=Decimal("100.00"),
        referente=utenti["ref"],
        data_presa_in_carico=D(2026, 11, 2),
        esito_convalida=m.Fattura.Esito.CONVALIDABILE,
        data_convalida=D(2026, 11, 2),
    )


@pytest.fixture
def rda_inserita(utenti):
    rda = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"),
        origine="manuale",
        descrizione="RDA di prova",
        referente_utente=utenti["ref"],
        numero_rda="5100000001",
        data_inserimento=D(2026, 11, 1),
    )
    m.PosizioneRDA.objects.create(
        rda=rda, numero=1, descrizione_breve="Posizione", importo_unitario=Decimal("10.00")
    )
    acquisti.invia(rda, utenti["ref"], D(2026, 10, 30))
    return rda


def _passo(fa):
    fa.refresh_from_db()
    return fatture.passo_fattura(fa, D(2026, 11, 12))


# --- RDA ---------------------------------------------------------------------------------


def test_rda_rigettata_torna_da_inserire_e_conserva_il_numero(utenti, rda_inserita):
    assert acquisti.fase(rda_inserita, D(2026, 11, 12)) == Fase.INSERITA
    esito = acquisti.rigetta_rda([rda_inserita], NOTA, utenti["ril"], D(2026, 11, 10))
    assert esito.fatte == [rda_inserita] and not esito.rifiutate
    rda_inserita.refresh_from_db()
    assert rda_inserita.numero_rda == "5100000001"
    assert rda_inserita.data_inserimento == D(2026, 11, 1)
    assert acquisti.fase(rda_inserita, D(2026, 11, 12)) == Fase.INVIATA
    assert acquisti.rda_da_rilasciare() == []
    assert acquisti.ultimo_rigetto(rda_inserita).nota == NOTA


def test_rda_rigettata_non_si_rilascia(utenti, rda_inserita):
    acquisti.rigetta_rda([rda_inserita], NOTA, utenti["ril"])
    esito = acquisti.rilascia_rda([rda_inserita], utenti["ril"])
    assert not esito.fatte and "rigettata" in esito.rifiutate[0][1]
    esito = acquisti.rigetta_rda([rda_inserita], NOTA, utenti["ril"])
    assert not esito.fatte and "rigettata" in esito.rifiutate[0][1]


def test_rda_riportando_i_dati_sap_si_ripresenta(
    utenti, rda_inserita, django_capture_on_commit_callbacks
):
    acquisti.rigetta_rda([rda_inserita], NOTA, utenti["ril"])
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.aggiorna_dati_sap(rda_inserita, "5100000001", D(2026, 11, 11), utenti["amm"])
    assert acquisti.fase(rda_inserita) == Fase.INSERITA
    assert acquisti.ultimo_rigetto(rda_inserita) is None
    assert acquisti.rda_da_rilasciare() == [rda_inserita]
    # La RDA torna al rilascio con un nuovo avviso all'addetto.
    assert any("da rilasciare" in x.subject for x in mail.outbox)


def test_rigetto_chiede_la_nota_e_la_funzione(utenti, rda_inserita):
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.rigetta_rda([rda_inserita], "  ", utenti["ril"])
    with pytest.raises(PermissionDenied):
        acquisti.rigetta_rda([rda_inserita], NOTA, utenti["amm"])


def test_rigetto_non_vale_per_rda_rilasciata(utenti, rda_inserita):
    acquisti.rilascia_rda([rda_inserita], utenti["ril"])
    esito = acquisti.rigetta_rda([rda_inserita], NOTA, utenti["ril"])
    assert not esito.fatte and esito.rifiutate


# --- RdC e MAP -----------------------------------------------------------------------------


def test_rdc_rigettata_la_fattura_riprende_il_passo_e_il_numero_resta(utenti, fattura):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    assert _passo(fattura) == PassoFattura.RDC_RILASCIO
    esito = fatture.rigetta_documenti([rdc.pk], NOTA, utenti["ril"], D(2026, 11, 10))
    assert esito.fatte == [rdc] and not esito.rifiutate
    rdc.refresh_from_db()
    assert rdc.numero == "4600000001" and rdc.rigettato_il == D(2026, 11, 10)
    assert rdc.rigettato_da == utenti["ril"] and rdc.nota_rigetto == NOTA
    assert _passo(fattura) == PassoFattura.RDC
    assert fatture.documenti_da_rilasciare() == []
    # Non si può registrare una seconda RdC: si corregge quella rigettata.
    with pytest.raises(acquisti.OperazioneNonAmmessa, match="rigettata"):
        fatture.registra_documento(fattura, Tipo.ODA, "4600000002", D(2026, 11, 4))
    esito = fatture.rilascia_documenti([rdc.pk], utenti["ril"])
    assert not esito.fatte and "rigettato" in esito.rifiutate[0][1]


def test_la_correzione_ripresenta_il_documento(utenti, fattura, django_capture_on_commit_callbacks):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    fatture.rigetta_documenti([rdc.pk], NOTA, utenti["ril"])
    rdc.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        fatture.modifica_documento(
            fattura, rdc, Tipo.ODA, "4600000009", D(2026, 11, 3), utenti["amm"]
        )
    rdc.refresh_from_db()
    assert rdc.numero == "4600000009" and rdc.rigettato_il is None and rdc.nota_rigetto == ""
    assert _passo(fattura) == PassoFattura.RDC_RILASCIO
    assert fatture.documenti_da_rilasciare() == [rdc]
    # La nota del rigetto resta nella storia delle modifiche.
    assert rdc.history.filter(nota_rigetto=NOTA).exists()
    assert any("da rilasciare" in x.subject for x in mail.outbox)


def test_map_rigettato_e_migo_non_rigettabile(utenti, fattura):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    fatture.rilascia_documenti([rdc.pk], utenti["ril"])
    map_ = fatture.registra_documento(fattura, Tipo.MAP, "5100000001", D(2026, 11, 4))
    migo = fatture.registra_documento(fattura, Tipo.MIGO, "5000000001", D(2026, 11, 4))
    esito = fatture.rigetta_documenti([migo.pk], NOTA, utenti["ril"])
    assert not esito.fatte and esito.rifiutate
    fatture.rigetta_documenti([map_.pk], NOTA, utenti["ril"])
    # Il MIGO registrato basta: il passo non torna a «MAP da fare».
    assert _passo(fattura) == PassoFattura.TRASFERIMENTO


def test_documento_rigettato_si_puo_rimuovere_e_il_numero_resta(utenti, fattura):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    fatture.rigetta_documenti([rdc.pk], NOTA, utenti["ril"])
    fatture.rimuovi_documento(fattura, rdc)
    rdc.refresh_from_db()
    assert rdc.archiviato and rdc.numero == "4600000001"


# --- Maschera ------------------------------------------------------------------------------


def _accedi(client, utente):
    client.force_login(utente)


def test_maschera_mostra_coge_e_wbs_e_rigetto_massivo(utenti, fattura, rda_inserita, client):
    conto = m.ContoCoge.objects.create(codice="6001", descrizione="Conto", valido_dal=D(2020, 1, 1))
    wbs = m.WBS.objects.create(codice_wbs="WBS-1", descrizione="Progetto")
    fattura.conto, fattura.wbs = conto, wbs
    fattura.save()
    rda_inserita.posizioni.update(conto=conto, wbs=wbs)
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    _accedi(client, utenti["ril"])
    html = client.get(reverse("contratti:rilasci")).content.decode()
    assert "COGE" in html and "WBS" in html and "6001" in html and "WBS-1" in html
    assert "Rigetta i selezionati" in html
    r = client.post(
        reverse("contratti:rilasci_rigetta"),
        {"rda": [rda_inserita.pk], "documento": [rdc.pk], "nota": NOTA},
    )
    assert r.status_code == 302
    rdc.refresh_from_db()
    assert rdc.rigettato_il is not None
    assert acquisti.rigettata(m.RichiestaAcquisto.objects.get(pk=rda_inserita.pk))


def test_rigetto_massivo_senza_nota_non_fa_nulla(utenti, fattura, client):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    _accedi(client, utenti["ril"])
    client.post(reverse("contratti:rilasci_rigetta"), {"documento": [rdc.pk], "nota": ""})
    rdc.refresh_from_db()
    assert rdc.rigettato_il is None


@pytest.mark.parametrize("utente", ["amm", "ref", "lettore"])
def test_403_sul_rigetto(utenti, fattura, client, utente):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    _accedi(client, utenti[utente])
    r = client.post(reverse("contratti:rilasci_rigetta"), {"documento": [rdc.pk], "nota": NOTA})
    assert r.status_code == 403
    rdc.refresh_from_db()
    assert rdc.rigettato_il is None


def test_schede_mostrano_il_rigetto(utenti, fattura, rda_inserita, client):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    fatture.rigetta_documenti([rdc.pk], NOTA, utenti["ril"])
    acquisti.rigetta_rda([rda_inserita], "Numero errato", utenti["ril"])
    _accedi(client, utenti["amm"])
    assert NOTA in client.get(reverse("contratti:fattura", args=[fattura.pk])).content.decode()
    html = client.get(reverse("contratti:rda", args=[rda_inserita.pk])).content.decode()
    assert "Rigettata dal rilascio" in html and "Numero errato" in html


# --- Email ---------------------------------------------------------------------------------


def test_email_del_rigetto_a_tutti_gli_interessati(
    utenti, fattura, rda_inserita, django_capture_on_commit_callbacks
):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        fatture.rigetta_documenti([rdc.pk], NOTA, utenti["ril"])
        acquisti.rigetta_rda([rda_inserita], "Numero errato", utenti["ril"])
    rigetti = [x for x in mail.outbox if "Rigetto dal rilascio" in x.subject]
    destinatari = {a for x in rigetti for a in x.to}
    # Addetto amministrativo e referente; chi ha rigettato non riceve il proprio avviso.
    assert destinatari == {"amm@esempio.test", "ref@esempio.test"}
    assert any(NOTA in x.body for x in rigetti) and any("Numero errato" in x.body for x in rigetti)
    assert not any("ril@esempio.test" in x.to for x in rigetti)


def test_chi_ha_registrato_riceve_l_avviso(utenti, fattura):
    rdc = fatture.registra_documento(fattura, Tipo.ODA, "4600000001", D(2026, 11, 3))
    altro = utenti["altro"]
    rdc._history_user = altro
    rdc._change_reason = "Registrato dalla fattura F-1/2026"
    rdc.save()
    assert notifiche._chi_ha_registrato(rdc, "Registrato dalla fattura") == altro
