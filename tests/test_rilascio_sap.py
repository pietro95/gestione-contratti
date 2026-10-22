"""Rilascio su SAP di RdC, MAP e MIGO: servizi, passi sul database, maschera, permessi."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from accounts.roles import ADMIN, EDITOR, READER
from contratti import acquisti, fatture
from contratti import models as m
from contratti.engine.acquisti import PassoFattura

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
Tipo = m.DocumentoEsecuzione.Tipo
PASSWORD = "password-locale-di-prova"


@pytest.fixture
def scenario(make_user):
    rossi = make_user("rossi", role=EDITOR)
    addetto = make_user("addetto", role=EDITOR)
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
    return {"fattura": fattura, "rossi": rossi, "addetto": addetto}


def _passo(fattura):
    fattura.refresh_from_db()
    return fatture.passo_fattura(fattura, D(2026, 10, 7))


def test_flusso_completo_con_i_rilasci(scenario):
    fa, addetto = scenario["fattura"], scenario["addetto"]
    assert _passo(fa) == PassoFattura.RDC
    rdc = fatture.registra_documento(fa, Tipo.ODA, "4600000001", D(2026, 10, 2))
    assert _passo(fa) == PassoFattura.RDC_RILASCIO
    esito = fatture.rilascia_documenti([rdc.pk], addetto, D(2026, 10, 3))
    assert [d.pk for d in esito.fatte] == [rdc.pk] and not esito.rifiutate
    rdc.refresh_from_db()
    assert rdc.data_rilascio == D(2026, 10, 3) and rdc.rilasciato_da == addetto
    assert _passo(fa) == PassoFattura.MAP_MIGO
    map_ = fatture.registra_documento(fa, Tipo.MAP, "5100000001", D(2026, 10, 4))
    assert _passo(fa) == PassoFattura.MAP_MIGO_RILASCIO
    fatture.rilascia_documenti([map_.pk], addetto, D(2026, 10, 5))
    assert _passo(fa) == PassoFattura.TRASFERIMENTO


def test_rilascio_non_ripetibile_e_annullabile(scenario):
    fa, addetto = scenario["fattura"], scenario["addetto"]
    rdc = fatture.registra_documento(fa, Tipo.ODA, "4600000001", D(2026, 10, 2))
    fatture.rilascia_documenti([rdc.pk], addetto)
    esito = fatture.rilascia_documenti([rdc.pk], addetto)
    assert not esito.fatte and "già rilasciato" in esito.rifiutate[0][1]
    # Un documento rilasciato non si corregge né si rimuove senza annullare il rilascio.
    rdc.refresh_from_db()
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.rimuovi_documento(fa, rdc)
    fatture.annulla_rilascio(rdc, addetto)
    rdc.refresh_from_db()
    assert rdc.data_rilascio is None and rdc.rilasciato_da is None
    fatture.rimuovi_documento(fa, rdc)


def test_coda_da_rilasciare(scenario):
    fa = scenario["fattura"]
    rdc = fatture.registra_documento(fa, Tipo.ODA, "4600000001", D(2026, 10, 2))
    assert [d.pk for d in fatture.documenti_da_rilasciare()] == [rdc.pk]
    assert fatture.documenti_da_rilasciare(Tipo.MAP) == []
    fatture.rilascia_documenti([rdc.pk], scenario["addetto"])
    assert fatture.documenti_da_rilasciare() == []
    # Fuori coda: fattura trasferita o fuori registro.
    map_ = fatture.registra_documento(fa, Tipo.MAP, "5100000001", D(2026, 10, 4))
    fa.fuori_registro = True
    fa.save(update_fields=["fuori_registro"])
    assert map_ not in fatture.documenti_da_rilasciare()


def test_chi_non_e_addetto_non_rilascia(scenario):
    fa = scenario["fattura"]
    rdc = fatture.registra_documento(fa, Tipo.ODA, "4600000001", D(2026, 10, 2))
    with pytest.raises(PermissionDenied):
        fatture.rilascia_documenti([rdc.pk], scenario["rossi"])


def test_funzione_archiviata_toglie_il_rilascio(scenario):
    m.FunzioneUtente.objects.filter(username="addetto").update(archiviato=True)
    assert not fatture.puo_rilasciare(scenario["addetto"])


# --- Viste ---------------------------------------------------------------------------------


def _login(client, nome):
    assert client.login(username=nome, password=PASSWORD)
    return client


def test_maschera_visibile_a_tutti_azioni_solo_all_addetto(scenario, client, make_user):
    rdc = fatture.registra_documento(scenario["fattura"], Tipo.ODA, "4600000001", D(2026, 10, 2))
    make_user("neri", role=READER)
    pagina = _login(client, "neri").get(reverse("contratti:rilasci"))
    assert pagina.status_code == 200
    assert "4600000001" in pagina.content.decode()
    assert 'name="documento"' not in pagina.content.decode()
    client.logout()
    pagina = _login(client, "addetto").get(reverse("contratti:rilasci"))
    assert 'name="documento"' in pagina.content.decode()
    assert rdc.numero in pagina.content.decode()


def test_rilascio_dalla_maschera(scenario, client):
    rdc = fatture.registra_documento(scenario["fattura"], Tipo.ODA, "4600000001", D(2026, 10, 2))
    _login(client, "addetto")
    risposta = client.post(reverse("contratti:rilasci_azione"), {"documento": [rdc.pk]})
    assert risposta.status_code == 302
    rdc.refresh_from_db()
    assert rdc.data_rilascio is not None and rdc.rilasciato_da.username == "addetto"


@pytest.mark.parametrize("utente, ruolo", [("neri", READER), ("bianchi", EDITOR)])
def test_403_senza_la_funzione(scenario, client, make_user, utente, ruolo):
    """Reader e Editor senza funzione non rilasciano né annullano il rilascio."""
    rdc = fatture.registra_documento(scenario["fattura"], Tipo.ODA, "4600000001", D(2026, 10, 2))
    fatture.rilascia_documenti([rdc.pk], scenario["addetto"])
    nuovo = fatture.registra_documento(scenario["fattura"], Tipo.MAP, "5100000001", D(2026, 10, 4))
    make_user(utente, role=ruolo)
    _login(client, utente)
    assert (
        client.post(reverse("contratti:rilasci_azione"), {"documento": [nuovo.pk]}).status_code
        == 403
    )
    assert client.post(reverse("contratti:rilascio_annulla", args=[rdc.pk])).status_code == 403
    nuovo.refresh_from_db()
    assert nuovo.data_rilascio is None


def test_admin_rilascia(scenario, client, make_user):
    rdc = fatture.registra_documento(scenario["fattura"], Tipo.ODA, "4600000001", D(2026, 10, 2))
    make_user("capo", role=ADMIN, is_superuser=True, is_staff=True)
    _login(client, "capo")
    client.post(
        reverse("contratti:rilasci_azione"),
        {"documento": [rdc.pk], "fattura": scenario["fattura"].pk},
    )
    rdc.refresh_from_db()
    assert rdc.data_rilascio is not None


def test_scheda_fattura_mostra_il_rilascio(scenario, client):
    fatture.registra_documento(scenario["fattura"], Tipo.ODA, "4600000001", D(2026, 10, 2))
    _login(client, "addetto")
    pagina = client.get(reverse("contratti:fattura", args=[scenario["fattura"].pk]))
    assert pagina.status_code == 200
    html = pagina.content.decode()
    assert "Rilascia" in html
