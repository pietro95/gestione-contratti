"""F11.3: fatture da prendere in carico, presa in carico multipla, lavorazione, esecuzione del
contratto. Permessi: Reader 403, Editor solo nei propri cluster una volta abbinata."""

import datetime
import html
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounts.roles import EDITOR, READER
from contratti import fatture
from contratti import models as m
from contratti.engine.acquisti import PassoFattura

from .. import factories as f
from ..engine.test_tc18_fatture import PAC_ATTESO
from .conftest import PASSWORD

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = datetime.date.today()


@pytest.fixture
def scenario(make_user):
    it = f.cluster("IT")
    conto = f.conto(
        codice="600010", descrizione="Conto di prova", valido_dal=D(2020, 1, 1), cluster=it
    )
    wbs = m.WBS.objects.create(codice_wbs="WBS-TEST-01", descrizione="WBS di prova", cluster=it)
    s = f.fornitore("Studio Prova", nome_breve="STUDIOP")
    referente = make_user("rossi", role=EDITOR)
    cs = f.contratto(
        fornitore=s,
        fabbisogno=f.fabbisogno("Consulenza S", referente_utente=referente),
        data_inizio=OGGI.replace(month=1, day=1),
        numero_contratto="5800000077",
    )
    voce = f.voce(
        cs, natura=m.Natura.CAPEX, conto=conto, centro_costo="C0001", wbs=wbs,
        importo_fisso=Decimal("5000.00"),
    )  # fmt: skip
    fa = m.Fattura.objects.create(
        fornitore=s, numero="13/2026", data=OGGI, importo_documento=Decimal("1679.83")
    )
    return {"fattura": fa, "contratto": cs, "voce": voce, "referente": referente}


def _viste_di_modifica(fa, c):
    return [
        ("post", reverse("contratti:fatture_azione")),
        ("get", reverse("contratti:fattura_nuova")),
        ("post", reverse("contratti:fattura_nuova")),
        ("get", reverse("contratti:contratto_fattura_nuova", args=[c.pk])),
        ("post", reverse("contratti:fattura_prendi", args=[fa.pk])),
        ("post", reverse("contratti:fattura_lascia", args=[fa.pk])),
        ("post", reverse("contratti:fattura_riassegna", args=[fa.pk])),
        ("post", reverse("contratti:fattura_contratto", args=[fa.pk])),
        ("post", reverse("contratti:fattura_fornitore", args=[fa.pk])),
        ("post", reverse("contratti:fattura_convalida", args=[fa.pk])),
        ("post", reverse("contratti:fattura_importi", args=[fa.pk])),
        ("post", reverse("contratti:fattura_documento", args=[fa.pk])),
        ("post", reverse("contratti:fattura_trasferisci", args=[fa.pk])),
        ("post", reverse("contratti:fattura_fuori_registro", args=[fa.pk])),
        ("post", reverse("contratti:contratto_documento", args=[c.pk])),
        ("post", reverse("contratti:contratto_chiudi", args=[c.pk])),
        ("post", reverse("contratti:contratto_stanziamento", args=[c.pk])),
    ]


def test_reader_riceve_403_e_legge(reader, scenario):
    fa, c = scenario["fattura"], scenario["contratto"]
    for metodo, url in _viste_di_modifica(fa, c):
        assert getattr(reader, metodo)(url).status_code == 403, (metodo, url)
    pagina = reader.get(reverse("contratti:fatture")).content.decode()
    assert "13/2026" in pagina and 'name="fattura"' not in pagina
    assert reader.get(reverse("contratti:fattura", args=[fa.pk])).status_code == 200
    assert reader.get(reverse("contratti:contratto", args=[c.pk])).status_code == 200
    fa.refresh_from_db()
    assert fa.referente is None


def test_editor_di_un_altro_cluster(scenario, make_user):
    fa, c = scenario["fattura"], scenario["contratto"]
    make_user("verdi", role=EDITOR)
    m.AssegnazioneCluster.objects.create(username="verdi", cluster=f.cluster("TLC"))
    m.AssegnazioneCluster.objects.create(username="rossi", cluster=f.cluster("IT"))
    client = Client()
    client.login(username="verdi", password=PASSWORD)
    # Prende in carico anche se è di un altro cluster...
    client.post(reverse("contratti:fattura_prendi", args=[fa.pk]))
    fa.refresh_from_db()
    assert fa.referente.username == "verdi"
    # ...ma non la abbina a un contratto IT.
    risposta = client.post(
        reverse("contratti:fattura_contratto", args=[fa.pk]), {"contratto": c.pk}
    )
    assert risposta.status_code == 403
    for url in (
        reverse("contratti:contratto_documento", args=[c.pk]),
        reverse("contratti:contratto_chiudi", args=[c.pk]),
        reverse("contratti:contratto_fattura_nuova", args=[c.pk]),
    ):
        assert client.post(url).status_code == 403, url


