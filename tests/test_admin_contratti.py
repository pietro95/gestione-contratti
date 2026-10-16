"""Admin come back-office: navigabile, senza cancellazioni, rate modificate tracciate."""

import datetime
from decimal import Decimal

import pytest
from django.contrib import admin
from django.urls import reverse

from accounts.roles import EDITOR, READER
from contratti import models as m

from . import factories as f

pytestmark = pytest.mark.django_db

D = datetime.date
MODELLI = [model for model in admin.site._registry if model._meta.app_label == "contratti"]


def _richiesta_admin():
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    richiesta = RequestFactory().get("/")
    richiesta.user = get_user_model()(is_superuser=True, is_staff=True)
    return richiesta


def url(model, view, *args):
    return reverse(f"admin:contratti_{model._meta.model_name}_{view}", args=args)


@pytest.fixture
def dati():
    """Un'istanza per ogni modello del registro."""
    c = f.contratto(numero_contratto="5800000001", cig="Z000000001")
    v = f.voce(c, massimale_variabile=Decimal("500"), stima_consumo_pct=Decimal("30"))
    p = f.piano(v)
    f.rata(p)
    proroga = m.Proroga.objects.create(
        contratto=c, data_atto=D(2026, 11, 1), nuova_data_fine=D(2027, 6, 30)
    )
    m.OpzioneContratto.objects.create(contratto=c, tipo="rinnovo", mesi=12)
    m.StatoPratica.objects.create(contratto=c, stato="non_avviata", data=D(2026, 9, 1))
    m.WBS.objects.create(codice_wbs="WBS-PROVA-01", descrizione="Progetto prova")
    m.AutorizzazioneExtraBudget.objects.create(
        codice="EB-PROVA-01",
        descrizione="Attività spot di prova",
        cluster=f.cluster(),
        protocollo="PROT-PROVA",
        data_autorizzazione=datetime.date(2026, 1, 1),
        importo_autorizzato=Decimal("1000.00"),
    )
    it, _ = m.Cluster.objects.get_or_create(codice="IT", defaults={"nome": "IT"})
    m.Sottocluster.objects.create(cluster=it, nome="Sottocluster di prova")
    m.FonteFinanziamento.objects.create(nome="Fonte di prova")
    m.AssegnazioneCluster.objects.create(username="responsabile.prova", cluster=it)
    successore = f.contratto(fabbisogno=c.fabbisogno, numero_contratto="5800000002")
    m.PropostaPredecessore.objects.create(
        predecessore=c, successore=successore, motivazione="prova"
    )
    m.PropostaRaggruppamento.objects.create(motivazione="prova", chiave="k").contratti.set(
        [c, successore]
    )
    m.ContoCoge.objects.create(
        codice="6000000001", descrizione="Conto fittizio", valido_dal=D(2020, 1, 1)
    )
    from django.contrib.auth import get_user_model

    m.Importazione.objects.create(
        tipo="date_emissione",
        nome_file="prova.csv",
        contenuto=b"",
        sha256="0" * 64,
        dimensione=0,
        utente=get_user_model().objects.create_user("autore_import_prova"),
    )
    # Processo d'acquisto (F11.1).
    m.FunzioneUtente.objects.create(username="addetto.prova", funzione="amministrazione_acquisti")
    m.RichiedenteSAP.objects.create(codice="999901", descrizione="Ufficio di prova")
    m.GruppoAcquisti.objects.create(codice="G01", descrizione="Gruppo di prova")
    m.CentroCosto.objects.create(codice="C0001", descrizione="Centro di prova")
    m.GruppoMerci.objects.create(codice="GM-TEST01", descrizione="Gruppo merci di prova")
    rda = m.RichiestaAcquisto.objects.create(
        origine="manuale", cluster=it, descrizione="RDA di prova", numero_rda="5100000001"
    )
    m.PosizioneRDA.objects.create(rda=rda, numero=1, descrizione_breve="Prova", importo_unitario=1)
    m.EventoRDA.objects.create(rda=rda, tipo="invio", data=D(2026, 9, 1))
    fattura = m.Fattura.objects.create(
        contratto=c, numero="FA-PROVA", data=D(2026, 3, 1), importo_documento=Decimal("100")
    )
    m.DocumentoEsecuzione.objects.create(
        contratto=c, tipo="MAP", data=D(2026, 3, 5), fattura=fattura
    )
    return {"contratto": c, "voce": v, "piano": p, "proroga": proroga}


