"""F11.4 nel browser: cruscotto acquisti, stato delle RDA, contratti da chiudere, anomalie
dell'esecuzione e cruscotto con «I miei acquisti», senza violazioni gravi di accessibilità."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import expect

from contratti import models as m

from .. import factories as f
from .conftest import violazioni_axe

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]
D = datetime.date


def test_viste_del_processo_d_acquisto(pagina):
    editor = get_user_model().objects.get(username="e2e_editor")
    rda = m.RichiestaAcquisto.objects.create(
        cluster=f.cluster("IT"), descrizione="Richiesta di prova", origine="manuale",
        numero_rda="5100000001", data_inserimento=D(2026, 1, 15), referente_utente=editor,
    )  # fmt: skip
    m.PosizioneRDA.objects.create(
        rda=rda, numero=1, descrizione_breve="Licenze", importo_unitario=Decimal("1000.00")
    )
    c = f.contratto(
        fabbisogno=f.fabbisogno("Forniture concluse"), una_tantum=True,
        data_inizio=D(2025, 1, 1), durata_mesi=1, numero_contratto="5800000016",
    )  # fmt: skip
    f.voce(c, importo_fisso=Decimal("100.00"))
    m.Fattura.objects.create(
        contratto=c, numero="FA-1", data=D(2025, 1, 20), importo_documento=Decimal("200.00"),
        valore_base=Decimal("200.00"), referente=editor, data_presa_in_carico=D(2025, 1, 21),
    )  # fmt: skip

    pagina.goto(f"{pagina.base}/report/acquisti/")
    expect(pagina.get_by_text("Da sollecitare per il rilascio")).to_be_visible()
    assert violazioni_axe(pagina) == []
    pagina.goto(f"{pagina.base}/report/rda/")
    expect(pagina.locator("#stato-rda")).to_contain_text("5100000001")
    assert violazioni_axe(pagina) == []
    pagina.goto(f"{pagina.base}/report/da-chiudere/")
    expect(pagina.locator("#da-chiudere")).to_contain_text("Attestazione mancante")
    assert violazioni_axe(pagina) == []
    pagina.goto(f"{pagina.base}/report/anomalie/")
    expect(pagina.locator("#anomalie")).to_contain_text("FATTURATO_OLTRE_MASSIMO")
    assert violazioni_axe(pagina) == []
    pagina.goto(f"{pagina.base}/")
    expect(pagina.locator("#miei-acquisti")).to_contain_text("Fattura FA-1")
    assert violazioni_axe(pagina) == []
    assert not pagina.errori, pagina.errori
