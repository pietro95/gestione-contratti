"""modifica_voce: «quote» sostituisce tutte le quote per periodo (SPEC_MCP Rev07, SPEC Rev28).

Anteprima e conferma come le altre scritture; le quote tolte restano nella storia con i loro
valori; le regole sono quelle del form della voce (voci a SAL: niente sovrapposizioni, somma
entro il fisso).
"""

import datetime
from decimal import Decimal

import pytest

from connettore.models import OperazioneMCP
from contratti import models as m
from tests import factories as f
from tests.connettore.test_scrittura import chiama, ctx, errore, ok
from tests.connettore.test_scrittura_equivalenza import mcp

pytestmark = pytest.mark.django_db
D = datetime.date
FISSO = Decimal("2947639.75")
QUOTE_230 = [
    ("2024-01-01", "2024-12-31", "0.00"),
    ("2025-01-01", "2025-12-31", "1486870.87"),
    ("2026-01-01", "2026-12-31", "1144060.62"),
    ("2027-01-01", "2027-12-31", "316708.26"),
]


def _quote(voce):
    return [
        (q.dal.isoformat(), q.al.isoformat(), str(q.importo)) for q in voce.quote.order_by("dal")
    ]


def _argomenti(quote):
    return [{"dal": d, "al": a, "importo": i} for d, a, i in quote]


@pytest.fixture
def lavori():
    c = f.contratto(
        data_inizio=D(2024, 10, 15),
        durata_mesi=29,
        data_fine_override=D(2027, 3, 31),
        numero_contratto="5800000230",
    )
    voce = f.voce(c, descrizione="Lavori", importo_fisso=FISSO)
    f.piano(voce, modalita="sal", periodicita="")
    for dal, al, importo in QUOTE_230:
        m.QuotaPeriodo.objects.create(
            voce=voce, dal=D.fromisoformat(dal), al=D.fromisoformat(al), importo=Decimal(importo)
        )
    return voce


def test_anteprima_mostra_quote_tolte_e_nuove_senza_scrivere(editor, lavori):
    nuove = [("2025-01-01", "2025-12-31", "1486870.87"), ("2026-01-01", "2026-12-31", "1460768.88")]
    r = ok(ctx(editor), "modifica_voce", {"id": lavori.pk, "quote": _argomenti(nuove)})
    assert _quote(lavori) == QUOTE_230  # niente di scritto
    quote = [x for x in r["modifiche"] if x["oggetto"] == "quota per periodo"]
    assert sorted(x["tipo"] for x in quote) == ["creato"] * 2 + ["eliminato"] * 4
    eliminate = {x["campi"]["importo"] for x in quote if x["tipo"] == "eliminato"}
    assert eliminate == {"0.00", "1486870.87", "1144060.62", "316708.26"}
    (voce,) = [o for o in r["oggetti_esistenti"] if o["tipo"] == "vocecontratto"]
    assert voce["id"] == lavori.pk


def test_conferma_sostituisce_tutte_le_quote(editor, lavori):
    nuove = [("2025-01-01", "2025-12-31", "1486870.87"), ("2026-01-01", "2026-12-31", "1460768.88")]
    esito = mcp(editor, "modifica_voce", {"id": lavori.pk, "quote": _argomenti(nuove)})
    assert _quote(lavori) == nuove
    voce_esito = next(o for o in esito["oggetti"] if o["tipo"] == "vocecontratto")
    assert [q["importo"] for q in voce_esito["quote"]["prima"]] == [
        "0.00",
        "1486870.87",
        "1144060.62",
        "316708.26",
    ]
    assert len(voce_esito["quote"]["dopo"]) == 2


def test_le_quote_tolte_restano_nella_storia_con_i_valori_e_il_motivo(editor, lavori):
    mcp(editor, "modifica_voce", {"id": lavori.pk, "quote": []})
    assert lavori.quote.count() == 0
    storia = m.QuotaPeriodo.history.filter(history_type="-")
    assert storia.count() == 4
    assert {s.importo for s in storia} == {Decimal(i) for _, _, i in QUOTE_230}
    assert all(s.voce_id == lavori.pk and s.history_user_id == editor.pk for s in storia)
    assert all("Quote sostituite" in s.history_change_reason for s in storia)


