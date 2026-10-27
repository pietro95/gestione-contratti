"""Quote per periodo nel form della voce: righe aggiunte e tolte nel browser, un solo salvataggio.

Caso: voce a SAL di lavori; quattro quote ad anno solare (2024 a 0,00) inserite in un colpo
solo, senza salvare una volta per riga. Errori sulla riga che li causa, senza perdere
quanto digitato.
"""

from decimal import Decimal

import pytest
from playwright.sync_api import expect

from contratti import models as m

from .. import factories as f
from .conftest import D, violazioni_axe

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]

QUOTE = [
    ("01/01/2024", "31/12/2024", "0,00"),
    ("01/01/2025", "31/12/2025", "1.486.870,87"),
    ("01/01/2026", "31/12/2026", "1.144.060,62"),
    ("01/01/2027", "31/12/2027", "316.708,26"),
]


@pytest.fixture
def lavori(dati):
    c = f.contratto(
        fabbisogno=f.fabbisogno("Lavori impianto di prova"),
        data_inizio=D(2024, 10, 15),
        durata_mesi=29,
        data_fine_override=D(2027, 3, 31),
        numero_contratto="5800000230",
    )
    voce = f.voce(c, descrizione="Lavori", importo_fisso=Decimal("2947639.75"))
    f.piano(voce, modalita="sal", periodicita="")
    return voce


def _apri(pagina, voce):
    pagina.goto(f"{pagina.base}/contratti/{voce.contratto_id}/voci/{voce.pk}/")


def _riempi(pagina, indice, dal, al, importo):
    for campo, valore in (("dal", dal), ("al", al), ("importo", importo)):
        pagina.fill(f"#id_quote-{indice}-{campo}", valore)
        pagina.keyboard.press("Tab")  # chiude il calendario, che coprirebbe i pulsanti
    pagina.keyboard.press("Escape")


def _salva(pagina):
    pagina.click("#voce-form button[type=submit]")


def test_quattro_quote_in_un_colpo_solo(pagina, lavori):
    _apri(pagina, lavori)
    righe = pagina.locator("#quote-forms tr[data-riga-form]")
    expect(righe).to_have_count(1)  # senza JavaScript resterebbe questa sola riga
    for _ in range(3):
        pagina.click("button[data-aggiungi-form=quote]")
    expect(righe).to_have_count(4)
    assert pagina.locator("#id_quote-TOTAL_FORMS").input_value() == "4"
    for i, quota in enumerate(QUOTE):
        _riempi(pagina, i, *quota)
    assert m.QuotaPeriodo.objects.count() == 0  # niente salvato finora

    _salva(pagina)
    pagina.wait_for_url(f"**/contratti/{lavori.contratto_id}/")
    quote = list(lavori.quote.order_by("dal"))
    assert [(q.dal.year, q.importo) for q in quote] == [
        (2024, Decimal("0.00")),
        (2025, Decimal("1486870.87")),
        (2026, Decimal("1144060.62")),
        (2027, Decimal("316708.26")),
    ]
    assert pagina.errori == []


def test_tre_righe_aggiunte_senza_salvare_e_una_sola_conferma(pagina, lavori):
    _apri(pagina, lavori)
    pagina.click("button[data-aggiungi-form=quote]")
    pagina.click("button[data-aggiungi-form=quote]")  # la riga vuota già presente + due
    for i, quota in enumerate(QUOTE[1:]):
        _riempi(pagina, i, *quota)
    _salva(pagina)
    pagina.wait_for_url(f"**/contratti/{lavori.contratto_id}/")
    assert lavori.quote.count() == 3


