"""F8: le pagine "Sposta" e "Accorpa" mostrano l'anteprima e salvano solo alla conferma."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from contratti import servizi

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


def test_accorpa_mostra_e_unisce_i_doppioni(editor):
    origine = f.fabbisogno("Importato due volte")
    destinazione = f.fabbisogno("Originale")
    copia = f.contratto(
        fabbisogno=origine, numero_contratto="5800000777", data_inizio=D(2025, 1, 1)
    )
    buono = f.contratto(
        fabbisogno=destinazione, numero_contratto="5800000777", data_inizio=D(2025, 1, 1)
    )
    url = reverse("contratti:fabbisogno_accorpa", args=[origine.pk])
    html = editor.post(url, {"destinazione": destinazione.pk, "passo": "anteprima"}).content
    assert "Contratti registrati due volte" in html.decode()
    # Deselezionando la coppia il doppione resta.
    editor.post(
        url,
        {"destinazione": destinazione.pk, "passo": "conferma", "doppioni_presenti": "1"},
    )
    copia.refresh_from_db()
    assert not copia.archiviato and copia.fabbisogno == destinazione

    html = editor.get(reverse("contratti:fabbisogno", args=[destinazione.pk])).content.decode()
    assert "Contratti registrati due volte" in html
    ((tenuto, doppione),) = servizi.doppioni_del_fabbisogno(destinazione)
    assert {tenuto, doppione} == {buono, copia}
    editor.post(
        reverse("contratti:fabbisogno_doppioni", args=[destinazione.pk]),
        {"doppioni": [f"{tenuto.pk}-{doppione.pk}"]},
    )
    doppione.refresh_from_db()
    tenuto.refresh_from_db()
    assert doppione.archiviato and not tenuto.archiviato


def test_catena_interrotta_avviso_e_collegamento_dal_fabbisogno(editor):
    """Dopo un accorpamento senza collegamento il vecchio contratto si ricollega a mano."""
    fab = f.fabbisogno("Accorpato in passato", decisione="rinnovare")
    vecchio = f.contratto(fabbisogno=fab, numero_contratto="5800000881", data_inizio=D(2025, 1, 1))
    nuovo = f.contratto(fabbisogno=fab, numero_contratto="5800000882", data_inizio=D(2026, 1, 1))
    html = editor.get(reverse("contratti:contratto", args=[vecchio.pk])).content.decode()
    assert "Collegalo dal fabbisogno" in html and "5800000882" in html
    html = editor.get(reverse("contratti:fabbisogno", args=[fab.pk])).content.decode()
    assert "Catena dei rinnovi interrotta" in html
    risposta = editor.post(
        reverse("contratti:fabbisogno_collega", args=[fab.pk]),
        {"collegamenti": [f"{vecchio.pk}-{nuovo.pk}"]},
        follow=True,
    )
    assert "1 contratti collegati al loro rinnovo" in risposta.content.decode()
    nuovo.refresh_from_db()
    assert nuovo.predecessore == vecchio
    html = editor.get(reverse("contratti:fabbisogno", args=[fab.pk])).content.decode()
    assert "Catena dei rinnovi interrotta" not in html
    html = editor.get(reverse("contratti:contratto", args=[vecchio.pk])).content.decode()
    assert "Collegalo dal fabbisogno" not in html


def test_collegamento_non_proposto_rifiutato_dalla_vista(editor):
    fab = f.fabbisogno("Senza catene")
    vecchio = f.contratto(fabbisogno=fab, data_inizio=D(2025, 1, 1))
    nuovo = f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1))
    risposta = editor.post(
        reverse("contratti:fabbisogno_collega", args=[fab.pk]),
        {"collegamenti": [f"{nuovo.pk}-{vecchio.pk}"]},
        follow=True,
    )
    assert "Collegamento non tra quelli proposti" in risposta.content.decode()
    nuovo.refresh_from_db()
    assert nuovo.predecessore is None
