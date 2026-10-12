"""F9.6: PDF dei report generati dal server (WeasyPrint), A4 orizzontale."""

import datetime
from decimal import Decimal

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from accounts.roles import READER
from contratti import models as m
from reports import pdf

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def dati():
    it = f.cluster("IT")
    conto = m.ContoCoge.objects.create(
        codice="61000001", descrizione="Conto di prova", valido_dal=D(2020, 1, 1), cluster=it
    )
    w = m.WBS.objects.create(
        codice_wbs="X.0001.00.000", descrizione="Investimenti IT", tipo="cluster", cluster=it
    )
    fab = f.fabbisogno("Piattaforma di prova", cluster=it, decisione="rinnovare")
    c = f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12)
    f.piano(f.voce(c, descrizione="Supporto", conto=conto, importo_fisso=Decimal("6000.00")))
    v = f.voce(c, descrizione="Licenze", natura="CAPEX", wbs=w, conto=conto,
               importo_fisso=Decimal("10000.00"))  # fmt: skip
    f.piano(v, modalita=m.ModalitaFatturazione.UNA_TANTUM, periodicita="")
    return {"wbs": w}


@pytest.fixture
def lettore(make_user):
    make_user("u_reader", role=READER)
    client = Client()
    client.login(username="u_reader", password="password-locale-di-prova")
    return client


@pytest.fixture
def catturato(monkeypatch):
    """Template e contesto passati a WeasyPrint, per controllare impaginazione e contenuto."""
    visto = {}
    originale = pdf.genera

    def genera(template, contesto, request=None):
        visto.update(template=template, contesto=contesto, request=request)
        return originale(template, contesto, request)

    monkeypatch.setattr(pdf, "genera", genera)
    return visto


def _scarica(client, url):
    r = client.get(url)
    assert r.status_code == 200
    assert r["Content-Type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
    return r


def _a4_orizzontale(visto):
    doc = pdf.documento(visto["template"], visto["contesto"], visto["request"])
    for pagina in doc.pages:  # px CSS: 297 × 210 mm
        assert round(pagina.width * 25.4 / 96) == 297
        assert round(pagina.height * 25.4 / 96) == 210
    return doc


def test_budget_pdf_a4_orizzontale_con_i_totali(dati, lettore, catturato):
    url = reverse("reports:budget") + "?anno=2026&area=tutti&formato=pdf"
    r = _scarica(lettore, url)
    assert r["Content-Disposition"].endswith('_Budget_2026_OPEX.pdf"')
    _a4_orizzontale(catturato)
    html = render_to_string(catturato["template"], catturato["contesto"])
    assert "Budget OPEX 2026" in html and "6.000,00 €" in html and "Totale OPEX" in html
    assert "Dettaglio delle voci" not in html


def test_budget_pdf_opex_e_capex_con_dettaglio(dati, lettore, catturato):
    url = reverse("reports:budget") + "?anno=2026&area=tutti&natura=&dettaglio=1&formato=pdf"
    assert _scarica(lettore, url)["Content-Disposition"].endswith('_Budget_2026_OPEX_CAPEX.pdf"')
    doc = _a4_orizzontale(catturato)
    assert len(doc.pages) >= 2  # la sezione CAPEX parte su una pagina nuova
    html = render_to_string(catturato["template"], catturato["contesto"])
    assert "Budget CAPEX 2026" in html and "10.000,00 €" in html
    assert "Dettaglio delle voci OPEX" in html and "Piattaforma di prova — Supporto" in html


def test_piano_ordini_e_spese_wbs_pdf(dati, lettore, catturato):
    r = _scarica(lettore, reverse("reports:piano_ordini") + "?anno=2027&area=tutti&formato=pdf")
    assert r["Content-Disposition"].endswith('_Piano_ordini_2027.pdf"')
    _a4_orizzontale(catturato)
    assert "Piattaforma di prova" in render_to_string(catturato["template"], catturato["contesto"])
    r = _scarica(lettore, reverse("reports:wbs_spese", args=[dati["wbs"].pk]) + "?formato=pdf")
    assert r["Content-Disposition"].endswith('_Spese_WBS_X.0001.00.000.pdf"')
    _a4_orizzontale(catturato)


def test_pulsante_pdf_al_posto_della_stampa(dati, lettore):
    html = lettore.get(reverse("reports:budget") + "?anno=2026").content.decode()
    assert "Scarica PDF" in html and "PDF con il dettaglio delle voci" in html
    assert "window.print" not in html


def test_nel_pdf_solo_file_locali():
    with pytest.raises(ValueError):
        pdf._solo_statici("https://example.com/logo.png")
    with pytest.raises(ValueError):
        pdf._solo_statici(pdf._url("css/pdf.css").replace("css/pdf.css", "../config/settings"))
    assert pdf._solo_statici(pdf._url("css/pdf.css"))


def test_cluster_in_evidenza_nel_pdf(dati, lettore, catturato):
    """Il PDF dice sempre quali cluster comprende: sotto il titolo, in testata e nel nome."""
    f.cluster("TLC")
    url = reverse("reports:budget") + "?anno=2026&area=IT&area=TLC&formato=pdf"
    r = _scarica(lettore, url)
    assert r["Content-Disposition"].endswith('_Budget_2026_OPEX_IT-TLC.pdf"')
    html = render_to_string(catturato["template"], catturato["contesto"])
    assert '<span class="filtro">Cluster: IT, TLC</span>' in html
    assert "Registro contratti ICTDINN · Cluster: IT, TLC" in html
    r = _scarica(lettore, reverse("reports:budget") + "?anno=2026&area=tutti&formato=pdf")
    assert r["Content-Disposition"].endswith('_Budget_2026_OPEX.pdf"')
    assert '<span class="filtro">Cluster: tutti</span>' in render_to_string(
        catturato["template"], catturato["contesto"]
    )
    url = reverse("reports:piano_ordini") + "?anno=2027&area=IT&formato=pdf"
    assert _scarica(lettore, url)["Content-Disposition"].endswith('_Piano_ordini_2027_IT.pdf"')
    assert '<span class="filtro">Cluster: IT</span>' in render_to_string(
        catturato["template"], catturato["contesto"]
    )


def test_piano_ordini_pdf_avvisi_di_frazionamento_solo_a_richiesta(dati, lettore, catturato):
    url = reverse("reports:piano_ordini") + "?anno=2027&area=tutti&formato=pdf"
    _scarica(lettore, url)
    assert "Possibile frazionamento" not in render_to_string(
        catturato["template"], catturato["contesto"]
    )
    _scarica(lettore, url + "&dettaglio=1")
    assert "Possibile frazionamento" in render_to_string(
        catturato["template"], catturato["contesto"]
    )
    html = lettore.get(reverse("reports:piano_ordini") + "?anno=2027").content.decode()
    assert "PDF con gli avvisi di frazionamento" in html
