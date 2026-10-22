"""Rilascio su SAP di RdC, MAP e MIGO: servizi, passi sul database, maschera, permessi."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from accounts.roles import ADMIN, EDITOR, READER
from contratti import acquisti, fatture
from contratti import models as m
from contratti.engine.acquisti import Fase, PassoFattura

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


def test_nemmeno_l_admin_senza_la_funzione_rilascia(scenario, client, make_user):
    rdc = fatture.registra_documento(scenario["fattura"], Tipo.ODA, "4600000001", D(2026, 10, 2))
    make_user("capo", role=ADMIN, is_superuser=True, is_staff=True)
    _login(client, "capo")
    azione = reverse("contratti:rilasci_azione")
    assert client.post(azione, {"documento": [rdc.pk]}).status_code == 403
    m.FunzioneUtente.objects.create(
        username="capo", funzione=m.FunzioneUtente.Funzione.RILASCIO_SAP
    )
    client.post(azione, {"documento": [rdc.pk], "fattura": scenario["fattura"].pk})
    rdc.refresh_from_db()
    assert rdc.data_rilascio is not None


def test_scheda_fattura_mostra_il_rilascio(scenario, client):
    fatture.registra_documento(scenario["fattura"], Tipo.ODA, "4600000001", D(2026, 10, 2))
    _login(client, "addetto")
    pagina = client.get(reverse("contratti:fattura", args=[scenario["fattura"].pk]))
    assert pagina.status_code == 200
    html = pagina.content.decode()
    assert "Rilascia" in html


# --- RDA -----------------------------------------------------------------------------------


@pytest.fixture
def rda_inserita():
    return m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"),
        origine="manuale",
        descrizione="RDA di prova",
        numero_rda="5100000001",
        data_inserimento=D(2026, 10, 1),
    )


def test_rda_inserita_si_rilascia_solo_con_la_funzione(scenario, rda_inserita):
    assert acquisti.rda_da_rilasciare() == [rda_inserita]
    with pytest.raises(PermissionDenied):
        acquisti.rilascia_rda([rda_inserita], scenario["rossi"])
    esito = acquisti.rilascia_rda([rda_inserita], scenario["addetto"], D(2026, 10, 5))
    assert esito.fatte == [rda_inserita] and not esito.rifiutate
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio == D(2026, 10, 5)
    assert rda_inserita.rilasciata_da == scenario["addetto"]
    assert acquisti.fase(rda_inserita, D(2026, 10, 6)) == Fase.RILASCIATA
    assert acquisti.rda_da_rilasciare() == []


def test_rda_non_rilasciabile_se_non_inserita_o_gia_rilasciata(scenario, rda_inserita):
    bozza = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"), origine="manuale", descrizione="Bozza"
    )
    esito = acquisti.rilascia_rda([bozza], scenario["addetto"])
    assert not esito.fatte and "non è ancora inserita" in esito.rifiutate[0][1]
    acquisti.rilascia_rda([rda_inserita], scenario["addetto"])
    esito = acquisti.rilascia_rda([rda_inserita], scenario["addetto"])
    assert not esito.fatte and "già rilasciata" in esito.rifiutate[0][1]


def test_annulla_rilascio_rda(scenario, rda_inserita):
    acquisti.rilascia_rda([rda_inserita], scenario["addetto"])
    rda_inserita.refresh_from_db()
    with pytest.raises(PermissionDenied):
        acquisti.annulla_rilascio_rda(rda_inserita, scenario["rossi"])
    acquisti.annulla_rilascio_rda(rda_inserita, scenario["addetto"])
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is None and rda_inserita.rilasciata_da is None
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.annulla_rilascio_rda(rda_inserita, scenario["addetto"])


def test_il_form_dei_dati_sap_non_scrive_il_rilascio(scenario, rda_inserita, client):
    """Numero e inserimento li riporta l'Editor; la data di rilascio resta dell'addetto."""
    _login(client, "rossi")
    client.post(
        reverse("contratti:rda_dati_sap", args=[rda_inserita.pk]),
        {
            "numero_rda": "5100000001",
            "data_inserimento": "01/10/2026",
            "data_rilascio": "05/10/2026",
        },
    )
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is None


@pytest.mark.parametrize("utente, ruolo", [("neri", READER), ("bianchi", EDITOR)])
def test_403_sul_rilascio_della_rda(scenario, rda_inserita, client, make_user, utente, ruolo):
    make_user(utente, role=ruolo)
    _login(client, utente)
    assert (
        client.post(reverse("contratti:rilasci_azione"), {"rda": [rda_inserita.pk]}).status_code
        == 403
    )
    acquisti.rilascia_rda([rda_inserita], scenario["addetto"])
    assert (
        client.post(reverse("contratti:rilascio_rda_annulla", args=[rda_inserita.pk])).status_code
        == 403
    )
    rda_inserita.refresh_from_db()
    assert rda_inserita.data_rilascio is not None


def test_maschera_e_scheda_della_rda(scenario, rda_inserita, client):
    _login(client, "addetto")
    pagina = client.get(reverse("contratti:rilasci")).content.decode()
    assert "5100000001" in pagina and 'name="rda"' in pagina
    assert (
        "Rilascia la RDA"
        in client.get(reverse("contratti:rda", args=[rda_inserita.pk])).content.decode()
    )
    client.post(
        reverse("contratti:rilasci_azione"),
        {"rda": [rda_inserita.pk], "ritorno_rda": rda_inserita.pk},
    )
    rda_inserita.refresh_from_db()
    assert rda_inserita.rilasciata_da.username == "addetto"
    scheda = client.get(reverse("contratti:rda", args=[rda_inserita.pk])).content.decode()
    assert "Annulla il rilascio" in scheda and "Rilascia la RDA" not in scheda
    # Sola lettura per chi non rilascia: vede la coda, senza selezione.
    client.logout()
    assert client.login(username="rossi", password=PASSWORD)
    m.RichiestaAcquisto.objects.filter(pk=rda_inserita.pk).update(data_rilascio=None)
    assert 'name="rda"' not in client.get(reverse("contratti:rilasci")).content.decode()


def test_migration_marca_rilasciati_i_documenti_gia_registrati(scenario):
    import importlib

    from django.apps import apps

    migrazione = importlib.import_module("contratti.migrations.0047_documenti_gia_rilasciati")
    fa, contratto = scenario["fattura"], scenario["fattura"].contratto
    rdc = m.DocumentoEsecuzione.objects.create(
        contratto=contratto, fattura=fa, tipo=Tipo.ODA, numero="1", data=D(2026, 10, 2)
    )
    ddt = m.DocumentoEsecuzione.objects.create(
        contratto=contratto, tipo=Tipo.DDT, numero="2", data=D(2026, 10, 3)
    )
    senza_fattura = m.DocumentoEsecuzione.objects.create(
        contratto=contratto, tipo=Tipo.MAP, numero="3", data=D(2026, 10, 4)
    )
    migrazione.marca_rilasciati(apps, None)
    for d in (rdc, ddt, senza_fattura):
        d.refresh_from_db()
    assert rdc.data_rilascio == D(2026, 10, 2) and rdc.rilasciato_da is None
    assert ddt.data_rilascio is None and senza_fattura.data_rilascio is None