def test_riga_non_salvata_si_rimuove_e_non_viene_inviata(pagina, lavori):
    _apri(pagina, lavori)
    for _ in range(3):
        pagina.click("button[data-aggiungi-form=quote]")
    _riempi(pagina, 0, *QUOTE[1])
    _riempi(pagina, 1, *QUOTE[0])  # da togliere
    _riempi(pagina, 2, *QUOTE[2])
    _riempi(pagina, 3, *QUOTE[3])
    pagina.locator("#quote-forms tr[data-riga-form]").nth(1).locator("[data-rimuovi-form]").click()
    expect(pagina.locator("#quote-forms tr[data-riga-form]:visible")).to_have_count(3)
    _salva(pagina)
    pagina.wait_for_url(f"**/contratti/{lavori.contratto_id}/")
    assert sorted(q.dal.year for q in lavori.quote.all()) == [2025, 2026, 2027]


def test_errore_sulla_riga_giusta_senza_perdere_quanto_digitato(pagina, lavori):
    _apri(pagina, lavori)
    for _ in range(2):
        pagina.click("button[data-aggiungi-form=quote]")
    _riempi(pagina, 0, *QUOTE[1])
    _riempi(pagina, 1, "01/06/2025", "31/12/2026", "1.000,00")  # si sovrappone alla riga 1
    _riempi(pagina, 2, *QUOTE[3])
    _salva(pagina)

    # Nessun salvataggio: la pagina si ripresenta con tre righe, l'errore sulla seconda.
    expect(pagina.locator(".alert-danger", has_text="Le quote hanno degli errori")).to_be_visible()
    righe = pagina.locator("#quote-forms tr[data-riga-form]")
    expect(righe).to_have_count(3)
    expect(righe.nth(1).locator(".invalid-feedback")).to_contain_text("ovrappone")
    expect(righe.nth(0).locator(".invalid-feedback")).to_have_count(0)
    expect(righe.nth(2).locator(".invalid-feedback")).to_have_count(0)
    assert pagina.input_value("#id_quote-0-importo") in ("1.486.870,87", "1486870.87")
    assert pagina.input_value("#id_quote-1-dal") == "01/06/2025"
    assert pagina.input_value("#id_quote-2-al") == "31/12/2027"
    assert lavori.quote.count() == 0
    assert violazioni_axe(pagina) == []

    # Si corregge la riga e si salva: ora passano tutte insieme.
    _riempi(pagina, 1, *QUOTE[2])
    _salva(pagina)
    pagina.wait_for_url(f"**/contratti/{lavori.contratto_id}/")
    assert lavori.quote.count() == 3


def test_somma_oltre_il_fisso_non_si_salva(pagina, lavori):
    _apri(pagina, lavori)
    _riempi(pagina, 0, "01/01/2025", "31/12/2025", "3.000.000,00")
    _salva(pagina)
    expect(pagina.locator(".alert-danger", has_text="supera l'importo fisso")).to_be_visible()
    assert lavori.quote.count() == 0


def test_quote_salvate_si_modificano_e_si_eliminano(pagina, lavori):
    for dal, al, importo in QUOTE:
        m.QuotaPeriodo.objects.create(
            voce=lavori,
            dal=D(int(dal[-4:]), 1, 1),
            al=D(int(al[-4:]), 12, 31),
            importo=Decimal(importo.replace(".", "").replace(",", ".")),
        )
    _apri(pagina, lavori)
    righe = pagina.locator("#quote-forms tr[data-riga-form]")
    expect(righe).to_have_count(5)  # quattro salvate + la riga vuota
    pagina.fill("#id_quote-2-importo", "1.000,00")
    pagina.check("#id_quote-0-DELETE")  # la quota 2024 si elimina
    pagina.click("button[data-aggiungi-form=quote]")
    _salva(pagina)
    pagina.wait_for_url(f"**/contratti/{lavori.contratto_id}/")
    assert [(q.dal.year, q.importo) for q in lavori.quote.order_by("dal")] == [
        (2025, Decimal("1486870.87")),
        (2026, Decimal("1000.00")),
        (2027, Decimal("316708.26")),
    ]
    # La quota eliminata resta nella storia, con i suoi valori.
    storia = m.QuotaPeriodo.history.filter(history_type="-")
    assert [(s.dal.year, s.importo) for s in storia] == [(2024, Decimal("0.00"))]
    assert "eliminata" in storia[0].history_change_reason
