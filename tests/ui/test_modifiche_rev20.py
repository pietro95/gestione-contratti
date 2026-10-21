"""Rev20: sottocluster obbligatorio, referente a tendina, fornitore dalla creazione del contratto,
tipo d'acquisto, altri importi in fattura, correzione dei documenti SAP, fatturato pregresso."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from contratti import fatture
from contratti import forms as web_forms
from contratti import models as m
from contratti.engine import acquisti as motore

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
DEC = Decimal


# --- Fabbisogno: sottocluster obbligatorio, referente tra gli utenti -------------------------


def _dati_fabbisogno(**kw):
    dati = {
        "descrizione": "Servizio di prova",
        "cluster": f.cluster("IT").pk,
        "sottocluster": f.sottocluster().pk,
        "decisione": "da_valutare",
    }
    return dati | kw


def test_fabbisogno_senza_sottocluster_non_si_salva():
    form = web_forms.FabbisognoForm(_dati_fabbisogno(sottocluster=""))
    assert not form.is_valid() and "sottocluster" in form.errors
    assert web_forms.FabbisognoForm(_dati_fabbisogno()).is_valid()


def test_fabbisogno_importato_senza_sottocluster_resta_modificabile():
    legacy = f.fabbisogno("Importato")  # nessun sottocluster
    form = web_forms.FabbisognoForm(
        _dati_fabbisogno(descrizione="Importato", sottocluster=""), instance=legacy
    )
    assert form.is_valid(), form.errors
    # Ma uno già classificato non perde il sottocluster.
    classificato = f.fabbisogno("Classificato", sottocluster=f.sottocluster())
    form = web_forms.FabbisognoForm(
        _dati_fabbisogno(descrizione="Classificato", sottocluster=""), instance=classificato
    )
    assert not form.is_valid() and "sottocluster" in form.errors


def test_fabbisogno_non_ha_piu_categoria_e_impianto():
    campi = set(web_forms.FabbisognoForm().fields)
    assert "categoria" not in campi and "impianto" not in campi
    assert "referente_utente" in campi and "referente" not in campi


def test_referente_dalla_tendina_degli_utenti(make_user):
    rossi = make_user("rossi", first_name="Mario", last_name="Rossi")
    make_user("spento", is_active=False)
    form = web_forms.FabbisognoForm(_dati_fabbisogno(referente_utente=rossi.pk))
    assert {u.username for u in form.fields["referente_utente"].queryset} == {"rossi"}
    assert form.is_valid(), form.errors
    fab = form.save()
    assert fab.referente_utente == rossi and fab.referente == "Rossi Mario"
    # Tolto il referente: non resta il nome di prima.
    form = web_forms.FabbisognoForm(_dati_fabbisogno(referente_utente=""), instance=fab)
    assert form.is_valid(), form.errors
    fab = form.save()
    assert fab.referente_utente is None and fab.referente == ""


# --- Contratto: sottocluster obbligatorio, fornitore nuovo, tipo d'acquisto -----------------


def _dati_contratto(fab, **kw):
    dati = {
        "fabbisogno": fab.pk,
        "fornitore": f.fornitore().pk,
        "descrizione": "Canone",
        "tipo_acquisto": "servizio",
        "procedura": f.procedura().pk,
        "data_inizio": "01/01/2026",
        "durata_mesi": 12,
    }
    return dati | kw


def test_contratto_nuovo_richiede_il_sottocluster():
    fab = f.fabbisogno("Senza sottocluster")
    form = web_forms.ContrattoNuovoForm(_dati_contratto(fab))
    assert not form.is_valid() and "sottocluster" in form.errors
    form = web_forms.ContrattoNuovoForm(_dati_contratto(fab, sottocluster=f.sottocluster().pk))
    assert form.is_valid(), form.errors
    contratto = form.save()
    contratto.fabbisogno.refresh_from_db()
    assert contratto.fabbisogno.sottocluster == f.sottocluster()  # impostato sul fabbisogno


def test_contratto_nuovo_usa_il_sottocluster_del_fabbisogno():
    fab = f.fabbisogno("Con sottocluster", sottocluster=f.sottocluster())
    assert web_forms.ContrattoNuovoForm(_dati_contratto(fab)).is_valid()


def test_sottocluster_di_un_altro_cluster_rifiutato():
    fab = f.fabbisogno("IT", sottocluster=f.sottocluster())
    altro = f.sottocluster("Telefonia", "TLC")
    form = web_forms.ContrattoNuovoForm(_dati_contratto(fab, sottocluster=altro.pk))
    assert not form.is_valid() and "sottocluster" in form.errors


def test_nuovo_fornitore_dalla_creazione_del_contratto():
    fab = f.fabbisogno("Con sottocluster", sottocluster=f.sottocluster())
    dati = _dati_contratto(
        fab,
        fornitore="",
        nuovo_fornitore="Fornitore Nuovo S.r.l.",
        nuovo_fornitore_piva="01234567890",
        nuovo_fornitore_codice_sap="20009999",
    )
    form = web_forms.ContrattoNuovoForm(dati)
    assert form.is_valid(), form.errors
    contratto = form.save()
    assert contratto.fornitore.ragione_sociale == "Fornitore Nuovo S.r.l."
    assert contratto.fornitore.partita_iva == "01234567890"
    assert contratto.fornitore.codice_sap == "20009999"


def test_fornitore_obbligatorio_e_non_doppio():
    fab = f.fabbisogno("Con sottocluster", sottocluster=f.sottocluster())
    senza = web_forms.ContrattoNuovoForm(_dati_contratto(fab, fornitore=""))
    assert not senza.is_valid() and "fornitore" in senza.errors
    doppio = web_forms.ContrattoNuovoForm(_dati_contratto(fab, nuovo_fornitore="Altro S.r.l."))
    assert not doppio.is_valid() and "nuovo_fornitore" in doppio.errors
    esistente = f.fornitore("Già Qui", partita_iva="09876543210")
    doppia_piva = web_forms.ContrattoNuovoForm(
        _dati_contratto(
            fab, fornitore="", nuovo_fornitore="Clone", nuovo_fornitore_piva="09876543210"
        )
    )
    assert not doppia_piva.is_valid() and "nuovo_fornitore_piva" in doppia_piva.errors
    assert esistente.contratti.count() == 0


def test_tipo_acquisto_servizi_lavori_o_forniture():
    fab = f.fabbisogno("Con sottocluster", sottocluster=f.sottocluster())
    form = web_forms.ContrattoNuovoForm(_dati_contratto(fab, tipo_acquisto="fornitura"))
    assert form.is_valid(), form.errors
    contratto = form.save()
    assert contratto.get_tipo_acquisto_display() == "Forniture"
    assert m.Contratto.TipoAcquisto.SERVIZIO.label == "Servizi / lavori"
    assert fatture.documento_proposto(m.Fattura(contratto=contratto)) == "MIGO"


def test_creazione_contratto_dalla_vista(editor):
    fab = f.fabbisogno("Con sottocluster", sottocluster=f.sottocluster())
    dati = _dati_contratto(fab, fornitore="", nuovo_fornitore="Aperto Qui S.r.l.")
    risposta = editor.post(reverse("contratti:contratto_nuovo"), dati)
    assert risposta.status_code == 302
    assert m.Contratto.objects.get().fornitore.ragione_sociale == "Aperto Qui S.r.l."


# --- Altri importi in fattura ------------------------------------------------------------------


def test_altri_importi_nel_motore():
    # 1.220 con IVA, di cui 100 di more non imputabili: base 1.000, IVA 220, altri 100.
    assert not motore.importo_quadra(DEC("1320.00"), DEC("1000.00"), None, None, DEC("220.00"))
    assert motore.importo_quadra(
        DEC("1320.00"), DEC("1000.00"), None, None, DEC("220.00"), DEC("100.00")
    )
    assert motore.valore_base_proposto(
        DEC("1320.00"), DEC("20.00"), DEC("2.00"), DEC("100.00")
    ) == DEC("1198.00")
    assert motore.iva_riconosciuta(
        DEC("1320.00"), DEC("1000.00"), None, None, [DEC("22")], DEC("100.00")
    ) == (DEC("22"), DEC("220.00"))
    assert motore.scorporo_iva(DEC("1320.00"), None, None, DEC("22"), DEC("100.00")) == (
        DEC("1000.00"),
        DEC("220.00"),
    )


def _fattura(importo="1320.00"):
    c = f.contratto(data_inizio=D(2026, 1, 1))
    f.voce(c, importo_fisso=DEC("5000.00"))
    return m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, numero="1/2026", data=D(2026, 3, 1),
        importo_documento=DEC(importo),
    )  # fmt: skip


def test_scorporo_toglie_gli_altri_importi():
    fa = _fattura()
    fatture.salva_importi(
        fa,
        {
            "altri_importi": DEC("100.00"),
            "competenza_dal": D(2026, 2, 1),
            "competenza_al": D(2026, 2, 28),
        },
        aliquota_scorporo=DEC("22"),
    )
    fa.refresh_from_db()
    assert (fa.valore_base, fa.iva, fa.altri_importi) == (
        DEC("1000.00"),
        DEC("220.00"),
        DEC("100.00"),
    )
    assert fatture.anomalie(fa) == []


def test_altri_importi_riconosciuti_e_quadratura():
    fa = _fattura()
    fatture.salva_importi(
        fa,
        {
            "valore_base": DEC("1000.00"),
            "altri_importi": DEC("100.00"),
            "competenza_dal": D(2026, 2, 1),
            "competenza_al": D(2026, 2, 28),
        },
    )
    fa.refresh_from_db()
    assert fa.iva == DEC("220.00") and fatture.anomalie(fa) == []
    # Senza gli altri importi la fattura non quadra più.
    fatture.salva_importi(
        fa,
        {
            "valore_base": DEC("1000.00"),
            "iva": DEC("220.00"),
            "competenza_dal": D(2026, 2, 1),
            "competenza_al": D(2026, 2, 28),
        },
    )
    fa.refresh_from_db()
    assert fatture.anomalie(fa) == ["IMPORTO_NON_QUADRA"]


def test_la_vista_importi_registra_gli_altri_importi(editor):
    fa = _fattura()
    risposta = editor.post(
        reverse("contratti:fattura_importi", args=[fa.pk]),
        {
            "valore_base": "1.000,00",
            "iva": "220,00",
            "altri_importi": "100,00",
            "competenza_dal": "01/02/2026",
            "competenza_al": "28/02/2026",
        },
    )
    assert risposta.status_code == 302
    fa.refresh_from_db()
    assert fa.altri_importi == DEC("100.00") and fa.valore_base == DEC("1000.00")
    pagina = editor.get(reverse("contratti:fattura", args=[fa.pk])).content.decode()
    assert "IVA compresa" not in pagina and "non imputabili al nostro ufficio" in pagina


# --- Documenti SAP della fattura: modifica e rimozione -----------------------------------------


@pytest.fixture
def con_documento():
    fa = _fattura()
    doc = fatture.registra_documento(fa, "MAP", "100200300", D(2026, 3, 10))
    return fa, doc


def test_modifica_del_documento(editor, con_documento):
    fa, doc = con_documento
    risposta = editor.post(
        reverse("contratti:fattura_documento_modifica", args=[fa.pk, doc.pk]),
        {"tipo": "ODA_RDC", "numero": "4500000001", "data": "12/03/2026"},
    )
    assert risposta.status_code == 302
    doc.refresh_from_db()
    assert (doc.tipo, doc.numero, doc.data) == ("ODA_RDC", "4500000001", D(2026, 3, 12))
    assert doc.history.count() == 2  # storia della correzione


def test_una_sola_rdc_anche_modificando(editor, con_documento):
    fa, doc = con_documento
    fatture.registra_documento(fa, "ODA_RDC", "4500000002", D(2026, 3, 1))
    editor.post(
        reverse("contratti:fattura_documento_modifica", args=[fa.pk, doc.pk]),
        {"tipo": "ODA_RDC", "numero": "4500000003", "data": "12/03/2026"},
    )
    doc.refresh_from_db()
    assert doc.tipo == "MAP"


def test_rimozione_archivia_e_si_puo_registrare_di_nuovo(editor, con_documento):
    fa, doc = con_documento
    risposta = editor.post(reverse("contratti:fattura_documento_rimuovi", args=[fa.pk, doc.pk]))
    assert risposta.status_code == 302
    doc.refresh_from_db()
    assert doc.archiviato  # nessuna cancellazione fisica
    assert not fa.documenti.filter(archiviato=False).exists()
    nuovo = fatture.registra_documento(fa, "MAP", "100200999", D(2026, 3, 11))
    assert nuovo.pk != doc.pk


def test_dopo_il_trasferimento_non_si_modifica(editor, con_documento):
    fa, doc = con_documento
    fatture.trasferisci(fa, data=D(2026, 3, 20))
    editor.post(reverse("contratti:fattura_documento_rimuovi", args=[fa.pk, doc.pk]))
    doc.refresh_from_db()
    assert not doc.archiviato
    fatture.annulla_trasferimento(fa)
    editor.post(reverse("contratti:fattura_documento_rimuovi", args=[fa.pk, doc.pk]))
    doc.refresh_from_db()
    assert doc.archiviato


def test_documento_di_un_altra_fattura_404(editor, con_documento):
    fa, _ = con_documento
    altra = m.Fattura.objects.create(
        fornitore=fa.fornitore, numero="9/2026", data=D(2026, 4, 1), importo_documento=DEC("1")
    )
    _, doc = con_documento
    risposta = editor.post(reverse("contratti:fattura_documento_rimuovi", args=[altra.pk, doc.pk]))
    assert risposta.status_code == 404


# --- Fatturato pregresso ---------------------------------------------------------------------


@pytest.fixture
def contratto_con_voce():
    c = f.contratto(data_inizio=D(2024, 1, 1), durata_mesi=36)
    f.voce(c, importo_fisso=DEC("30000.00"))
    return c


def test_il_pregresso_conta_nel_fatturato_e_nel_residuo(contratto_con_voce):
    from contratti import acquisti

    c = contratto_con_voce
    m.FatturatoPregresso.objects.create(contratto=c, anno=2024, importo=DEC("10000.00"))
    m.FatturatoPregresso.objects.create(contratto=c, anno=2025, importo=DEC("9000.00"))
    m.FatturatoPregresso.objects.create(
        contratto=c, anno=2023, importo=DEC("500.00"), archiviato=True
    )
    e = acquisti.riepilogo_esecuzione(c, D(2026, 6, 1)).esecuzione
    assert e.fatturato == DEC("19000.00")
    assert e.residuo_fisso == DEC("11000.00")
    assert e.avanzamento_pct == 63


def test_pregresso_oltre_il_massimo_e_anomalia(contratto_con_voce):
    from contratti import acquisti

    m.FatturatoPregresso.objects.create(
        contratto=contratto_con_voce, anno=2024, importo=DEC("31000.00")
    )
    r = acquisti.riepilogo_esecuzione(contratto_con_voce, D(2026, 6, 1))
    assert "FATTURATO_OLTRE_MASSIMO" in r.anomalie


def test_vista_pregresso_registra_e_corregge(editor, contratto_con_voce):
    c = contratto_con_voce
    url = reverse("contratti:pregresso_salva", args=[c.pk])
    assert (
        editor.post(url, {"anno": 2024, "importo": "10.000,00", "note": "da Excel"}).status_code
        == 302
    )
    editor.post(url, {"anno": 2024, "importo": "11.000,00"})  # stesso anno: corregge
    (riga,) = c.fatturato_pregresso.filter(archiviato=False)
    assert riga.importo == DEC("11000.00") and riga.history.count() == 2
    editor.post(url, {"anno": 1999, "importo": "1,00"})  # anno non valido
    assert c.fatturato_pregresso.count() == 1
    editor.post(reverse("contratti:pregresso_rimuovi", args=[c.pk, riga.pk]))
    riga.refresh_from_db()
    assert riga.archiviato


def test_pregresso_ammesso_su_contratto_chiuso(editor, contratto_con_voce):
    c = contratto_con_voce
    c.data_chiusura = D(2026, 1, 31)
    c.save()
    editor.post(
        reverse("contratti:pregresso_salva", args=[c.pk]), {"anno": 2024, "importo": "5,00"}
    )
    assert c.fatturato_pregresso.count() == 1
    pagina = editor.get(reverse("contratti:contratto", args=[c.pk])).content.decode()
    assert "Fatturato pregresso" in pagina


# --- Permessi: il Reader riceve 403 sulle viste nuove -----------------------------------------


def test_reader_403_sulle_viste_nuove(reader, con_documento, contratto_con_voce):
    fa, doc = con_documento
    c = contratto_con_voce
    pre = m.FatturatoPregresso.objects.create(contratto=c, anno=2024, importo=DEC("1.00"))
    viste = [
        reverse("contratti:fattura_documento_modifica", args=[fa.pk, doc.pk]),
        reverse("contratti:fattura_documento_rimuovi", args=[fa.pk, doc.pk]),
        reverse("contratti:pregresso_salva", args=[c.pk]),
        reverse("contratti:pregresso_rimuovi", args=[c.pk, pre.pk]),
    ]
    for url in viste:
        assert reader.post(url).status_code == 403, url
    doc.refresh_from_db()
    assert not doc.archiviato
