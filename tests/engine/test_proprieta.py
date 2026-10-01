"""Proprietà (hypothesis): ogni ripartizione quadra al centesimo con il valore della voce."""

import datetime
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from contratti.engine.budget import calcola, valore
from contratti.engine.importi import ripartisci
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import Livello, Modalita, Piano, Quota, Voce

importi = st.decimals(min_value=Decimal("0"), max_value=Decimal("9999999.99"), places=2)
date_inizio = st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2035, 12, 31))
modalita = st.sampled_from(
    [Modalita.ANTICIPATA, Modalita.POSTICIPATA, Modalita.UNA_TANTUM, Modalita.CONSUMO]
)
periodicita = st.sampled_from(
    ["mensile", "bimestrale", "trimestrale", "semestrale", "annuale", "intera_durata"]
)


@st.composite
def voci(draw):
    inizio = draw(date_inizio)
    fine = inizio + datetime.timedelta(days=draw(st.integers(min_value=0, max_value=6 * 366)))
    massimale = draw(importi)
    pct = draw(st.one_of(st.none(), st.decimals(min_value=0, max_value=100, places=2)))
    piano = Piano(modalita=draw(modalita), periodicita=draw(periodicita))
    return Voce(
        importo_fisso=draw(importi),
        inizio=inizio,
        fine=fine,
        anno_impegno=inizio.year,
        piano=piano,
        massimale_variabile=massimale,
        stima_consumo_pct=pct,
    )


@settings(max_examples=300, deadline=None)
@given(voci())
def test_competenza_quadra_con_il_valore_della_voce(v):
    viste, _ = calcola([v])
    for livello in Livello:
        attese = valore(v, livello)
        assert viste["competenza"].totale(livello) == attese
        assert viste["impegno"].totale(livello) == attese
        assert viste["cassa"].totale(livello) == attese
        assert attese == attese.quantize(Decimal("0.01"))


@settings(max_examples=300, deadline=None)
@given(voci())
def test_rate_quadrano_e_non_sono_negative(v):
    rate = genera_rate(v)
    assert sum((r.importo for r in rate), Decimal("0")) == valore(v, Livello.FISSO)
    assert all(r.importo >= 0 for r in rate)
    assert all(v.inizio <= (r.periodo_inizio or v.inizio) for r in rate)
    assert [r.numero for r in rate] == list(range(1, len(rate) + 1))


@settings(max_examples=300, deadline=None)
@given(v=voci())
def test_livelli_ordinati(v):
    assert valore(v, Livello.FISSO) <= valore(v, Livello.PROBABILE) <= valore(v, Livello.MASSIMO)


@given(
    totale=importi,
    pesi=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=40),
)
def test_ripartisci_quadra_sempre(totale, pesi):
    quote = ripartisci(totale, pesi)
    assert sum(quote) == totale
    assert all(q >= 0 for q in quote)


@st.composite
def voci_con_quote(draw):
    v = draw(voci())
    giorni_totali = (v.fine - v.inizio).days + 1
    tagli = sorted(
        set(draw(st.lists(st.integers(1, max(1, giorni_totali - 1)), max_size=5))) - {giorni_totali}
    )
    confini = [0, *tagli, giorni_totali]
    pesi = [confini[i + 1] - confini[i] for i in range(len(confini) - 1)]
    importi_quote = ripartisci(v.importo_fisso, pesi)
    quote = tuple(
        Quota(
            v.inizio + datetime.timedelta(days=confini[i]),
            v.inizio + datetime.timedelta(days=confini[i + 1] - 1),
            importi_quote[i],
        )
        for i in range(len(pesi))
    )
    return Voce(**{**v.__dict__, "quote": quote})


@settings(max_examples=200, deadline=None)
@given(voci_con_quote())
def test_con_quote_tutto_quadra(v):
    viste, esiti = calcola([v])
    assert esiti == [] or [e.codice for e in esiti] == ["CASSA_PRO_RATA"]
    for livello in Livello:
        assert viste["competenza"].totale(livello) == valore(v, livello)
        assert viste["cassa"].totale(livello) == valore(v, livello)
    assert sum((r.importo for r in genera_rate(v)), Decimal("0")) == valore(v, Livello.FISSO)
