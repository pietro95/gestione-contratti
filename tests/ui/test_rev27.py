"""Rev27: campi del fabbisogno, link ai documenti sul NAS, consumo senza rate programmate,
competenza dichiarata dal referente."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from contratti import forms as web_forms
from contratti import models as m
from contratti import servizi

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


def _dati_fabbisogno(**kw):
    dati = {
        "descrizione": "Servizio di prova",
        "cluster": f.cluster("IT").pk,
        "sottocluster": f.sottocluster().pk,
        "decisione": "da_valutare",
    }
    return dati | kw


# --- Campi del fabbisogno -----------------------------------------------------------------


def test_fabbisogno_salva_motivazione_priorita_tipo_fonte_e_una_tantum():
    form = web_forms.FabbisognoForm(
        _dati_fabbisogno(
            motivazione="Sostituzione apparati a fine vita",
            priorita="necessaria",
            tipo_acquisto="fornitura",
            fonte_stima="preventivo",
            una_tantum="on",
            note="Preventivo del 10/10",
        )
    )
    assert form.is_valid(), form.errors
    fab = form.save()
    assert (fab.priorita, fab.tipo_acquisto, fab.fonte_stima) == (
        "necessaria",
        "fornitura",
        "preventivo",
    )
    assert fab.una_tantum and fab.motivazione and fab.note


@pytest.mark.parametrize(
    ("campo", "valore"),
    [("priorita", "urgente"), ("tipo_acquisto", "noleggio"), ("fonte_stima", "intuito")],
)
def test_fabbisogno_valori_non_ammessi(campo, valore):
    form = web_forms.FabbisognoForm(_dati_fabbisogno(**{campo: valore}))
    assert not form.is_valid() and campo in form.errors


def test_fabbisogno_i_nuovi_campi_sono_facoltativi():
    fab = web_forms.FabbisognoForm(_dati_fabbisogno()).save()
    assert fab.priorita == fab.tipo_acquisto == fab.fonte_stima == "" and not fab.una_tantum


# --- Link ai documenti: anche il NAS ------------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        "https://sharepoint.example/documenti/1",
        "smb://nas.esempio.test/Share/ICTDINN/00_IT/Contratti/2026",
        "file://nas.esempio.test/Share/ICTDINN",
        "file:///X:/ICTDINN/Contratti",
    ],
)
def test_link_documenti_ammette_http_smb_e_file(link):
    form = web_forms.ContrattoForm(
        {
            "fabbisogno": f.fabbisogno().pk,
            "fornitore": f.fornitore().pk,
            "procedura": f.procedura().pk,
            "data_inizio": "01/01/2026",
            "durata_mesi": 12,
            "link_documenti": link,
        }
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["link_documenti"] == link
    contratto = f.contratto(link_documenti=link)
    contratto.full_clean()  # lo stesso validatore sul modello


@pytest.mark.parametrize("link", ["ftp://nas.esempio.test/x", "javascript:alert(1)", "smb:/"])
def test_link_documenti_rifiuta_gli_altri_schemi(link):
    contratto = f.contratto()
    contratto.link_documenti = link
    with pytest.raises(ValidationError):
        contratto.full_clean()


# --- A consumo: nessuna rata programmata -----------------------------------------------------


def test_consumo_non_genera_rate():
    # Fornitura a consumo con fisso 0 e massimale 20.000 (era: 24 rate mensili da 0,00).
    c = f.contratto(data_inizio=D(2026, 3, 1), durata_mesi=24)
    v = f.voce(c, importo_fisso=Decimal("0.00"), massimale_variabile=Decimal("20000.00"))
    piano = f.piano(v, modalita="consumo", periodicita="", data_prima_fattura=D(2026, 2, 28))
    assert servizi.genera_scadenzario(v) == []
    assert piano.rate.count() == 0


def test_consumo_rigenera_e_toglie_le_vecchie_rate_generate():
    c = f.contratto(data_inizio=D(2026, 3, 1), durata_mesi=24)
    v = f.voce(c, importo_fisso=Decimal("0.00"), massimale_variabile=Decimal("20000.00"))
    piano = f.piano(v, modalita="consumo", periodicita="")
    f.rata(piano, numero=1, importo=Decimal("0.00"))
    assert servizi.genera_scadenzario(v) == [] and piano.rate.count() == 0


def test_piano_a_consumo_azzera_periodicita_e_prima_fattura():
    form = web_forms.PianoForm(
        {
            "modalita": "consumo",
            "periodicita": "mensile",
            "data_prima_fattura": "28/02/2026",
            "giorni_pagamento": "",
        }
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["periodicita"] == ""
    assert form.cleaned_data["data_prima_fattura"] is None


# --- Competenza dichiarata -------------------------------------------------------------------


@pytest.fixture
def fab_con_contratto():
    fab = f.fabbisogno("Vigilanza", decisione="rinnovare", sottocluster=f.sottocluster())
    c = f.contratto(fabbisogno=fab, data_inizio=D(2027, 1, 1), durata_mesi=12)
    v = f.voce(c, importo_fisso=Decimal("11393.00"))
    f.piano(v, modalita="anticipata", periodicita="annuale")
    f.rata(
        v.piano_fatturazione,
        data_fattura=D(2027, 1, 1),
        data_pagamento_stimata=D(2027, 3, 31),
        importo=Decimal("11393.00"),
    )
    return fab


def test_competenza_dichiarata_una_per_anno_e_natura(fab_con_contratto):
    a = servizi.dichiara_competenza(fab_con_contratto, 2027, "OPEX", Decimal("10000"), "referente")
    b = servizi.dichiara_competenza(fab_con_contratto, 2027, "OPEX", Decimal("10500"))
    assert a.pk == b.pk and b.importo == Decimal("10500") and b.note == ""
    servizi.dichiara_competenza(fab_con_contratto, 2027, "CAPEX", Decimal("500"))
    assert m.CompetenzaDichiarata.objects.count() == 2
    assert b.history.count() == 2  # la storia conserva il valore di prima


def test_competenza_dichiarata_confronto_con_il_calcolo(fab_con_contratto):
    from reports.competenza import confronto

    servizi.dichiara_competenza(fab_con_contratto, 2027, "OPEX", Decimal("10000.00"))
    (riga,) = confronto(fab_con_contratto, D(2026, 10, 22))
    assert riga.dichiarato == Decimal("10000.00")
    assert riga.probabile == Decimal("11393.00")
    assert riga.scostamento == Decimal("-1393.00")


def test_pagina_fabbisogno_mostra_il_confronto(editor, fab_con_contratto):
    servizi.dichiara_competenza(fab_con_contratto, 2027, "OPEX", Decimal("10000.00"))
    pagina = editor.get(reverse("contratti:fabbisogno", args=[fab_con_contratto.pk]))
    assert pagina.status_code == 200
    html = pagina.content.decode()
    assert "Competenza dichiarata" in html and "10.000,00" in html and "11.393,00" in html


def test_editor_dichiara_e_toglie(editor, fab_con_contratto):
    url = reverse("contratti:fabbisogno_competenza", args=[fab_con_contratto.pk])
    r = editor.post(url, {"anno": 2027, "natura": "OPEX", "importo": "10.000,00", "note": "x"})
    assert r.status_code == 302
    (d,) = m.CompetenzaDichiarata.objects.all()
    assert d.importo == Decimal("10000.00")
    r = editor.post(reverse("contratti:archivia", args=["competenza", d.pk]))
    d.refresh_from_db()
    assert r.status_code == 302 and d.archiviato


def test_competenza_dichiarata_non_valida_non_si_salva(editor, fab_con_contratto):
    url = reverse("contratti:fabbisogno_competenza", args=[fab_con_contratto.pk])
    editor.post(url, {"anno": 2027, "natura": "OPEX", "importo": "-5"})
    assert not m.CompetenzaDichiarata.objects.exists()


def test_reader_non_dichiara_ne_toglie(reader, fab_con_contratto):
    url = reverse("contratti:fabbisogno_competenza", args=[fab_con_contratto.pk])
    assert reader.post(url, {"anno": 2027, "natura": "OPEX", "importo": "1"}).status_code == 403
    d = servizi.dichiara_competenza(fab_con_contratto, 2027, "OPEX", Decimal("1"))
    assert reader.post(reverse("contratti:archivia", args=["competenza", d.pk])).status_code == 403
    assert not m.CompetenzaDichiarata.objects.get().archiviato
