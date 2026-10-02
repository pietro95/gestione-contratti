"""F8: le pagine "Sposta" e "Accorpa" mostrano l'anteprima e salvano solo alla conferma."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


def test_sposta_anteprima_poi_conferma(editor, dati):
    c = dati["contratto"]
    destinazione = f.fabbisogno("Destinazione di prova")
    url = reverse("contratti:contratto_sposta", args=[c.pk])
    assert "Anteprima" in editor.get(url).content.decode()

    html = editor.post(url, {"destinazione": destinazione.pk, "passo": "anteprima"}).content
    assert "Conferma lo spostamento" in html.decode()
    c.refresh_from_db()
    assert c.fabbisogno == dati["fabbisogno"]  # l'anteprima non salva

    risposta = editor.post(
        url, {"destinazione": destinazione.pk, "passo": "conferma", "predecessore": ""}
    )
    assert risposta.status_code == 302
    c.refresh_from_db()
    assert c.fabbisogno == destinazione


def test_sposta_errore_mostrato_senza_salvare(editor, dati):
    c = dati["contratto"]
    altro = f.fabbisogno("Con catena")
    vecchio = f.contratto(fabbisogno=altro, data_inizio=D(2024, 1, 1))
    f.contratto(fabbisogno=altro, predecessore=vecchio, data_inizio=D(2025, 1, 1))
    url = reverse("contratti:contratto_sposta", args=[c.pk])
    risposta = editor.post(
        url, {"destinazione": altro.pk, "passo": "conferma", "predecessore": vecchio.pk}
    )
    assert risposta.status_code == 200
    assert "senza successore" in risposta.content.decode()
    c.refresh_from_db()
    assert c.fabbisogno == dati["fabbisogno"]


def test_accorpa_con_collegamento(editor):
    origine = f.fabbisogno("Vecchio nome", decisione="rinnovare")
    destinazione = f.fabbisogno("Nuovo nome", decisione="rinnovare")
    vecchio = f.contratto(fabbisogno=origine, data_inizio=D(2024, 1, 1), durata_mesi=12)
    nuovo = f.contratto(fabbisogno=destinazione, data_inizio=D(2025, 1, 1), durata_mesi=12)
    f.voce(nuovo, importo_fisso=Decimal("10.00"))
    url = reverse("contratti:fabbisogno_accorpa", args=[origine.pk])
    html = editor.post(url, {"destinazione": destinazione.pk, "passo": "anteprima"}).content
    assert f'value="{vecchio.pk}-{nuovo.pk}" checked' in html.decode()

    risposta = editor.post(
        url,
        {
            "destinazione": destinazione.pk,
            "passo": "conferma",
            "collegamenti": [f"{vecchio.pk}-{nuovo.pk}"],
        },
    )
    assert risposta.status_code == 302
    assert risposta.url == reverse("contratti:fabbisogno", args=[destinazione.pk])
    origine.refresh_from_db()
    nuovo.refresh_from_db()
    assert origine.archiviato and nuovo.predecessore == vecchio
