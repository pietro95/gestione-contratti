"""Flussi operativi end-to-end dall'interfaccia (ROADMAP F4)."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from contratti import adapters
from contratti import models as m
from contratti.selettori import cruscotto

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


def campi_contratto(**kw):
    base = {
        "fornitore": "",
        "descrizione": "",
        "numero_contratto": "",
        "data_emissione": "",
        "numero_rda": "",
        "cig": "",
        "procedura": "",
        "lead_time_mesi_override": "",
        "data_stipula": "",
        "data_inizio": "",
        "durata_mesi": "12",
        "data_fine_override": "",
        "preavviso_disdetta_giorni": "",
        "link_documenti": "",
        "note": "",
    }
    base.update(kw)
    return base


def test_registro_rinnovo_il_previsto_sparisce(editor, dati):
    """Accettazione F4: registro il rinnovo → il previsto del periodo sparisce."""
    fab, vecchio = dati["fabbisogno"], dati["contratto"]
    orizzonte = D(2028, 12, 31)
    prima = adapters.previsti_fabbisogno(fab, orizzonte)
    assert [p.inizio for p in prima] == [D(2027, 1, 1), D(2028, 1, 1)]
    assert vecchio in [r.contratto for r in cruscotto(D(2027, 1, 15), {})[adapters.Alert.ROSSO]]

    # Il form propone il rinnovo precompilato.
    pagina = editor.get(reverse("contratti:contratto_rinnovo", args=[vecchio.pk]))
    assert pagina.status_code == 200
    assert pagina.context["form"].initial["data_inizio"] == D(2027, 1, 1)

    risposta = editor.post(
        reverse("contratti:contratto_rinnovo", args=[vecchio.pk]),
        {
            **campi_contratto(
                fornitore=vecchio.fornitore_id,
                procedura=vecchio.procedura_id,
                data_inizio="2027-01-01",
                numero_contratto="5800000099",
                cig="Z000000099",
            ),
            "voci-TOTAL_FORMS": "1",
            "voci-INITIAL_FORMS": "1",
            "voci-0-origine": dati["voce"].pk,
            "voci-0-riporta": "on",
            "voci-0-descrizione": "Canone 2027",
            "voci-0-importo_fisso": "11.000,00",
            "voci-0-massimale_variabile": "0",
        },
    )
    nuovo = m.Contratto.objects.get(numero_contratto="5800000099")
    assert risposta.status_code == 302 and risposta.url == reverse(
        "contratti:contratto", args=[nuovo.pk]
    )
    assert nuovo.predecessore == vecchio and nuovo.fabbisogno == fab
    voce = nuovo.voci.get()
    assert voce.importo_fisso == Decimal("11000.00")
    assert voce.piano_fatturazione.modalita == "anticipata"  # piano copiato
    assert vecchio.stati_pratica.first().stato == "contratto_attivo"

    dopo = adapters.previsti_fabbisogno(fab, orizzonte)
    assert [p.inizio for p in dopo] == [D(2028, 1, 1)]  # il previsto 2027 è sparito
    assert dopo[0].voci[0].importo_fisso == Decimal("11000.00")  # riparte dal reale
    rossi = cruscotto(D(2027, 1, 15), {})[adapters.Alert.ROSSO]
    assert vecchio not in [r.contratto for r in rossi]  # niente più alert sul vecchio


def test_secondo_rinnovo_rifiutato(editor, dati):
    f.contratto(
        fabbisogno=dati["fabbisogno"], predecessore=dati["contratto"], data_inizio=D(2027, 1, 1)
    )
    risposta = editor.get(reverse("contratti:contratto_rinnovo", args=[dati["contratto"].pk]))
    assert risposta.status_code == 302


def test_nuovo_contratto_e_voce_con_anteprima(editor, dati):
    risposta = editor.post(
        reverse("contratti:contratto_nuovo"),
        {
            **campi_contratto(
                fornitore=dati["fornitore"].pk,
                procedura=m.Procedura.objects.get(codice="rdo").pk,
                data_inizio="2026-07-01",
                durata_mesi="24",
            ),
            "fabbisogno": dati["fabbisogno"].pk,
        },
    )
    assert risposta.status_code == 302
    c = m.Contratto.objects.order_by("-pk").first()
    dati_voce = {
        "voce-descrizione": "Canone trimestrale",
        "voce-proroga": "",
        "voce-conto": "",
        "voce-centro_costo": "",
        "voce-natura": "OPEX",
        "voce-wbs": "",
        "voce-importo_fisso": "24.000,00",
        "voce-massimale_variabile": "0",
        "voce-stima_consumo_pct": "",
        "voce-stima_consumo_importo": "",
        "piano-modalita": "posticipata",
        "piano-periodicita": "trimestrale",
        "piano-data_prima_fattura": "",
        "piano-giorni_pagamento": "60",
        "piano-pagamento_fine_mese": "true",
        "piano-note": "",
        "quote-TOTAL_FORMS": "1",
        "quote-INITIAL_FORMS": "0",
        "quote-0-dal": "",
        "quote-0-al": "",
        "quote-0-importo": "",
    }
    # Anteprima (TC-03): 8 rate da 3.000,00, prima il 30/09/2026, nessun salvataggio.
    anteprima = editor.post(reverse("contratti:voce_anteprima", args=[c.pk]), dati_voce)
    html = anteprima.content.decode()
    assert "8 rate" in html and "30/09/2026" in html and "3.000,00 €" in html
    assert not c.voci.exists()

    assert editor.post(reverse("contratti:voce_nuova", args=[c.pk]), dati_voce).status_code == 302
    voce = c.voci.get()
    assert voce.piano_fatturazione.pagamento_fine_mese is True
    editor.post(reverse("contratti:scadenzario_genera", args=[voce.pk]))
    rate = list(voce.piano_fatturazione.rate.order_by("numero"))
    assert len(rate) == 8 and rate[0].data_pagamento_stimata == D(2026, 11, 30)


def test_modifica_rata_marcata_e_blocca_la_rigenerazione(editor, dati):
    rata = dati["rata"]
    risposta = editor.post(
        reverse("contratti:rata_modifica", args=[rata.pk]),
        {
            "data_fattura": "2026-02-01",
            "data_pagamento_stimata": "2026-04-30",
            "importo": "10.500,00",
            "numero_fattura": "F-1",
        },
    )
    assert risposta.status_code == 302
    rata.refresh_from_db()
    assert rata.modificata_manualmente and rata.importo == Decimal("10500.00")
    risposta = editor.post(
        reverse("contratti:scadenzario_genera", args=[dati["voce"].pk]), follow=True
    )
    assert "rigenerazione non eseguita" in risposta.content.decode()


def test_proroga_con_importo(editor, dati):
    c = dati["contratto"]
    risposta = editor.post(
        reverse("contratti:proroga_nuova", args=[c.pk]),
        {
            "data_atto": "2026-11-15",
            "nuova_data_fine": "2027-06-30",
            "riferimento": "Prot. 1",
            "note": "",
            "importo_fisso": "5.000,00",
            "descrizione_voce": "",
            "modalita": "una_tantum",
            "periodicita": "",
        },
    )
    assert risposta.status_code == 302
    assert adapters.data_fine_effettiva(c) == D(2027, 6, 30)
    voce = c.voci.get(proroga__isnull=False)
    assert voce.importo_fisso == Decimal("5000.00")


def test_proroga_prima_della_fine_rifiutata(editor, dati):
    risposta = editor.post(
        reverse("contratti:proroga_nuova", args=[dati["contratto"].pk]),
        {"data_atto": "2026-11-15", "nuova_data_fine": "2026-12-31", "modalita": "una_tantum"},
    )
    assert risposta.status_code == 200
    assert "successiva al 31/12/2026" in risposta.content.decode()
    assert not m.Proroga.objects.exists()


def test_avanzamento_pratica(editor, dati):
    c = dati["contratto"]
    editor.post(
        reverse("contratti:pratica_avanza", args=["contratto", c.pk]),
        {"stato": "rda_richiesta", "data": "2026-09-01", "note": "chiesta a SAP"},
    )
    passaggio = c.stati_pratica.get()
    assert (passaggio.stato, passaggio.data, passaggio.utente.username) == (
        "rda_richiesta",
        D(2026, 9, 1),
        "u_editor",
    )
    assert adapters.alert_contratto(c, D(2026, 10, 1)) == adapters.Alert.GIALLO  # pratica avanzata


def test_archiviazione_e_ripristino(editor, dati):
    c = dati["contratto"]
    editor.post(reverse("contratti:archivia", args=["contratto", c.pk]))
    c.refresh_from_db()
    assert c.archiviato and m.Contratto.objects.filter(pk=c.pk).exists()
    assert "5800000001" not in editor.get(reverse("contratti:contratti")).content.decode()
    editor.post(reverse("contratti:archivia", args=["contratto", c.pk]), {"ripristina": "1"})
    c.refresh_from_db()
    assert not c.archiviato


def test_proposte_da_interfaccia(editor, dati):
    rag = dati["raggruppamento"]
    editor.post(reverse("contratti:proposta_azione", args=["raggruppamento", rag.pk, "conferma"]))
    rag.refresh_from_db()
    assert rag.stato == "confermata"
    pred = dati["predecessore"]
    risposta = editor.post(
        reverse("contratti:proposta_azione", args=["predecessore", pred.pk, "conferma"]),
        follow=True,
    )
    pred.refresh_from_db()
    assert pred.stato == "confermata"
    assert "Proposta confermata" in risposta.content.decode()


def test_fabbisogno_e_fornitore_da_interfaccia(editor, dati):
    risposta = editor.post(
        reverse("contratti:fornitore_nuovo"),
        {
            "ragione_sociale": "Nuovo Fornitore S.r.l.",
            "partita_iva": "",
            "codice_sap": "",
            "note": "",
        },
    )
    assert risposta.status_code == 302
    assert m.Fornitore.objects.filter(ragione_sociale="Nuovo Fornitore S.r.l.").exists()
    risposta = editor.post(
        reverse("contratti:fabbisogno_nuovo"),
        {
            "descrizione": "Firewall perimetrale",
            "cluster": m.Cluster.objects.get(codice="IT").pk,
            "categoria": m.Categoria.objects.get(nome="Licenze software").pk,
            "decisione": "da_valutare",
            "previsto_data_avvio": "2027-01-01",
            "previsto_durata_mesi": "",
        },
    )
    assert risposta.status_code == 200  # avvio senza durata: errore
    assert "insieme avvio e durata" in risposta.content.decode()


def test_storico_mostra_le_modifiche(editor, dati):
    c = dati["contratto"]
    editor.post(
        reverse("contratti:contratto_modifica", args=[c.pk]),
        {
            **campi_contratto(
                fornitore=c.fornitore_id,
                procedura=c.procedura_id,
                data_inizio="2026-01-01",
                numero_contratto="5800000077",
            ),
            "fabbisogno": c.fabbisogno_id,
        },
    )
    html = editor.get(reverse("contratti:contratto", args=[c.pk])).content.decode()
    assert "5800000001 → 5800000077" in html and "u_editor" in html
