"""F11.3 nel browser: import settimanale → presa in carico multipla → contratto → convalida →
RdC → MAP → rilasci su SAP → commento per PAC → trasferimento → chiusura del contratto.

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
from .conftest import violazioni_axe

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]
D = datetime.date


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
    conto = f.conto(
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
    expect(pagina.get_by_text("FORNITORE_CREATO").first).to_be_visible()
    assert violazioni_axe(pagina) == []
    pagina.click("button:has-text('Conferma l')")
    pagina.locator("#modale-conferma [data-conferma-ok]").click()
    expect(pagina.locator(".sottotitolo .stato-verde")).to_have_text("Importato")
    assert m.Fattura.objects.count() == 3

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
    # La 99, del fornitore creato dall'import, non ha un contratto né un referente proposto.
    assert set(
        m.Fattura.objects.exclude(numero="99").values_list("referente__username", flat=True)
    ) == {"e2e_editor"}
    assert m.Fattura.objects.get(numero="99").referente is None

    # La fattura 13/2026: contratto proposto, convalida, importi, RdC e MAP, con i rilasci.
    m.FunzioneUtente.objects.create(
        username="e2e_editor", funzione=m.FunzioneUtente.Funzione.RILASCIO_SAP
    )
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
    pagina.fill("#id_competenza_dal", "01/01/2026")
    pagina.fill("#id_competenza_al", "31/12/2026")
    pagina.keyboard.press("Escape")
    pagina.click("button:has-text('Salva gli importi')")
    for tipo, numero in (("ODA_RDC", "RDC-0001"), ("MAP", "MAP-0001")):
        pagina.select_option("#id_tipo", tipo)
        pagina.fill("#id_numero", numero)
        pagina.keyboard.press("Escape")
        pagina.click("button:has-text('Registra il documento')")
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("RdC da rilasciare")
    pagina.locator("button:has-text('Rilascia')").first.click()
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("MAP/MIGO da rilasciare")
    pagina.locator("button:has-text('Rilascia')").first.click()
    expect(pagina.locator(".sottotitolo .stato").first).to_have_text("Da trasferire")
    assert violazioni_axe(pagina) == []

    # Commento per PAC negli appunti, poi il trasferimento.
    pagina.click("text=Copia il commento per PAC")
    expect(pagina.locator("button.copiato")).to_be_visible()
    assert pagina.evaluate("navigator.clipboard.readText()") == PAC_ATTESO.replace(
        "5800000013", "5800000077"
    )
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


def test_voci_solo_del_contratto_scelto(pagina):
    """Assegnando la fattura al contratto, la tendina «Voce» mostra solo le voci del contratto
    scelto e cambia con il contratto."""
    editor = get_user_model().objects.get(username="e2e_editor")
    fornitore = f.fornitore("Negozio Prova S.r.l.")
    a = f.contratto(fornitore=fornitore, numero_contratto="5800000081",
                    data_inizio=D(2026, 1, 1))  # fmt: skip
    b = f.contratto(fornitore=fornitore, numero_contratto="5800000082",
                    data_inizio=D(2026, 2, 1))  # fmt: skip
    va = [f.voce(a, descrizione=f"Voce A{i}") for i in (1, 2)]
    vb = f.voce(b, descrizione="Voce B1")
    fattura = m.Fattura.objects.create(
        fornitore=fornitore, numero="AMZ-1", data=D(2026, 9, 1),
        importo_documento=Decimal("10.00"), referente=editor,
        data_presa_in_carico=D(2026, 9, 2),
    )  # fmt: skip
    pagina.goto(f"{pagina.base}/fatture/{fattura.pk}/")
    voce = pagina.locator("#id_voce")
    pagina.select_option("#id_contratto", str(a.pk))
    expect(voce.locator("option")).to_have_count(3)  # vuota + le due voci di A
    pagina.select_option("#id_contratto", str(b.pk))
    expect(voce.locator("option")).to_have_count(2)
    pagina.select_option("#id_voce", str(vb.pk))
    assert violazioni_axe(pagina) == []
    pagina.click("button:has-text('Assegna al contratto')")
    expect(pagina.locator(".toast-body").first).to_contain_text("assegnata")
    fattura.refresh_from_db()
    assert (fattura.contratto_id, fattura.voce_id) == (b.pk, vb.pk)
    assert va[0].contratto_id == a.pk