def test_tutti_i_modelli_registrati():
    attesi = {
        "procedura", "soglia", "parametro", "wbs", "cluster", "contocoge",
        "fornitore", "fabbisogno", "contratto", "proroga", "vocecontratto",
        "pianofatturazione", "rata", "statopratica", "richiestaacquisto", "fattura",
        "documentoesecuzione", "richiedentesap", "gruppoacquisti", "gruppomerci", "funzioneutente",
    }  # fmt: skip
    assert attesi <= {model._meta.model_name for model in MODELLI}


@pytest.mark.parametrize("model", MODELLI, ids=lambda model: model._meta.model_name)
def test_admin_navigabile(admin_client, dati, model):
    obj = model.objects.first()
    assert admin_client.get(url(model, "changelist")).status_code == 200
    assert admin_client.get(url(model, "changelist"), {"q": "prova"}).status_code == 200
    model_admin = admin.site._registry[model]
    attesa_add = 200 if model_admin.has_add_permission(_richiesta_admin()) else 403
    assert admin_client.get(url(model, "add")).status_code == attesa_add
    assert admin_client.get(url(model, "change", obj.pk)).status_code == 200
    assert admin_client.get(url(model, "history", obj.pk)).status_code == 200


@pytest.mark.parametrize("model", MODELLI, ids=lambda model: model._meta.model_name)
def test_admin_senza_cancellazione(admin_client, dati, model):
    obj = model.objects.first()
    assert admin_client.get(url(model, "delete", obj.pk)).status_code == 403
    response = admin_client.get(url(model, "changelist"))
    assert "delete_selected" not in response.content.decode()


def test_archiviazione_da_admin_con_storia(admin_client, dati):
    c = dati["contratto"]
    response = admin_client.post(
        url(m.Contratto, "changelist"),
        {"action": "archivia", "_selected_action": [c.pk]},
    )
    assert response.status_code == 302
    c.refresh_from_db()
    assert c.archiviato
    assert m.Contratto.objects.filter(pk=c.pk).exists()
    ultima = c.history.first()
    assert ultima.archiviato and ultima.history_user.is_superuser


def test_rata_modificata_da_admin_marcata(admin_client, dati):
    rata = dati["piano"].rate.get()
    assert not rata.modificata_manualmente
    response = admin_client.post(
        url(m.Rata, "change", rata.pk),
        {
            "piano": rata.piano_id,
            "numero": 1,
            "data_fattura": "01/01/2026",
            "data_pagamento_stimata": "01/03/2026",
            "importo": "1100.00",
            "numero_fattura": "",
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    rata.refresh_from_db()
    assert rata.importo == Decimal("1100.00")
    assert rata.modificata_manualmente


def test_rata_salvata_senza_modifiche_non_marcata(admin_client, dati):
    rata = dati["piano"].rate.get()
    admin_client.post(
        url(m.Rata, "change", rata.pk),
        {
            "piano": rata.piano_id,
            "numero": 1,
            "data_fattura": "01/01/2026",
            "data_pagamento_stimata": "01/03/2026",
            "importo": "1000.00",
            "numero_fattura": "",
        },
    )
    rata.refresh_from_db()
    assert not rata.modificata_manualmente


def test_avviso_codice_sap_condiviso(admin_client):
    f.fornitore("Primo", codice_sap="999001")
    response = admin_client.post(
        url(m.Fornitore, "add"),
        {"ragione_sociale": "Secondo", "partita_iva": "", "codice_sap": "999001", "note": ""},
        follow=True,
    )
    assert "usato anche da: Primo" in response.content.decode()


@pytest.mark.parametrize("role", [EDITOR, READER])
def test_admin_chiuso_a_editor_e_reader(client, make_user, role):
    # L'admin è solo per Admin (is_staff); Editor e Reader useranno l'interfaccia di F4.
    make_user("utente", role=role)
    client.login(username="utente", password="password-locale-di-prova")
    for view in ("changelist", "add"):
        response = client.get(url(m.Contratto, view))
        assert response.status_code == 302
        assert response.url.startswith(reverse("admin:login"))
