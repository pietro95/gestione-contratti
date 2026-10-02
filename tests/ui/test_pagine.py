"""Pagine di lettura: navigabili da tutti i ruoli, contenuti calcolati dal motore."""

import datetime

import pytest
from django.urls import reverse

from accounts.roles import ADMIN, EDITOR, READER

pytestmark = pytest.mark.django_db
D = datetime.date


def pagine(d):
    return [
        reverse("home"),
        reverse("contratti:cruscotto"),
        reverse("contratti:contratti"),
        reverse("contratti:contratto", args=[d["contratto"].pk]),
        reverse("contratti:fabbisogni"),
        reverse("contratti:fabbisogno", args=[d["fabbisogno"].pk]),
        reverse("contratti:fabbisogno", args=[d["nuovo"].pk]),
        reverse("contratti:fornitori"),
        reverse("contratti:fornitore", args=[d["fornitore"].pk]),
        reverse("contratti:proposte"),
    ]


@pytest.mark.parametrize("ruolo", [READER, EDITOR, ADMIN])
def test_pagine_di_lettura(come, dati, ruolo):
    client = come(ruolo)
    for url in pagine(dati):
        assert client.get(url).status_code == 200, url


def test_anonimo_non_vede_le_pagine(client, dati):
    for url in pagine(dati):
        assert client.get(url).status_code == 302, url


def test_reader_non_vede_i_pulsanti_di_modifica(reader, dati):
    html = reader.get(reverse("contratti:contratto", args=[dati["contratto"].pk])).content.decode()
    assert "Registra rinnovo" not in html
    assert "Genera scadenzario" not in html
    html = reader.get(reverse("contratti:proposte")).content.decode()
    assert "btn-success" not in html  # nessun pulsante Conferma


def test_editor_vede_i_pulsanti(editor, dati):
    html = editor.get(reverse("contratti:contratto", args=[dati["contratto"].pk])).content.decode()
    for testo in ("Registra rinnovo", "Registra proroga", "Aggiungi voce", "Genera scadenzario"):
        assert testo in html


def test_dettaglio_contratto_date_e_importi(reader, dati):
    html = reader.get(
        reverse("contratti:contratto", args=[dati["contratto"].pk]) + "?oggi=2026-09-30"
    ).content.decode()
    assert "31/12/2026" in html  # fine effettiva
    assert "10.000,00 €" in html  # importi all'italiana
    assert "Storico modifiche" in html


def test_elenco_contratti_filtri(reader, dati):
    url = reverse("contratti:contratti")
    assert "5800000001" in reader.get(url, {"q": "5800000001"}).content.decode()
    assert "5800000001" not in reader.get(url, {"q": "inesistente"}).content.decode()
    assert "5800000001" in reader.get(url, {"anno": "2026"}).content.decode()
    assert "5800000001" not in reader.get(url, {"anno": "2024"}).content.decode()
    # Risposta parziale per htmx: solo la tabella.
    parziale = reader.get(url, {"q": "5800000001"}, HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in parziale and "5800000001" in parziale


def test_cruscotto_simulazione_data_solo_admin(come, dati):
    admin = come(ADMIN)
    html = admin.get(reverse("contratti:cruscotto"), {"oggi": "2027-01-15"}).content.decode()
    assert "15/01/2027" in html
    assert dati["fabbisogno"].descrizione in html  # scaduto senza rinnovo → rosso


def test_cruscotto_ignora_la_data_simulata_per_editor(editor, dati):
    html = editor.get(reverse("contratti:cruscotto"), {"oggi": "2027-01-15"}).content.decode()
    assert "15/01/2027" not in html


def test_cruscotto_include_i_fabbisogni_nuovi(come, dati):
    admin = come(ADMIN)
    # Avvio 01/07/2027, lead time "da verificare" 6 mesi: limite 01/01/2027.
    html = admin.get(reverse("contratti:cruscotto"), {"oggi": "2027-02-01"}).content.decode()
    assert "Nuovo servizio" in html and "nuovo</span>" in html


def test_fabbisogno_mostra_i_previsti(reader, dati):
    html = reader.get(
        reverse("contratti:fabbisogno", args=[dati["fabbisogno"].pk])
    ).content.decode()
    assert "Contratti previsti" in html and "01/01/2027" in html


def test_versione_nel_pie_di_pagina(reader, settings):
    settings.APP_VERSION = "v1.2"
    assert "versione v1.2" in reader.get(reverse("home")).content.decode()


def test_id_oltre_mille_non_formattati_con_il_separatore(editor, dati):
    """USE_THOUSAND_SEPARATOR: un id 12345 nei valori dei filtri deve restare 12345."""
    from contratti import models as m

    fornitore = m.Fornitore.objects.create(pk=12345, ragione_sociale="Fornitore 12345")
    fab = m.Fabbisogno.objects.create(
        pk=23456, descrizione="Id grande", area="IT", categoria=dati["fabbisogno"].categoria
    )
    html = editor.get(reverse("contratti:contratti")).content.decode()
    assert f'value="{fornitore.pk}"' in html
    html = editor.get(reverse("contratti:fabbisogno", args=[fab.pk])).content.decode()
    assert "?fabbisogno=23456" in html


def test_piani_da_verificare_elenca_le_voci_senza_piano_reale(editor, dati):
    from decimal import Decimal

    from contratti import models as m
    from tests import factories as f

    c = dati["contratto"]
    pesante = f.voce(c, descrizione="Voce pesante", importo_fisso=Decimal("90000.00"))
    f.piano(pesante, modalita="da_verificare", periodicita="")
    f.voce(c, descrizione="Voce senza piano", importo_fisso=Decimal("10.00"))
    url = reverse("contratti:piani_da_verificare")
    html = editor.get(url).content.decode()
    assert "Voce pesante" in html and "Voce senza piano" in html
    assert html.index("Voce pesante") < html.index("Voce senza piano")
    assert "Canone" not in html.split('id="piani"')[1]  # la voce con piano reale non c'è
    # Salvando il piano dall'elenco si torna all'elenco.
    modifica = reverse("contratti:voce_modifica", args=[c.pk, pesante.pk]) + "?ritorno=piani"
    assert modifica.replace("&", "&amp;") in html or modifica in html
    risposta = editor.get(url)
    assert risposta.context["piani_da_verificare"] == 2
    assert m.VoceContratto.objects.count() == 3