def test_presa_in_carico_multipla_e_proposte(scenario, editor, make_user):
    s = scenario["fattura"].fornitore
    altra = m.Fattura.objects.create(
        fornitore=s, numero="14/2026", data=OGGI, importo_documento=Decimal("10")
    )
    # Il referente proposto è rossi (referente del fabbisogno): «proposte a me» è attivo per lui.
    rossi = Client()
    rossi.login(username="rossi", password=PASSWORD)
    pagina = rossi.get(reverse("contratti:fatture")).content.decode()
    assert "Solo le proposte a me (2)" in pagina and "13/2026" in pagina
    # Editor senza proposte vede tutto; prende in carico le due insieme.
    pagina = editor.get(reverse("contratti:fatture")).content.decode()
    assert "13/2026" in pagina and "14/2026" in pagina
    risposta = editor.post(
        reverse("contratti:fatture_azione"),
        {"azione": "prendi", "fattura": [scenario["fattura"].pk, altra.pk]},
        follow=True,
    )
    assert "2 fatture prese in carico" in html.unescape(risposta.content.decode())
    assert set(m.Fattura.objects.values_list("referente__username", flat=True)) == {"u_editor"}
    risposta = rossi.post(
        reverse("contratti:fatture_azione"), {"azione": "prendi", "fattura": [altra.pk]},
        follow=True,
    )  # fmt: skip
    assert "già in carico a u_editor" in html.unescape(risposta.content.decode())
    # Assegna ai proposti: solo Admin e addetto.
    assert (
        rossi.post(
            reverse("contratti:fatture_azione"),
            {"azione": "assegna_proposti", "fattura": [altra.pk]},
        ).status_code
        == 403
    )
    pagina = editor.get(reverse("contratti:fatture") + "?vista=mie").content.decode()
    assert "14/2026" in pagina


def test_lavorazione_completa(scenario):
    fa, c, rossi = scenario["fattura"], scenario["contratto"], scenario["referente"]
    m.AssegnazioneCluster.objects.create(username="rossi", cluster=f.cluster("IT"))
    client = Client()
    client.login(username="rossi", password=PASSWORD)
    url = reverse("contratti:fattura", args=[fa.pk])
    pagina = client.get(url).content.decode()
    assert "Contratto proposto" in pagina and "Prendi in carico" in pagina
    client.post(reverse("contratti:fattura_prendi", args=[fa.pk]))
    client.post(reverse("contratti:fattura_contratto", args=[fa.pk]), {"contratto": c.pk})
    fa = fatture.QS_FATTURE.get(pk=fa.pk)
    assert (fa.referente, fa.contratto, fa.voce) == (rossi, c, scenario["voce"])
    assert fatture.passo_fattura(fa) == PassoFattura.CONVALIDA
    # In attesa senza nota: rifiutato.
    client.post(
        reverse("contratti:fattura_convalida", args=[fa.pk]), {"esito_convalida": "in_attesa"}
    )
    fa.refresh_from_db()
    assert fa.esito_convalida == "da_valutare"
    client.post(
        reverse("contratti:fattura_convalida", args=[fa.pk]),
        {"esito_convalida": "convalidabile", "nota_convalida": ""},
    )
    client.post(
        reverse("contratti:fattura_importi", args=[fa.pk]),
        {
            "valore_base": "1.504,17",
            "oneri": "173,66",
            "bollo": "2,00",
            "voce": scenario["voce"].pk,
            "competenza_dal": "01/01/2026",
            "competenza_al": "31/12/2026",
        },
    )
    for tipo, numero in (("ODA_RDC", "RDC-0001"), ("MAP", "MAP-0001")):
        client.post(
            reverse("contratti:fattura_documento", args=[fa.pk]),
            {"tipo": tipo, "numero": numero, "data": OGGI.strftime("%d/%m/%Y")},
        )
    fa = fatture.QS_FATTURE.get(pk=fa.pk)
    assert fatture.passo_fattura(fa) == PassoFattura.RDC_RILASCIO
    m.DocumentoEsecuzione.objects.filter(fattura=fa).update(data_rilascio=OGGI)
    fa = fatture.QS_FATTURE.get(pk=fa.pk)
    assert fatture.passo_fattura(fa) == PassoFattura.TRASFERIMENTO
    pagina = html.unescape(client.get(url).content.decode())
    assert PAC_ATTESO.replace("5800000013", "5800000077") in pagina
    assert (
        "Contratto 5800000077. Valore base da prelevare € 1.504,17. COGE: 600010, CDC: C0001"
        in pagina
    )
    client.post(
        reverse("contratti:fattura_trasferisci", args=[fa.pk]),
        {"data": OGGI.strftime("%d/%m/%Y")},
    )
    fa.refresh_from_db()
    assert fa.data_trasferimento == OGGI and fa.trasferita_da == rossi
    # Esecuzione del contratto: fatturato sul valore base; chiusura dalla scheda.
    pagina = html.unescape(client.get(reverse("contratti:contratto", args=[c.pk])).content.decode())
    assert "1.504,17 €" in pagina and "13/2026" in pagina
    client.post(reverse("contratti:contratto_chiudi", args=[c.pk]))
    c.refresh_from_db()
    assert c.data_chiusura == OGGI
    client.post(reverse("contratti:contratto_chiudi", args=[c.pk]), {"annulla": "1"})
    c.refresh_from_db()
    assert c.data_chiusura is None


