"""F7: pagine principali nel browser. Nessun errore JavaScript, accessibilità WCAG 2.1 AA
(nessuna violazione grave o critica secondo axe-core), tastiera, componenti interattivi."""

import datetime
import json

import pytest
from playwright.sync_api import expect

from contratti import models as m

from .. import factories as f
from .conftest import violazioni_axe

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]


def _pagine(dati):
    c, fab = dati["contratto"], dati["fabbisogno"]
    v = dati["voce"]
    # Catena interrotta: avviso nel fabbisogno e nel contratto rimasto senza rinnovo.
    interrotto = f.fabbisogno("Catena interrotta", decisione="rinnovare")
    # Rinnovo che parte prima della scadenza (01/03/2025–28/02/2026, poi dal 01/01/2026).
    vecchio = f.contratto(fabbisogno=interrotto, data_inizio=datetime.date(2025, 3, 1))
    f.contratto(fabbisogno=interrotto, data_inizio=datetime.date(2026, 1, 1))
    wbs = m.WBS.objects.create(codice_wbs="X.0001.00.000", descrizione="WBS di prova")
    # F9.3: un contratto nuovo che sostituisce anche un altro contratto.
    nuovo = f.contratto(
        fabbisogno=interrotto, predecessore=vecchio, data_inizio=datetime.date(2027, 1, 1)
    )
    confluito = f.contratto(fabbisogno=interrotto, data_inizio=datetime.date(2025, 6, 1))
    confluito.confluito_in = nuovo
    confluito.save()
    return [
        "/",
        "/cruscotto/",
        "/contratti/",
        "/contratti/?area=IT&ordina=-fine",
        f"/contratti/{c.pk}/",
        f"/contratti/{c.pk}/modifica/",
        f"/contratti/{c.pk}/rinnovo/",
        f"/contratti/{c.pk}/proroga/",
        f"/contratti/{c.pk}/voci/{v.pk}/",
        "/fabbisogni/",
        f"/fabbisogni/{fab.pk}/",
        "/fabbisogni/nuovo/",
        "/fornitori/",
        f"/fornitori/{c.fornitore_id}/",
        f"/contratti/{c.pk}/sposta/",
        "/contratti/nuovo/",
        f"/contratti/{c.pk}/voci/nuova/?guidata=1",
        f"/contratti/{c.pk}/scadenzario/",
        f"/fabbisogni/{fab.pk}/accorpa/",
        f"/fabbisogni/{interrotto.pk}/",
        f"/contratti/{vecchio.pk}/",
        f"/contratti/{vecchio.pk}/collega/",
        f"/contratti/{nuovo.pk}/",
        f"/contratti/{nuovo.pk}/confluiti/",
        f"/contratti/{confluito.pk}/",
        "/piani-da-verificare/",
        "/import/",
        "/report/budget/?anno=2026",
        "/report/budget/?anno=2026&natura=separate",
        "/report/piano-ordini/?anno=2027",
        "/report/wbs/",
        f"/report/wbs/{wbs.pk}/",
        "/cerca/?q=prova",
        "/proposte/",
    ]


def test_pagine_senza_errori_e_accessibili(pagina, dati):
    problemi = {}
    for url in _pagine(dati):
        risposta = pagina.goto(pagina.base + url)
        assert risposta.status == 200, url
        pagina.wait_for_load_state("networkidle")
        gravi = violazioni_axe(pagina)
        if gravi:
            problemi[url] = gravi
    assert not pagina.errori, pagina.errori
    assert not problemi, json.dumps(problemi, indent=1, ensure_ascii=False)


def test_login_accessibile_con_logo(browser, live_server, dati):
    pg = browser.new_page()
    pg.goto(f"{live_server.url}/accounts/login/")
    assert pg.locator("img[alt=Siciliacque]").is_visible()
    assert violazioni_axe(pg) == []
    pg.close()


def test_tastiera_salta_al_contenuto(pagina):
    pagina.keyboard.press("Tab")
    focalizzato = pagina.evaluate("document.activeElement.textContent.trim()")
    assert focalizzato == "Salta al contenuto"
    pagina.keyboard.press("Enter")
    assert pagina.evaluate("document.activeElement.id") == "contenuto"


