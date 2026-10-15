"""Imputazione propria della fattura (conto, centro di costo, WBS) al posto di quella della
voce, e tendina della voce limitata al contratto scelto. Dati di fantasia."""

import datetime
import json
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.roles import EDITOR, READER
from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import fatture
from contratti import forms_fatture as ff
from contratti import models as m
from tests.connettore.conftest import chiama

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def dati():
    it = f.cluster("IT")
    conti = {c: m.ContoCoge.objects.create(codice=c, descrizione=c, valido_dal=D(2020, 1, 1),
                                           cluster=it) for c in ("600010", "600020")}  # fmt: skip
    wbs = m.WBS.objects.create(codice_wbs="WBS-TEST-02", descrizione="WBS di prova", cluster=it)
    fornitore = f.fornitore("Negozio Prova S.r.l.")
    a = f.contratto(fornitore=fornitore, numero_contratto="5800000081")
    b = f.contratto(fornitore=fornitore, numero_contratto="5800000082")
    voce = f.voce(a, conto=conti["600010"], centro_costo="C0001")
    f.voce(a, descrizione="Seconda voce")
    f.voce(b, descrizione="Voce di B")
    fattura = m.Fattura.objects.create(
        fornitore=fornitore, contratto=a, voce=voce, numero="AMZ-1", data=D(2026, 9, 1),
        importo_documento=Decimal("100.00"), valore_base=Decimal("100.00"),
    )  # fmt: skip
    return {"a": a, "b": b, "voce": voce, "fattura": fattura, "conti": conti, "wbs": wbs}


def test_voci_del_contratto_scelto(dati):
    a, b = dati["a"], dati["b"]
    form = ff.ContrattoFatturaForm(fattura=dati["fattura"], initial={"contratto": a.pk})
    assert {v.contratto_id for v in form.fields["voce"].queryset} == {a.pk}
    mappa = json.loads(form.fields["contratto"].widget.attrs["data-voci"])
    assert len(mappa[str(a.pk)]) == 2 and len(mappa[str(b.pk)]) == 1
    # Inviato: la voce di un altro contratto è un errore.
    voce_b = b.voci.get()
    form = ff.ContrattoFatturaForm({"contratto": a.pk, "voce": voce_b.pk}, fattura=dati["fattura"])
    assert not form.is_valid() and "voce" in form.errors
    form = ff.ContrattoFatturaForm({"contratto": b.pk, "voce": voce_b.pk}, fattura=dati["fattura"])
    assert form.is_valid()


def test_imputazione_propria_nelle_indicazioni_e_nel_pac(dati):
    x = dati["fattura"]
    assert "COGE: 600010, CDC: C0001, WBS: --" in fatture.indicazioni_validazione(x)
    fatture.imputa(x, dati["conti"]["600020"], "", dati["wbs"])
    x = fatture.QS_FATTURE.get(pk=x.pk)
    # Campo per campo: il centro di costo vuoto resta quello della voce.
    assert "COGE: 600020, CDC: C0001, WBS: WBS-TEST-02" in fatture.indicazioni_validazione(x)
    assert "WBS-TEST-02" in fatture.commento_pac(x)
    fatture.imputa(x, None, "", None)
    x = fatture.QS_FATTURE.get(pk=x.pk)
    assert "COGE: 600010, CDC: C0001, WBS: --" in fatture.indicazioni_validazione(x)
    assert x.history.first().history_change_reason == "Imputazione della fattura"


def test_dalla_pagina_e_reader(client, make_user, dati):
    x = dati["fattura"]
    url = reverse("contratti:fattura_importi", args=[x.pk])
    dati_post = {"valore_base": "100,00", "oneri": "", "bollo": "", "iva": "",
                 "voce": dati["voce"].pk, "rata": "", "conto": dati["conti"]["600020"].pk,
                 "centro_costo": "C0009", "wbs": "",
                 "competenza_dal": "01/01/2026", "competenza_al": "31/12/2026"}  # fmt: skip
    client.force_login(make_user("lettore", role=READER))
    assert client.post(url, dati_post).status_code == 403
    client.force_login(make_user("redattore", role=EDITOR))
    client.post(url, dati_post)
    x.refresh_from_db()
    assert (x.conto.codice, x.centro_costo, x.wbs) == ("600020", "C0009", None)
    pagina = client.get(reverse("contratti:fattura", args=[x.pk])).content.decode()
    assert "Imputazione della fattura, se diversa dalla voce" in pagina


def test_dal_connettore(make_user, dati):
    editor = make_user("redattore", role=EDITOR)
    ctx = Contesto(editor, D(2026, 10, 12), scrittura=True, client_id="prova")
    x = dati["fattura"]
    risposta, _ = protocollo.gestisci(
        chiama("importi_fattura", {"id": x.pk, "conto_id": dati["conti"]["600020"].pk,
                                   "centro_costo": "C0009",
                                   "competenza_dal": "2026-01-01",
                                   "competenza_al": "2026-12-31"}), ctx,
    )  # fmt: skip
    anteprima = risposta["result"]["structuredContent"]
    assert (
        "CDC: C0009"
        in anteprima["effetti"]["processo_acquisto"]["dopo"]["fatture"][0]["commento_pac"]
    )
    protocollo.gestisci(chiama("conferma_operazione",
                               {"id_operazione": anteprima["id_operazione"]}), ctx)  # fmt: skip
    risposta, _ = protocollo.gestisci(chiama("fattura", {"id": x.pk}), ctx)
    assert risposta["result"]["structuredContent"]["imputazione_della_fattura"] == {
        "conto": "600020", "centro_costo": "C0009", "wbs": None,
    }  # fmt: skip
