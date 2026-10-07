"""F11.3 nel browser: import settimanale → presa in carico multipla → contratto → convalida →
RdC → MAP → commento per PAC → trasferimento → chiusura del contratto.

Ogni pagina senza violazioni gravi di accessibilità (axe-core). Nomi e codici di fantasia.
"""

import datetime
from decimal import Decimal

import openpyxl
import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import expect

from contratti import models as m

from .. import factories as f
from ..engine.test_tc18_fatture import PAC_ATTESO
from .conftest import violazioni_axe as _violazioni_axe

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]
D = datetime.date


def violazioni_axe(pg):
    """Come in conftest, ad animazione delle notifiche finita (a metà dissolvenza il contrasto
    non è quello reale)."""
    pg.wait_for_function(
        """() => [...document.querySelectorAll('.toast')].every(t => {
            const s = getComputedStyle(t);
            return s.display === 'none' || s.opacity === '1';
        })"""
    )
    return _violazioni_axe(pg)


def _estrazione(tmp_path, oggi):
    wb = openpyxl.Workbook()
    ws = wb.active
    for riga in (
        ["Rev. 00"],
        ["#", "Fornitore", "Numero Documento", "Data", "Importo SAP", "REFERENTE"],
        [1, "STUDIOP", "13/2026", oggi.strftime("%d.%m.%Y"), "1679,83", None],
        [2, "STUDIOP", "14/2026", oggi.strftime("%d.%m.%y"), 100, None],
        [3, "Fornitore Sconosciuto", "99", oggi.strftime("%d.%m.%Y"), 10, None],
    ):
        ws.append(riga)
    percorso = tmp_path / "estrazione_fatture.xlsx"
    wb.save(percorso)
    return percorso


def test_flusso_della_fattura(pagina, tmp_path):
    oggi = datetime.date.today()
    it = f.cluster("IT")
    conto = m.ContoCoge.objects.create(
        codice="600010", descrizione="Conto di prova", valido_dal=D(2020, 1, 1), cluster=it
    )
    wbs = m.WBS.objects.create(codice_wbs="WBS-TEST-01", descrizione="WBS di prova", cluster=it)
    s = f.fornitore("Studio Prova", nome_breve="STUDIOP")
    editor = get_user_model().objects.get(username="e2e_editor")
    cs = f.contratto(
        fornitore=s,
        fabbisogno=f.fabbisogno("Consulenza di prova", referente_utente=editor),
        data_inizio=oggi.replace(month=1, day=1),
        numero_contratto="5800000077",
    )
    f.voce(
        cs, natura=m.Natura.CAPEX, conto=conto, centro_costo="C0001", wbs=wbs,
        importo_fisso=Decimal("5000.00"),
    )  # fmt: skip
    pagina.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=pagina.base)

    # Import settimanale: anteprima, poi conferma nella finestra modale.
    pagina.goto(f"{pagina.base}/import/")
    pagina.set_input_files("#id_fatture-file", str(_estrazione(tmp_path, oggi)))
    pagina.click("form[action$='/fatture/'] button[type=submit]")
    expect(pagina.locator("text=Anteprima: nessun dato è stato ancora scritto")).to_be_visible()
    expect(pagina.get_by_text("FORNITORE_NON_TROVATO").first).to_be_visible()
    assert violazioni_axe(pagina) == []
    pagina.click("button:has-text('Conferma l')")
    pagina.locator("#modale-conferma [data-conferma-ok]").click()
    expect(pagina.locator(".sottotitolo .stato-verde")).to_have_text("Importato")
    assert m.Fattura.objects.count() == 2

    # Da prendere in carico: proposte a me (referente del fabbisogno), selezione multipla.
    pagina.goto(f"{pagina.base}/fatture/")
    expect(pagina.locator("#f-proposte")).to_be_checked()
    assert violazioni_axe(pagina) == []
    pagina.check("[data-seleziona-tutte=fattura]")
    expect(pagina.locator("[data-selezionate=fattura]")).to_have_text("2 selezionate")
    pagina.click("button[value=prendi]")
    expect(
        pagina.locator(".alert-success, .toast", has_text="2 fatture prese in carico")
    ).to_have_count(1)
    assert set(m.Fattura.objects.values_list("referente__username", flat=True)) == {"e2e_editor"}

    # La fattura 13/2026: contratto proposto, convalida, importi, RdC e MAP.
    fa = m.Fattura.objects.get(numero="13/2026")
    pagina.goto(f"{pagina.base}/fatture/{fa.pk}/")
    assert violazioni_axe(pagina) == []
    pagina.click("button:has-text('Assegna al contratto')")
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("Da convalidare")
    pagina.select_option("#id_esito_convalida", "convalidabile")
    pagina.click("button:has-text('Registra l')")
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("RdC da fare")
    pagina.fill("#id_valore_base", "1.504,17")
    pagina.fill("#id_oneri", "173,66")
    pagina.fill("#id_bollo", "2,00")
    pagina.click("button:has-text('Salva gli importi')")
    for tipo, numero in (("ODA_RDC", "RDC-0001"), ("MAP", "MAP-0001")):
        pagina.select_option("#id_tipo", tipo)
        pagina.fill("#id_numero", numero)
        pagina.keyboard.press("Escape")
        pagina.click("button:has-text('Registra il documento')")
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("Da trasferire")
    assert violazioni_axe(pagina) == []

    # Commento per PAC negli appunti, poi il trasferimento.
    pagina.click("text=Copia il commento per PAC")
    expect(pagina.locator("button.copiato")).to_be_visible()
    assert pagina.evaluate("navigator.clipboard.readText()") == PAC_ATTESO
    pagina.click("button:has-text('Registra il trasferimento')")
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("Trasferita")

    # Esecuzione del contratto e chiusura in finestra modale.
    pagina.goto(f"{pagina.base}/contratti/{cs.pk}/#esecuzione")
    expect(pagina.locator("#esecuzione").get_by_text("1.504,17 €").first).to_be_visible()
    assert violazioni_axe(pagina) == []
    pagina.locator("#esecuzione").get_by_role("button", name="Chiudi", exact=True).click()
    pagina.locator("#modale-conferma [data-conferma-ok]").click()
    expect(pagina.locator(".sottotitolo").get_by_text("chiuso", exact=True)).to_be_visible()
    cs.refresh_from_db()
    assert cs.data_chiusura == oggi
    assert not pagina.errori, pagina.errori
