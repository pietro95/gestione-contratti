"""Nuovo contratto guidato: contratto → voce e piano → rate generate (richiesta di Pietro)."""

import datetime

import pytest
from django.urls import reverse

from contratti import models as m

from .. import factories as f
from .test_flussi import campi_contratto

pytestmark = pytest.mark.django_db
D = datetime.date


def _voce(**kw):
    dati = {
        "voce-descrizione": "Canone trimestrale",
        "voce-proroga": "",
        "voce-conto": "",
        "voce-centro_costo": "",
        "voce-natura": "OPEX",
        "voce-wbs": "",
        "voce-importo_fisso": "24.000,00",
        "voce-massimale_variabile": "0",
        "voce-stima_consumo_pct": "",
        "voce-stima_consumo_importo": "",
        "piano-modalita": "posticipata",
        "piano-periodicita": "trimestrale",
        "piano-data_prima_fattura": "",
        "piano-giorni_pagamento": "60",
        "piano-pagamento_fine_mese": "true",
        "piano-note": "",
        "quote-TOTAL_FORMS": "1",
        "quote-INITIAL_FORMS": "0",
        "quote-0-dal": "",
        "quote-0-al": "",
        "quote-0-importo": "",
    }
    dati.update(kw)
    return dati


def test_tre_passi_dal_contratto_alle_rate(editor, dati):
    nuovo = reverse("contratti:contratto_nuovo")
    html = editor.get(nuovo).content.decode()
    assert (
        'aria-label="Passi del nuovo contratto"' in html and "Avanti: voci e fatturazione" in html
    )

    risposta = editor.post(
        nuovo,
        {
            **campi_contratto(
                fornitore=dati["fornitore"].pk,
                procedura=m.Procedura.objects.get(codice="rdo").pk,
                data_inizio="2026-07-01",
                durata_mesi="24",
            ),
            "fabbisogno": dati["fabbisogno"].pk,
            "sottocluster": f.sottocluster().pk,
        },
    )
    c = m.Contratto.objects.order_by("-pk").first()
    passo2 = reverse("contratti:voce_nuova", args=[c.pk]) + "?guidata=1"
    assert risposta.url == passo2
    html = editor.get(passo2).content.decode()
    assert 'aria-current="step"' in html and "Salva e genera le rate" in html

    # Salvando la voce le rate si generano (TC-03: 8 rate trimestrali da 3.000,00).
    risposta = editor.post(passo2, _voce())
    assert risposta.url == reverse("contratti:contratto_guidata", args=[c.pk])
    voce = c.voci.get()
    rate = list(voce.piano_fatturazione.rate.order_by("numero"))
    assert len(rate) == 8 and rate[0].data_fattura == D(2026, 9, 30)
    assert not any(r.modificata_manualmente for r in rate)

    html = editor.get(risposta.url).content.decode()
    assert "Totale (8 rate)" in html and "24.000,00 €" in html
    assert "Aggiungi un&#x27;altra voce" in html or "Aggiungi un'altra voce" in html


def test_modificando_il_piano_le_rate_si_rigenerano(editor, dati):
    c, voce = dati["contratto"], dati["voce"]  # annuale anticipata: una rata
    url = reverse("contratti:voce_modifica", args=[c.pk, voce.pk])
    editor.post(url, _voce(**{"voce-importo_fisso": "12.000,00", "piano-modalita": "anticipata"}))
    assert voce.piano_fatturazione.rate.count() == 4  # trimestrale su 12 mesi


def test_rate_modificate_a_mano_non_si_rigenerano(editor, dati):
    c, voce, rata = dati["contratto"], dati["voce"], dati["rata"]
    m.Rata.objects.filter(pk=rata.pk).update(modificata_manualmente=True)
    url = reverse("contratti:voce_modifica", args=[c.pk, voce.pk])
    risposta = editor.post(url, _voce(), follow=True)
    assert "rate non rigenerate" in risposta.content.decode()
    assert list(voce.piano_fatturazione.rate.all()) == [rata]


def test_sal_nessuna_rata_e_avviso(editor, dati):
    c = dati["contratto"]
    risposta = editor.post(
        reverse("contratti:voce_nuova", args=[c.pk]) + "?guidata=1",
        _voce(**{"piano-modalita": "sal", "piano-periodicita": ""}),
        follow=True,
    )
    assert "le rate si inseriscono a mano" in risposta.content.decode()