def test_registrazione_a_mano_e_ricerca(scenario, editor):
    c = scenario["contratto"]
    risposta = editor.post(
        reverse("contratti:contratto_fattura_nuova", args=[c.pk]),
        {"numero": "15/2026", "data": OGGI.strftime("%d/%m/%Y"), "importo_documento": "100"},
    )
    nuova = m.Fattura.objects.get(numero="15/2026")
    assert risposta.status_code == 302 and nuova.contratto == c and nuova.referente is None
    # Lo stesso numero dello stesso fornitore non si registra due volte.
    risposta = editor.post(
        reverse("contratti:contratto_fattura_nuova", args=[c.pk]),
        {"numero": "15/2026", "data": OGGI.strftime("%d/%m/%Y"), "importo_documento": "100"},
    )
    assert risposta.status_code == 200 and m.Fattura.objects.filter(numero="15/2026").count() == 1
    m.DocumentoEsecuzione.objects.create(
        contratto=c, tipo="ODA_RDC", numero="RDC-0042", data=OGGI, fattura=nuova
    )
    pagina = editor.get(reverse("contratti:cerca") + "?q=RDC-0042").content.decode()
    assert "Fattura 15/2026" in pagina


def test_documento_di_esecuzione_e_fuori_registro(scenario, editor):
    fa, c = scenario["fattura"], scenario["contratto"]
    editor.post(
        reverse("contratti:contratto_documento", args=[c.pk]),
        {"tipo": "ATTESTAZIONE", "data": OGGI.strftime("%d/%m/%Y"), "finale": "on"},
    )
    assert c.documenti_esecuzione.get().finale
    editor.post(
        reverse("contratti:contratto_documento", args=[c.pk]),
        {"tipo": "DDT", "data": OGGI.strftime("%d/%m/%Y"), "finale": "on"},
    )
    assert c.documenti_esecuzione.count() == 1  # «finale» solo per attestazione e ricezione
    editor.post(
        reverse("contratti:fatture_azione"), {"azione": "fuori_registro", "fattura": [fa.pk]}
    )
    fa.refresh_from_db()
    assert fa.fuori_registro
    pagina = editor.get(reverse("contratti:fatture")).content.decode()
    assert "13/2026" not in pagina
    editor.post(reverse("contratti:fattura_fuori_registro", args=[fa.pk]), {"valore": "0"})
    fa.refresh_from_db()
    assert not fa.fuori_registro


def test_tipo_acquisto_nel_form_del_contratto(scenario, editor):
    c = scenario["contratto"]
    pagina = editor.get(reverse("contratti:contratto_modifica", args=[c.pk])).content.decode()
    assert 'name="tipo_acquisto"' in pagina