def test_senza_quote_nell_argomento_restano_quelle_che_ci_sono(editor, lavori):
    mcp(editor, "modifica_voce", {"id": lavori.pk, "descrizione": "Lavori (rev.)"})
    assert _quote(lavori) == QUOTE_230


def test_stesse_date_con_importi_diversi_non_violano_l_unicita(editor, lavori):
    nuove = [(d, a, "100.00") for d, a, _ in QUOTE_230]
    mcp(editor, "modifica_voce", {"id": lavori.pk, "quote": _argomenti(nuove)})
    assert _quote(lavori) == nuove


def test_quote_sovrapposte_di_un_sal_rifiutate_senza_toccare_le_esistenti(editor, lavori):
    sovrapposte = [("2025-01-01", "2025-12-31", "100.00"), ("2025-06-01", "2026-06-30", "100.00")]
    testo = errore(
        ctx(editor), "modifica_voce", {"id": lavori.pk, "quote": _argomenti(sovrapposte)}
    )
    assert "ovrappone" in testo and "quote[1]" in testo
    assert _quote(lavori) == QUOTE_230  # la sostituzione è annullata insieme all'errore
    assert not OperazioneMCP.objects.exists()


def test_somma_oltre_il_fisso_di_un_sal_rifiutata(editor, lavori):
    troppe = [("2025-01-01", "2025-12-31", "3000000.00")]
    testo = errore(ctx(editor), "modifica_voce", {"id": lavori.pk, "quote": _argomenti(troppe)})
    assert "supera l'importo fisso" in testo
    assert _quote(lavori) == QUOTE_230


def test_quote_ad_anno_solare_oltre_il_servizio_ammesse_per_un_sal(editor, lavori):
    # 01/01/2024 prima dell'inizio (15/10/2024), 31/12/2027 dopo la fine (31/03/2027).
    mcp(editor, "modifica_voce", {"id": lavori.pk, "quote": _argomenti(QUOTE_230)})
    assert _quote(lavori) == QUOTE_230


def test_anteprima_riporta_gli_avvisi_non_bloccanti(editor, lavori):
    # Somma inferiore al fisso e quota a cavallo di due anni: si accettano, con avviso.
    quote = [("2025-07-01", "2026-06-30", "1000.00")]
    r = ok(ctx(editor), "modifica_voce", {"id": lavori.pk, "quote": _argomenti(quote)})
    testo = " ".join(r["avvisi"])
    assert "attraversano due anni" in testo and "SAL non pianificato" in testo


def test_voce_non_sal_con_quote_incoerenti_si_salva_con_avviso(editor):
    c = f.contratto(data_inizio=D(2026, 1, 1), durata_mesi=24)
    voce = f.voce(c, importo_fisso=Decimal("2400.00"))
    f.piano(voce, modalita="posticipata", periodicita="annuale")
    # Non partono dall'inizio del servizio: non bloccano il salvataggio, ma vengono ignorate.
    quote = [("2026-07-01", "2026-12-31", "1000.00")]
    r = ok(ctx(editor), "modifica_voce", {"id": voce.pk, "quote": _argomenti(quote)})
    assert any("non coerenti" in a for a in r["avvisi"])
    mcp(editor, "modifica_voce", {"id": voce.pk, "quote": _argomenti(quote)})
    assert voce.quote.count() == 1


def test_il_reader_non_puo_sostituire_le_quote(make_user, lavori):
    from accounts.roles import READER

    lettore = make_user("lettore2", role=READER)
    r = chiama(ctx(lettore), "modifica_voce", {"id": lavori.pk, "quote": []})
    assert r["isError"] is True
    assert _quote(lavori) == QUOTE_230
