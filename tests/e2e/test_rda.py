"""F11.2 nel browser: richiesta di RDA → invio → rimando → invio → dati SAP → contratto.

Ogni pagina senza violazioni gravi di accessibilità (axe-core); «Copia» mette il testo della
richiesta negli appunti.
"""

import pytest
from playwright.sync_api import expect

from contratti import models as m

from .conftest import violazioni_axe

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]


def test_flusso_della_richiesta_di_rda(pagina, dati):
    fab, c = dati["fabbisogno"], dati["contratto"]
    m.RichiedenteSAP.objects.create(
        codice="999901", descrizione="Ufficio di prova", predefinito=True
    )
    m.GruppoAcquisti.objects.create(codice="G01", predefinito=True)
    pagina.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=pagina.base)

    # Dal fabbisogno: richiesta impostata come rinnovo del contratto in scadenza.
    pagina.goto(f"{pagina.base}/fabbisogni/{fab.pk}/")
    pagina.click("text=Nuova richiesta di RDA")
    expect(pagina.get_by_text("Rinnovo", exact=True)).to_be_visible()
    expect(pagina.locator("#id_pos-0-descrizione_breve")).not_to_have_value("")
    assert violazioni_axe(pagina) == []
    pagina.click("button[data-aggiungi-form=pos]")
    expect(
        pagina.locator("#id_pos-2-descrizione_breve")
    ).to_be_focused()  # proposta + vuota + nuova
    assert pagina.locator("#id_pos-TOTAL_FORMS").input_value() == "3"
    pagina.click("button[name=invia]")
    pagina.wait_for_url("**/rda/*/")
    rda = m.RichiestaAcquisto.objects.get()
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("Inviata")
    assert violazioni_axe(pagina) == []

    # «Copia testo della richiesta»: negli appunti il testo della mail.
    pagina.click("text=Copia testo della richiesta")
    expect(pagina.locator("button.copiato")).to_be_visible()
    appunti = pagina.evaluate("navigator.clipboard.readText()")
    assert appunti.startswith("Si deve predisporre la seguente RDA.")
    assert "(Campo SAP) Richiedente: 999901" in appunti

    # L'addetto rimanda al referente, che corregge e invia di nuovo.
    pagina.fill("#nota-rimando", "Manca il preventivo")
    pagina.click("text=Rimanda al referente")
    expect(pagina.locator(".alert-warning", has_text="Manca il preventivo")).to_be_visible()
    pagina.get_by_role("link", name="Modifica", exact=True).click()
    pagina.fill("#id_allegati", "preventivo nella cartella")
    assert violazioni_axe(pagina) == []
    pagina.click("button[name=invia]")
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("Inviata")

    # Dati da SAP: inserimento e rilascio.
    pagina.fill("#id_numero_rda", "5100000001")
    pagina.fill("#id_data_inserimento", "15/06/2026")
    pagina.fill("#id_data_rilascio", "01/07/2026")
    pagina.keyboard.press("Escape")
    pagina.click("text=Salva i dati SAP")
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("Rilasciata")

    # Il contratto emesso, precompilato dalla RDA.
    pagina.get_by_role("link", name="Registra contratto", exact=True).click()
    assert violazioni_axe(pagina) == []
    pagina.fill("#id_numero_contratto", "5800000099")
    pagina.click("button[type=submit]:has-text('Registra contratto')")
    pagina.wait_for_url("**/contratti/*/")
    nuovo = m.Contratto.objects.get(numero_contratto="5800000099")
    assert (nuovo.predecessore_id, nuovo.rda_id) == (c.pk, rda.pk)
    expect(pagina.get_by_role("link", name="RDA 5100000001")).to_be_visible()
    assert violazioni_axe(pagina) == []
    pagina.goto(f"{pagina.base}/rda/")
    assert violazioni_axe(pagina) == []
    pagina.goto(f"{pagina.base}/rda/registra/")
    assert violazioni_axe(pagina) == []
    assert not pagina.errori, pagina.errori


def test_il_richiedente_propone_il_gruppo_acquisti(pagina, dati):
    """Codici di rilascio SAP: scegliendo il richiedente di un'altra unità, il gruppo acquisti
    diventa quello della sua unità."""
    fab = dati["fabbisogno"]
    g1 = m.GruppoAcquisti.objects.create(codice="G01", descrizione="Ufficio", predefinito=True)
    g2 = m.GruppoAcquisti.objects.create(codice="G02", descrizione="Altra unità")
    m.RichiedenteSAP.objects.create(
        codice="999901", descrizione="Ufficio", predefinito=True, gruppo_acquisti=g1
    )
    altro = m.RichiedenteSAP.objects.create(
        codice="999902", descrizione="Altra unità", gruppo_acquisti=g2
    )
    pagina.goto(f"{pagina.base}/rda/nuova/{fab.pk}/")
    expect(pagina.locator("#id_gruppo_acquisti")).to_have_value(str(g1.pk))
    pagina.select_option("#id_richiedente", str(altro.pk))
    expect(pagina.locator("#id_gruppo_acquisti")).to_have_value(str(g2.pk))
    assert violazioni_axe(pagina) == []
    pagina.click("button[type=submit]:has-text('Salva in bozza')")
    pagina.wait_for_url("**/rda/*/")
    rda = m.RichiestaAcquisto.objects.get()
    assert (rda.richiedente_id, rda.gruppo_acquisti_id) == (altro.pk, g2.pk)
