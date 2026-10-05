"""F9.3: «Registra rinnovo» che sostituisce anche altri contratti; confluenze dal contratto."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from contratti import adapters
from contratti import models as m

from .. import factories as f
from .test_flussi import campi_contratto

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def sim():
    fab = f.fabbisogno("SIM", decisione="rinnovare")
    v = f.contratto(fabbisogno=fab, numero_contratto="5800000301", data_inizio=D(2025, 1, 1),
                    durata_mesi=24)  # fmt: skip
    f.piano(f.voce(v, importo_fisso=Decimal("4800.00")))
    mm = f.contratto(fabbisogno=fab, numero_contratto="5800000302", data_inizio=D(2025, 11, 1))
    return {"fab": fab, "v": v, "m": mm}


def test_rinnovo_che_sostituisce_anche_un_altro_contratto(editor, sim):
    v, mm = sim["v"], sim["m"]
    url = reverse("contratti:contratto_rinnovo", args=[v.pk])
    html = editor.get(url).content.decode()
    assert "Sostituisce anche" in html and "5800000302" in html
    risposta = editor.post(
        url,
        {
            **campi_contratto(
                fornitore=v.fornitore_id,
                procedura=v.procedura_id,
                data_inizio="2027-01-01",
                durata_mesi="24",
                numero_contratto="5800000303",
            ),
            "voci-TOTAL_FORMS": "1",
            "voci-INITIAL_FORMS": "1",
            "voci-0-origine": v.voci.get().pk,
            "voci-0-riporta": "on",
            "voci-0-descrizione": "SIM voce e M2M",
            "voci-0-importo_fisso": "9.600,00",
            "voci-0-massimale_variabile": "0",
            "sostituisce": [mm.pk],
        },
    )
    n = m.Contratto.objects.get(numero_contratto="5800000303")
    assert risposta.status_code == 302
    mm.refresh_from_db()
    assert n.predecessore == v and mm.confluito_in == n
    assert not adapters.ha_successore(n) and adapters.ha_successore(mm)
    html = editor.get(reverse("contratti:contratto", args=[n.pk])).content.decode()
    assert "Sostituisce anche" in html and "5800000302" in html
    html = editor.get(reverse("contratti:contratto", args=[mm.pk])).content.decode()
    assert "Confluito in" in html and "Registra rinnovo</a>" not in html


def test_confluenza_dalla_scheda_e_togli(editor, sim):
    v, mm = sim["v"], sim["m"]
    n = f.contratto(fabbisogno=sim["fab"], predecessore=v, numero_contratto="5800000303",
                    data_inizio=D(2027, 1, 1))  # fmt: skip
    html = editor.get(reverse("contratti:contratto", args=[n.pk])).content.decode()
    assert "Sostituisce anche altri contratti" in html
    url = reverse("contratti:contratto_confluiti", args=[n.pk])
    assert "5800000302" in editor.get(url).content.decode()
    assert editor.post(url, {}).status_code == 200  # nessuna scelta
    assert editor.post(url, {"confluiti": [mm.pk]}).status_code == 302
    mm.refresh_from_db()
    assert mm.confluito_in == n
    risposta = editor.post(
        reverse("contratti:contratto_togli_confluenza", args=[mm.pk]), {"ritorno": "nuovo"}
    )
    assert risposta.url == reverse("contratti:contratto", args=[n.pk])
    mm.refresh_from_db()
    assert mm.confluito_in is None