def test_data_con_calendario_e_formato_italiano(pagina, dati):
    c = dati["contratto"]
    pagina.goto(f"{pagina.base}/contratti/{c.pk}/modifica/")
    campo = pagina.locator("#id_data_inizio")
    assert campo.input_value() == "01/01/2026"
    campo.click()
    assert pagina.locator(".flatpickr-calendar.open").is_visible()
    campo.fill("15/03/2026")
    pagina.keyboard.press("Escape")
    pagina.click("button[type=submit]:has-text('Salva')")
    pagina.wait_for_url(f"{pagina.base}/contratti/{c.pk}/")
    c.refresh_from_db()
    assert c.data_inizio == datetime.date(2026, 3, 15)


def test_tendina_con_ricerca(pagina, dati):
    c = dati["contratto"]
    pagina.goto(f"{pagina.base}/contratti/{c.pk}/modifica/")
    wrapper = pagina.locator("select#id_fornitore ~ .ts-wrapper")
    assert wrapper.count() == 1  # Tom Select attivo sulla tendina dei fornitori (15 voci)
    wrapper.locator(".ts-control").click()
    # Si scrive solo quando la tendina è aperta e il campo ha il fuoco: digitando subito,
    # i primi caratteri possono andare persi e il filtro non restringe le voci.
    expect(wrapper.locator(".ts-dropdown")).to_be_visible()
    campo = wrapper.locator("input")
    expect(campo).to_be_focused()
    campo.fill("prova 07")
    opzioni = pagina.locator(".ts-dropdown .option:visible")
    expect(opzioni).to_have_count(1)  # il filtro di Tom Select è ritardato di qualche ms
    opzioni.first.click()
    pagina.click("button[type=submit]:has-text('Salva')")
    pagina.wait_for_url(f"{pagina.base}/contratti/{c.pk}/")
    c.refresh_from_db()
    assert c.fornitore == dati["fornitori"][7]


def test_schede_del_dettaglio_e_indirizzo(pagina, dati):
    c = dati["contratto"]
    pagina.goto(f"{pagina.base}/contratti/{c.pk}/#storico")
    assert pagina.locator("#storico").is_visible()
    pagina.click("button[data-bs-target='#voci']")
    assert pagina.locator("#voci").is_visible()
    assert pagina.url.endswith("#voci")


def test_anteprima_scadenzario(pagina, dati):
    c = dati["contratto"]
    pagina.goto(f"{pagina.base}/contratti/{c.pk}/voci/nuova/")
    pagina.fill("#id_voce-descrizione", "Canone trimestrale")
    pagina.fill("#id_voce-importo_fisso", "12.000,00")
    pagina.select_option("#id_piano-modalita", "posticipata")
    pagina.select_option("#id_piano-periodicita", "trimestrale")
    pagina.click("text=Calcola")
    pagina.wait_for_selector("#anteprima table")
    assert "4 rate, totale 12.000,00 €" in pagina.inner_text("#anteprima")


def test_filtri_attivi_e_ordinamento(pagina, dati):
    altro = m.Contratto.objects.create(
        fabbisogno=dati["fabbisogno"],
        fornitore=dati["fornitori"][1],
        procedura=dati["contratto"].procedura,
        data_inizio=datetime.date(2024, 1, 1),
        durata_mesi=12,
        numero_contratto="5800000002",
    )
    pagina.goto(f"{pagina.base}/contratti/?ordina=inizio")
    prima = pagina.locator("#tabella tbody tr").first.inner_text()
    assert "5800000002" in prima  # 2024 prima del 2026
    pagina.goto(f"{pagina.base}/contratti/?ordina=-inizio&area=IT")
    assert "5800000001" in pagina.locator("#tabella tbody tr").first.inner_text()
    chip = pagina.locator(".chip", has_text="Cluster: IT")
    assert chip.is_visible()
    chip.locator("a").click()
    pagina.wait_for_load_state("networkidle")
    assert "area=" not in pagina.url
    assert altro.pk