# --- Vista di default, import dell'amministrazione acquisti, fatture bloccate ----------------


def _client(username):
    client = Client()
    client.login(username=username, password=PASSWORD)
    return client


def test_vista_di_default_senza_fatture_da_prendere(scenario, editor):
    fa = scenario["fattura"]
    # C'è una fattura da prendere in carico: si apre «Da prendere in carico».
    risposta = editor.get(reverse("contratti:fatture"))
    assert risposta.context["vista"] == "da_prendere"
    # Presa in carico: la vista è vuota e di default si apre «Le mie fatture».
    editor.post(reverse("contratti:fattura_prendi", args=[fa.pk]))
    risposta = editor.get(reverse("contratti:fatture"))
    assert risposta.context["vista"] == "mie"
    assert [r["f"] for r in risposta.context["pagina"]] == [fa]
    # Una fattura da prendere in carico non proposta a me (altro fornitore, nessun contratto)
    # si vede comunque: la vista di default resta «Da prendere in carico».
    altro = f.fornitore("Altro Fornitore")
    m.Fattura.objects.create(
        fornitore=altro, numero="X-1", data=OGGI, importo_documento=Decimal("10")
    )
    risposta = editor.get(reverse("contratti:fatture"))
    assert risposta.context["vista"] == "da_prendere" and risposta.context["totale"] == 1
    # La scelta esplicita della vista non si tocca.
    risposta = editor.get(reverse("contratti:fatture") + "?vista=da_prendere")
    assert risposta.context["vista"] == "da_prendere" and risposta.context["totale"] == 1


def test_import_nella_pagina_fatture_solo_per_l_amministrazione(
    scenario, editor, reader, make_user
):
    make_user("gialli", role=EDITOR)
    m.FunzioneUtente.objects.create(
        username="gialli", funzione=m.FunzioneUtente.Funzione.AMMINISTRAZIONE_ACQUISTI
    )
    url = reverse("contratti:fatture")
    addetto = _client("gialli")
    pagina = addetto.get(url).content.decode()
    assert 'id="import-fatture"' in pagina
    assert reverse("contratti:importazione_carica", args=["fatture"]) in pagina
    for altro in (editor, reader):
        assert 'id="import-fatture"' not in altro.get(url).content.decode()


def test_fattura_bloccata_non_e_da_convalidare(scenario, editor):
    fa = scenario["fattura"]
    fa.referente = scenario["referente"]
    fa.data_presa_in_carico = OGGI - datetime.timedelta(days=30)
    fa.data_registrazione = OGGI - datetime.timedelta(days=30)
    fa.contratto = scenario["contratto"]
    fa.voce = scenario["voce"]
    fa.esito_convalida = m.Fattura.Esito.CONVALIDABILE
    fa.data_convalida = OGGI - datetime.timedelta(days=20)
    fa.bloccata_fino_al = OGGI + datetime.timedelta(days=10)
    fa.save()
    assert fatture.passo_fattura(fa, OGGI) == PassoFattura.BLOCCATA
    assert not fatture.ferma(fa, OGGI)  # aspetta la data del blocco: non è ferma
    risposta = _client("rossi").get(reverse("contratti:fatture") + "?vista=mie")
    assert [r["passo_label"] for r in risposta.context["pagina"]] == ["Bloccata"]
    assert 'class="stato stato-grigio">Bloccata' in risposta.content.decode()
    dettaglio = editor.get(reverse("contratti:fattura", args=[fa.pk])).content.decode()
    assert "Bloccata" in dettaglio
    # Passata la data del blocco, la fattura prosegue.
    fa.bloccata_fino_al = OGGI - datetime.timedelta(days=1)
    fa.save()
    assert fatture.passo_fattura(fa, OGGI) == PassoFattura.RDC


