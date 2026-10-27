"""Form della voce, quote per periodo: un solo POST con tutte le righe (SPEC §4, Rev29).

Il flusso nel browser (aggiungi righe senza salvare) è in ``tests/e2e/test_quote_voce.py``; qui
la parte del server: più righe in un invio, errori per riga con i dati conservati, regole delle
quote per modalità, eliminazione, 403 per il Reader.
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from contratti import models as m

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
FISSO = Decimal("2947639.75")


def _voce_sal():
    c = f.contratto(
        data_inizio=D(2024, 10, 15),
        durata_mesi=29,
        data_fine_override=D(2027, 3, 31),
        numero_contratto="5800000230",
    )
    voce = f.voce(c, descrizione="Lavori", importo_fisso=FISSO)
    f.piano(voce, modalita="sal", periodicita="")
    return voce


def _post(voce, quote, *, iniziali=0, modalita="sal", periodicita="", fisso="2.947.639,75", **kw):
    """Dati del form della voce con le quote date: (dal, al, importo) o con ``id`` e ``DELETE``."""
    dati = {
        "voce-descrizione": "Lavori",
        "voce-natura": "OPEX",
        "voce-importo_fisso": fisso,
        "voce-massimale_variabile": "0,00",
        "piano-modalita": modalita,
        "piano-periodicita": periodicita,
        "piano-giorni_pagamento": "30",
        "piano-pagamento_fine_mese": "true",
        "quote-TOTAL_FORMS": str(len(quote)),
        "quote-INITIAL_FORMS": str(iniziali),
        "quote-MIN_NUM_FORMS": "0",
        "quote-MAX_NUM_FORMS": "1000",
    }
    for i, q in enumerate(quote):
        dal, al, importo = q[:3]
        dati |= {f"quote-{i}-dal": dal, f"quote-{i}-al": al, f"quote-{i}-importo": importo}
        if len(q) > 3:
            dati |= q[3]
    return dati | kw


def _url(voce):
    return reverse("contratti:voce_modifica", args=[voce.contratto_id, voce.pk])


QUATTRO = [
    ("01/01/2024", "31/12/2024", "0,00"),
    ("01/01/2025", "31/12/2025", "1.486.870,87"),
    ("01/01/2026", "31/12/2026", "1.144.060,62"),
    ("01/01/2027", "31/12/2027", "316.708,26"),
]


def test_quattro_quote_in_un_solo_invio(editor):
    voce = _voce_sal()
    risposta = editor.post(_url(voce), _post(voce, QUATTRO))
    assert risposta.status_code == 302
    assert [(q.dal.year, q.importo) for q in voce.quote.order_by("dal")] == [
        (2024, Decimal("0.00")),
        (2025, Decimal("1486870.87")),
        (2026, Decimal("1144060.62")),
        (2027, Decimal("316708.26")),
    ]


def test_tre_righe_piu_una_vuota_in_fondo(editor):
    voce = _voce_sal()
    quote = [*QUATTRO[1:], ("", "", "")]  # la riga vuota in più non conta
    assert editor.post(_url(voce), _post(voce, quote)).status_code == 302
    assert voce.quote.count() == 3


def test_errore_sulla_riga_giusta_e_dati_conservati(editor):
    voce = _voce_sal()
    quote = [QUATTRO[1], ("01/06/2025", "31/12/2026", "1.000,00"), QUATTRO[3]]
    risposta = editor.post(_url(voce), _post(voce, quote))
    assert risposta.status_code == 200
    assert voce.quote.count() == 0
    errori = risposta.context["quote"].errors
    assert errori[0] == {} and errori[2] == {}
    assert "ovrappone" in errori[1]["dal"][0]
    html = risposta.content.decode()
    # Le tre righe sono ancora lì, con quanto era stato digitato.
    for valore in ("1.486.870,87", "01/06/2025", "31/12/2026", "316.708,26"):
        assert valore in html
    assert html.count("data-riga-form") == 3 + 1  # le righe più il modello della riga vuota


def test_sal_somma_oltre_il_fisso_non_si_salva(editor):
    voce = _voce_sal()
    risposta = editor.post(_url(voce), _post(voce, [("01/01/2025", "31/12/2025", "3.000.000,00")]))
    assert risposta.status_code == 200
    assert "supera l&#x27;importo fisso" in risposta.content.decode() or (
        "supera l'importo fisso" in risposta.content.decode()
    )
    assert voce.quote.count() == 0


def test_la_regola_usa_il_fisso_e_la_modalita_del_form_non_quelli_salvati(editor):
    voce = _voce_sal()  # salvata con 2.947.639,75
    quote = [("01/01/2025", "31/12/2025", "5.000,00")]
    assert editor.post(_url(voce), _post(voce, quote, fisso="1.000,00")).status_code == 200
    assert voce.quote.count() == 0
    assert editor.post(_url(voce), _post(voce, quote, fisso="5.000,00")).status_code == 302


def test_sal_quota_a_cavallo_si_salva_con_avviso(editor):
    voce = _voce_sal()
    risposta = editor.post(
        _url(voce), _post(voce, [("01/07/2025", "30/06/2026", "1.000,00")]), follow=True
    )
    testi = " ".join(str(x) for x in risposta.context["messages"])
    assert voce.quote.count() == 1
    assert "attraversano due anni" in testi and "SAL non pianificato" in testi


def test_non_sal_con_quote_incoerenti_si_salva_con_avviso_non_bloccante(editor):
    c = f.contratto(data_inizio=D(2026, 1, 1), durata_mesi=24)
    voce = f.voce(c, importo_fisso=Decimal("2400.00"))
    f.piano(voce, modalita="posticipata", periodicita="annuale")
    quote = [("01/07/2026", "31/12/2026", "1.000,00")]  # non copre il servizio
    risposta = editor.post(
        _url(voce),
        _post(voce, quote, modalita="posticipata", periodicita="annuale", fisso="2.400,00"),
        follow=True,
    )
    assert voce.quote.count() == 1  # non blocca
    assert "non coerenti" in " ".join(str(x) for x in risposta.context["messages"])


def test_quote_salvate_si_modificano_e_si_eliminano_con_traccia(editor):
    voce = _voce_sal()
    for dal, al, importo in [(D(2025, 1, 1), D(2025, 12, 31), "100.00"),
                             (D(2026, 1, 1), D(2026, 12, 31), "200.00")]:  # fmt: skip
        m.QuotaPeriodo.objects.create(voce=voce, dal=dal, al=al, importo=Decimal(importo))
    prima, seconda = voce.quote.order_by("dal")
    dati = _post(
        voce,
        [
            ("01/01/2025", "31/12/2025", "150,00",
             {"quote-0-id": prima.pk, "quote-0-voce": voce.pk}),
            ("01/01/2026", "31/12/2026", "200,00",
             {"quote-1-id": seconda.pk, "quote-1-voce": voce.pk, "quote-1-DELETE": "on"}),
            ("01/01/2027", "31/12/2027", "300,00"),
        ],
        iniziali=2,
    )  # fmt: skip
    assert editor.post(_url(voce), dati).status_code == 302
    assert [(q.dal.year, q.importo) for q in voce.quote.order_by("dal")] == [
        (2025, Decimal("150.00")),
        (2027, Decimal("300.00")),
    ]
    tolta = m.QuotaPeriodo.history.get(history_type="-")
    assert (tolta.dal.year, tolta.importo) == (2026, Decimal("200.00"))
    assert "eliminata" in tolta.history_change_reason and tolta.history_user is not None
    assert (
        "modificata"
        in m.QuotaPeriodo.history.filter(history_type="~", id=prima.pk)
        .first()
        .history_change_reason
    )


def test_riga_vuota_e_modello_presenti_nella_pagina(editor):
    voce = _voce_sal()
    html = editor.get(_url(voce)).content.decode()
    assert 'id="quote-vuota"' in html and 'data-aggiungi-form="quote"' in html
    assert "quote-__prefix__-dal" in html  # il modello della riga
    assert 'name="quote-0-dal"' in html


def test_reader_non_puo_salvare_le_quote(reader):
    voce = _voce_sal()
    assert reader.post(_url(voce), _post(voce, QUATTRO)).status_code == 403
    assert voce.quote.count() == 0


def test_anteprima_ignora_le_righe_eliminate_e_mostra_gli_avvisi(editor):
    voce = _voce_sal()
    risposta = editor.post(
        reverse("contratti:voce_anteprima_esistente", args=[voce.contratto_id, voce.pk]),
        _post(voce, [("01/07/2025", "30/06/2026", "1.000,00")]),
    )
    html = risposta.content.decode()
    assert "A SAL non si generano rate" in html and "attraversano due anni" in html