def test_conferma_in_finestra_modale(pagina, dati):
    v = dati["voce"]
    pagina.goto(f"{pagina.base}/contratti/{dati['contratto'].pk}/#voci")
    pagina.click("button:has-text('Genera scadenzario')")
    modale = pagina.locator("#modale-conferma")
    modale.wait_for(state="visible")
    assert "modificate a mano restano" in modale.inner_text()
    modale.locator("[data-conferma-ok]").click()
    pagina.wait_for_load_state("networkidle")
    assert v.piano_fatturazione.rate.count() == 1


def test_menu_su_tablet(browser, live_server, dati, make_user):
    make_user("e2e_tablet", role="Reader")
    pg = browser.new_page(viewport={"width": 800, "height": 1000})
    pg.goto(f"{live_server.url}/accounts/login/")
    pg.fill("#id_username", "e2e_tablet")
    pg.fill("#id_password", "password-locale-di-prova")
    pg.click("button[type=submit]")
    pg.wait_for_url(f"{live_server.url}/")
    menu = pg.locator("#menu")
    assert not menu.is_visible()
    pg.click("button[aria-controls=menu]")
    menu.locator("a:has-text('Contratti')").click()
    pg.wait_for_url(f"{live_server.url}/contratti/")
    pg.close()


def test_sposta_contratto_con_anteprima_accessibile(pagina, dati):
    """F8: scelta della destinazione con la ricerca, anteprima della catena, conferma."""
    c = dati["contratto"]
    pagina.goto(f"{pagina.base}/contratti/{c.pk}/sposta/")
    wrapper = pagina.locator("select#id_destinazione ~ .ts-wrapper")
    wrapper.locator(".ts-control").click()
    expect(wrapper.locator(".ts-dropdown")).to_be_visible()
    campo = wrapper.locator("input")
    expect(campo).to_be_focused()
    campo.fill("Nuovo servizio")
    opzioni = pagina.locator(".ts-dropdown .option:visible")
    expect(opzioni).to_have_count(1)
    opzioni.first.click()
    expect(wrapper.locator(".ts-dropdown")).to_be_hidden()
    # Con il fuoco la tendina resta su una riga: al blur il pulsante non si sposta e il
    # clic arriva (prima il layout saltava di una riga e il clic si perdeva).
    altezza = wrapper.locator(".ts-control").bounding_box()["height"]
    pagina.click("button[value=anteprima]")
    expect(pagina.locator("text=Di quale contratto è il rinnovo?")).to_be_visible()
    assert altezza < 45
    assert violazioni_axe(pagina) == []
    pagina.click("button[value=conferma]")
    pagina.wait_for_url(f"{pagina.base}/contratti/{c.pk}/")
    c.refresh_from_db()
    assert c.fabbisogno.descrizione == "Nuovo servizio di prova"
    assert not pagina.errori, pagina.errori


def test_import_date_da_interfaccia(pagina, dati, tmp_path):
    """F9.1: carico il file, vedo l'anteprima (accessibile), confermo nella finestra modale."""
    c = dati["contratto"]
    file = tmp_path / "date.csv"
    file.write_text("numero_contratto;data_emissione\n5800000001;15/12/2025\n", encoding="utf-8")
    pagina.goto(f"{pagina.base}/import/")
    pagina.set_input_files("#id_date_emissione-file", str(file))
    pagina.click("form[action$='/date_emissione/'] button[type=submit]")
    expect(pagina.locator("text=Anteprima: nessun dato è stato ancora scritto")).to_be_visible()
    assert violazioni_axe(pagina) == []
    c.refresh_from_db()
    assert c.data_emissione is None
    pagina.click("button:has-text('Conferma l')")
    modale = pagina.locator("#modale-conferma")
    expect(modale).to_be_visible()
    modale.locator("[data-conferma-ok]").click()
    expect(pagina.locator(".sottotitolo .stato-verde")).to_have_text("Importato")
    c.refresh_from_db()
    assert c.data_emissione == datetime.date(2025, 12, 15)
    assert not pagina.errori, pagina.errori
