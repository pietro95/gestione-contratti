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

LINK_AMMESSI = [
    "https://sharepoint.example/documenti/1",
    "https://sharepoint/documenti/1",  # host interno senza dominio
    "http://10.0.0.5:8080/doc",
    "smb://nas01/share/x",
    "smb://server/share/cartella",
    "smb://10.0.0.5/share",
    "smb://nas.esempio.test/Share/ICTDINN/00_IT/Contratti/2026",
    "smb://nas01/Share/Contratti 2026/Fornitore Esempio",  # spazi nei nomi delle cartelle
    "smb://nas01:445/share",
    "file://nas01/share/x",
    "file:///X:/ICTDINN/Contratti",
]
LINK_RIFIUTATI = [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "ftp://nas01/x",
    "smb:/",
    "smb://",
    "smb:///share",  # senza host
    "file://",
    "smb://nas01/share/<x>",
    "smb://nas01/sh\\are",  # barre inverse nel percorso
    "https://nas 01/x",
]


def _form_contratto(**kw):
    return web_forms.ContrattoForm(
        {
            "fabbisogno": f.fabbisogno().pk,
            "fornitore": f.fornitore().pk,
            "procedura": f.procedura().pk,
            "data_inizio": "01/01/2026",
            "durata_mesi": 12,
            **kw,
        }
    )


@pytest.mark.parametrize("link", LINK_AMMESSI)
def test_link_documenti_ammessi(link):
    form = _form_contratto(link_documenti=link)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["link_documenti"] == link
    contratto = f.contratto(link_documenti=link)
    contratto.full_clean()  # lo stesso validatore sul modello


@pytest.mark.parametrize("link", LINK_RIFIUTATI)
def test_link_documenti_rifiutati(link):
    form = _form_contratto(link_documenti=link)
    assert not form.is_valid() and "link_documenti" in form.errors
    contratto = f.contratto()
    contratto.link_documenti = link
    with pytest.raises(ValidationError):
        contratto.full_clean()


def test_link_documenti_vuoto_e_facoltativo():
    form = _form_contratto(link_documenti="")
    assert form.is_valid(), form.errors
    f.contratto(link_documenti="").full_clean()


def test_link_documenti_oltre_500_caratteri_rifiutato():
    lungo = "smb://nas01/share/" + "a" * 483  # 501 caratteri
    assert len(lungo) == 501
    assert "link_documenti" in _form_contratto(link_documenti=lungo).errors
    esatto = lungo[:-1]
    assert _form_contratto(link_documenti=esatto).is_valid()


def test_link_documenti_senza_schema_resta_https():
    form = _form_contratto(link_documenti="sharepoint.example/doc")
    assert form.is_valid(), form.errors
    assert form.cleaned_data["link_documenti"] == "https://sharepoint.example/doc"


@pytest.mark.parametrize(
    ("unc", "atteso"),
    [
        (r"\\nas01\share\Contratti\2026", "file://nas01/share/Contratti/2026"),
        (r"\\10.0.0.5\share", "file://10.0.0.5/share"),
    ],
)
def test_percorso_unc_normalizzato_in_file(unc, atteso):
    form = _form_contratto(link_documenti=unc)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["link_documenti"] == atteso


def test_unc_malformato_rifiutato():
    assert "link_documenti" in _form_contratto(link_documenti=r"\\\nas01\share").errors


def test_link_esistenti_non_vengono_modificati(editor):
    """Il validatore non tocca i dati: un link già salvato resta com'è."""
    c = f.contratto(link_documenti="https://vecchio.example/doc")
    m.Contratto.objects.filter(pk=c.pk).update(link_documenti="smb://nas01/share/x")
    c.refresh_from_db()
    assert c.link_documenti == "smb://nas01/share/x"


def test_pagina_contratto_http_si_apre_smb_si_copia(editor):
    http = f.contratto(link_documenti="https://sharepoint/documenti/1")
    smb = f.contratto(link_documenti="smb://nas01/Share/Contratti")
    html_http = editor.get(reverse("contratti:contratto", args=[http.pk])).content.decode()
    assert 'href="https://sharepoint/documenti/1"' in html_http
    assert "Copia il link ai documenti" not in html_http
    html_smb = editor.get(reverse("contratti:contratto", args=[smb.pk])).content.decode()
    assert 'href="smb://nas01/Share/Contratti"' in html_smb  # resta un link
    assert 'data-copia-testo="smb://nas01/Share/Contratti"' in html_smb  # e testo copiabile
    assert "\\\\nas01\\Share\\Contratti" in html_smb  # percorso di Windows


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


def test_tutti_i_form_del_contratto_usano_lo_stesso_campo_link():
    """Interfaccia e connettore (crea, modifica, rinnovo) passano da questi form."""
    from contratti.models import LinkDocumentiFormField

    for classe in (
        web_forms.ContrattoForm,
        web_forms.ContrattoNuovoForm,
        web_forms.RinnovoForm,
        web_forms.RinnovoSenzaContrattoForm,
    ):
        campo = classe().fields.get("link_documenti")
        assert isinstance(campo, LinkDocumentiFormField), classe.__name__
        assert campo.max_length == 500