def test_competenza_obbligatoria_con_il_valore_base(editor, scenario):
    fa = scenario["fattura"]
    editor.post(reverse("contratti:fattura_prendi", args=[fa.pk]))
    url = reverse("contratti:fattura_importi", args=[fa.pk])
    base = {"valore_base": "1.000,00", "oneri": "", "bollo": "", "iva": ""}
    editor.post(url, base)
    fa.refresh_from_db()
    assert fa.valore_base is None  # senza competenza non si salva
    editor.post(url, {**base, "competenza_dal": "01/06/2026", "competenza_al": "01/05/2026"})
    fa.refresh_from_db()
    assert fa.valore_base is None  # fine prima dell'inizio
    editor.post(url, {**base, "competenza_dal": "01/06/2026", "competenza_al": "31/05/2027"})
    fa.refresh_from_db()
    assert (fa.valore_base, fa.competenza_dal, fa.competenza_al) == (
        Decimal("1000.00"), D(2026, 6, 1), D(2027, 5, 31),
    )  # fmt: skip
    assert "COMPETENZA_MANCANTE" not in fatture.anomalie(fa)


def test_stanziamento_dal_contratto(editor, scenario, make_user):
    c, voce = scenario["contratto"], scenario["voce"]
    make_user("lettore", role=READER)
    reader = Client()
    reader.login(username="lettore", password=PASSWORD)
    dati = {
        "voce": voce.pk, "importo": "1.500,00",
        "competenza_dal": "01/09/2026", "competenza_al": "30/09/2026", "note": "non fatturato",
    }  # fmt: skip
    assert (
        reader.post(reverse("contratti:contratto_stanziamento", args=[c.pk]), dati).status_code
        == 403
    )
    editor.post(reverse("contratti:contratto_stanziamento", args=[c.pk]), dati)
    s = m.Stanziamento.objects.get()
    assert (s.importo, s.competenza_dal, s.competenza_al) == (
        Decimal("1500.00"), D(2026, 9, 1), D(2026, 9, 30),
    )  # fmt: skip
    pagina = editor.get(reverse("contratti:contratto", args=[c.pk])).content.decode()
    assert "Stanziamenti" in pagina and "1.500,00" in pagina
    # La fine prima dell'inizio non si registra.
    editor.post(
        reverse("contratti:contratto_stanziamento", args=[c.pk]),
        {**dati, "competenza_dal": "30/09/2026", "competenza_al": "01/09/2026"},
    )
    assert m.Stanziamento.objects.count() == 1
    # Il Reader non chiude né annulla; l'Editor chiude con la fattura arrivata.
    azione = reverse("contratti:stanziamento_azione", args=[s.pk])
    assert reader.post(azione, {"annulla": "1"}).status_code == 403
    editor.post(azione, {"fattura": scenario["fattura"].pk})
    s.refresh_from_db()
    assert s.fattura_id is None  # la fattura non è ancora del contratto
    scenario["fattura"].contratto = c
    scenario["fattura"].save()
    editor.post(azione, {"fattura": scenario["fattura"].pk})
    s.refresh_from_db()
    assert s.fattura_id == scenario["fattura"].pk and s.chiuso
    editor.post(azione, {"annulla": "1"})
    s.refresh_from_db()
    assert s.archiviato


def test_cambio_fornitore_della_fattura(scenario, come, make_user):
    """Il fornitore creato dall'import con il nome di SAP si corregge con quello in anagrafica."""
    fa = scenario["fattura"]
    giusto = f.fornitore("Telecom Italia S.p.A.")
    doppio = f.fornitore("TIM S.p.A.")
    fa.fornitore = doppio
    fa.save()
    url = reverse("contratti:fattura_fornitore", args=[fa.pk])
    admin = come("Admin")
    assert admin.get(reverse("contratti:fattura", args=[fa.pk])).status_code == 200
    assert admin.post(url, {"fornitore": giusto.pk}).status_code == 302
    fa.refresh_from_db()
    assert fa.fornitore == giusto
    assert fa.history.first().history_change_reason.startswith("Fornitore: TIM S.p.A.")
    # Doppione: lo stesso numero è già registrato per il fornitore di destinazione.
    altra = m.Fattura.objects.create(
        fornitore=doppio, numero=fa.numero, data=OGGI, importo_documento=Decimal("1.00")
    )
    admin.post(reverse("contratti:fattura_fornitore", args=[altra.pk]), {"fornitore": giusto.pk})
    altra.refresh_from_db()
    assert altra.fornitore == doppio


def test_cambio_fornitore_non_ammesso_con_il_contratto(scenario):
    fa, c = scenario["fattura"], scenario["contratto"]
    fatture.assegna_contratto(fa, c)
    with pytest.raises(fatture.OperazioneNonAmmessa):
        fatture.cambia_fornitore(fa, f.fornitore("Altro Fornitore"))
