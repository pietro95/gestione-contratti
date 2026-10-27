"""Voci a SAL (SPEC §5.2, Rev29): il fatturato non è mai una ripartizione lineare sul tempo.

Caso di riferimento: voce a SAL di lavori (importo fisso 2.947.639,75) dal 15/10/2024 al
31/03/2027, con le quote ad anno solare e le sei fatture del caso reale, in forma anonima.
"""

from dataclasses import replace

import pytest

from contratti.engine.budget import calcola, ripartizione_sal
from contratti.engine.previsioni import previsti
from contratti.engine.sal import errori_quote
from contratti.engine.tipi import (
    Consuntivo,
    ContrattoBase,
    Livello,
    Quota,
    Rata,
    TipoConsuntivo,
)

from .casi import D, euro, piano, voce

FISSO = "2947639.75"
INIZIO, FINE = D(2024, 10, 15), D(2027, 3, 31)

QUOTE = (
    Quota(D(2024, 1, 1), D(2024, 12, 31), euro("0.00")),
    Quota(D(2025, 1, 1), D(2025, 12, 31), euro("1486870.87")),
    Quota(D(2026, 1, 1), D(2026, 12, 31), euro("1144060.62")),
    Quota(D(2027, 1, 1), D(2027, 12, 31), euro("316708.26")),
)
# (data documento, valore base): quattro nel 2025, due nel 2026.
FATTURE = (
    (D(2025, 2, 20), "467235.71"),
    (D(2025, 5, 12), "294836.45"),
    (D(2025, 9, 3), "356049.94"),
    (D(2025, 12, 18), "368748.77"),
    (D(2026, 4, 9), "622064.41"),
    (D(2026, 9, 24), "521996.21"),
)


def _fatture(*elenco):
    return tuple(
        Consuntivo(TipoConsuntivo.FATTURA, euro(importo), data, data, data=data, riferimento=i)
        for i, (data, importo) in enumerate(elenco, start=1)
    )


def sal(**kw):
    return voce(FISSO, INIZIO, FINE, piano=piano("sal"), **kw)


def cassa(v, livello=Livello.FISSO):
    viste, esiti = calcola([v])
    return {a: i[livello] for a, i in viste["cassa"].per_anno.items() if i.get(livello)}, esiti


def codici(esiti):
    return sorted(e.codice for e in esiti)


# --- Quote -----------------------------------------------------------------------------------


def test_con_quote_la_cassa_le_usa_senza_ripartire_a_giorni():
    per_anno, esiti = cassa(sal(quote=QUOTE))
    assert per_anno == {
        2025: euro("1486870.87"),
        2026: euro("1144060.62"),
        2027: euro("316708.26"),
    }
    assert 2024 not in per_anno  # la quota 2024 è zero: nessun importo prima del servizio
    assert "CASSA_PRO_RATA" not in codici(esiti)


def test_le_quote_sono_previsto_non_consuntivo():
    r, _ = ripartizione_sal(sal(quote=QUOTE), Livello.FISSO, "cassa")
    assert r.consuntivo_per_anno() == {}
    assert r.previsto == {
        2025: euro("1486870.87"),
        2026: euro("1144060.62"),
        2027: euro("316708.26"),
    }
    assert r.non_pianificato == euro("0.00")
    assert r.fonti == ("quote",)


def test_quote_ad_anno_solare_ammesse_anche_se_la_prima_inizia_prima_del_servizio():
    # 01/01/2024 < 15/10/2024 e 31/12/2027 > 31/03/2027: per un SAL non è un'incoerenza.
    _, esiti = cassa(sal(quote=QUOTE))
    assert "QUOTE_INCOERENTI" not in codici(esiti)


def test_quote_sovrapposte_si_ignorano_e_si_segnalano():
    sovrapposte = (
        Quota(D(2025, 1, 1), D(2025, 12, 31), euro("1000.00")),
        Quota(D(2025, 6, 1), D(2026, 12, 31), euro("2000.00")),
    )
    per_anno, esiti = cassa(sal(quote=sovrapposte))
    assert per_anno == {}
    assert "QUOTE_INCOERENTI" in codici(esiti)
    assert "SAL_NON_PIANIFICATO" in codici(esiti)


def test_quote_con_somma_oltre_il_fisso_si_ignorano():
    troppe = (Quota(D(2025, 1, 1), D(2025, 12, 31), euro("3000000.00")),)
    per_anno, esiti = cassa(sal(quote=troppe))
    assert per_anno == {}
    assert "QUOTE_INCOERENTI" in codici(esiti)


def test_quota_a_cavallo_va_all_anno_del_dal_con_avviso():
    quote = (Quota(D(2025, 7, 1), D(2026, 6, 30), euro("1000.00")),)
    per_anno, esiti = cassa(sal(quote=quote))
    assert per_anno == {2025: euro("1000.00")}
    assert "SAL_QUOTA_A_CAVALLO" in codici(esiti)


def test_errori_quote_solo_sovrapposizione_e_somma():
    ok = [
        (D(2024, 1, 1), D(2024, 12, 31), euro("1.00")),
        (D(2025, 1, 1), D(2025, 12, 31), euro("1.00")),
    ]
    assert errori_quote(euro("10.00"), ok) == []
    sovrapposte = [*ok, (D(2025, 12, 31), D(2026, 3, 1), euro("1.00"))]
    ((indice, _),) = errori_quote(euro("10.00"), sovrapposte)
    assert indice == 2
    assert [i for i, _ in errori_quote(euro("1.00"), ok)] == [None]


# --- Fatture ---------------------------------------------------------------------------------


def test_senza_quote_la_cassa_e_la_somma_delle_fatture_per_anno_del_documento():
    per_anno, esiti = cassa(sal(consuntivi=_fatture(*FATTURE)))
    assert per_anno == {2025: euro("1486870.87"), 2026: euro("1144060.62")}
    assert 2024 not in per_anno and 2027 not in per_anno
    # Il residuo (316.708,26) non è fatturato: è non pianificato, segnalato.
    assert codici(esiti) == ["SAL_NON_PIANIFICATO"]
    assert "316.708,26" in esiti[0].messaggio


def test_residuo_non_pianificato_fuori_dai_totali():
    r, _ = ripartizione_sal(sal(consuntivi=_fatture(*FATTURE)), Livello.FISSO, "cassa")
    assert r.previsto == {}
    assert r.non_pianificato == euro("316708.26")
    assert sum(r.per_anno.values()) == euro("2630931.49")


def test_con_fatture_e_quote_valgono_le_fatture_e_la_quota_degli_anni_dopo():
    r, esiti = ripartizione_sal(
        sal(quote=QUOTE, consuntivi=_fatture(*FATTURE)), Livello.FISSO, "cassa"
    )
    assert r.consuntivo_per_anno() == {2025: euro("1486870.87"), 2026: euro("1144060.62")}
    # Le quote 2025 e 2026 non si contano una seconda volta; resta la quota 2027.
    assert r.previsto == {2027: euro("316708.26")}
    assert r.per_anno == {
        2025: euro("1486870.87"),
        2026: euro("1144060.62"),
        2027: euro("316708.26"),
    }
    assert r.non_pianificato == euro("0.00")
    assert r.fonti == ("fatture", "quote")
    assert codici(esiti) == []


def test_consuntivo_e_previsto_coesistono_nello_stesso_anno():
    rate = (Rata(1, D(2026, 11, 30), D(2027, 1, 31), euro("100000.00")),)
    r, _ = ripartizione_sal(sal(rate=rate, consuntivi=_fatture(FATTURE[4])), Livello.FISSO, "cassa")
    assert r.consuntivo_per_anno() == {2026: euro("622064.41")}
    assert r.previsto == {2026: euro("100000.00")}
    assert r.per_anno == {2026: euro("722064.41")}  # per_anno resta il totale


def test_il_totale_per_voce_non_supera_il_fisso():
    quote = (
        Quota(D(2025, 1, 1), D(2025, 12, 31), euro("1000000.00")),
        Quota(D(2026, 1, 1), D(2026, 12, 31), euro("1500000.00")),
        Quota(D(2027, 1, 1), D(2027, 12, 31), euro("447639.75")),
    )
    # Fatture 2024 per 1.000.000: residuo 1.947.639,75 su quote per 2.947.639,75.
    fatture = _fatture((D(2024, 12, 1), "1000000.00"))
    r, esiti = ripartizione_sal(sal(quote=quote, consuntivi=fatture), Livello.FISSO, "cassa")
    assert sum(r.per_anno.values()) == euro(FISSO)
    assert r.previsto == {2025: euro("1000000.00"), 2026: euro("947639.75")}  # taglio dal fondo
    assert "SAL_PREVISTO_ECCEDENTE" in codici(esiti)


def test_fatture_oltre_il_fisso_si_contano_per_intero_senza_previsto():
    fatture = _fatture((D(2025, 5, 1), "3000000.00"))
    r, esiti = ripartizione_sal(sal(quote=QUOTE, consuntivi=fatture), Livello.FISSO, "cassa")
    assert r.consuntivo_per_anno() == {2025: euro("3000000.00")}
    assert r.previsto == {}
    assert "SAL_FATTURATO_SUPERA_FISSO" in codici(esiti)


def test_fattura_fuori_dal_periodo_di_servizio_segnalata():
    _, esiti = cassa(sal(consuntivi=_fatture((D(2024, 3, 1), "100.00"))))
    assert "FATTURA_FUORI_PERIODO" in codici(esiti)


def test_riferimento_della_fattura_resta_sulle_righe_per_attribuirla_a_una_wbs():
    r, _ = ripartizione_sal(sal(consuntivi=_fatture(*FATTURE)), Livello.FISSO, "cassa")
    assert r.consuntivo_per_anno({1, 2, 3, 4}) == {2025: euro("1486870.87")}
    assert r.consuntivo_per_anno({5, 6}) == {2026: euro("1144060.62")}


# --- Né quote né fatture ---------------------------------------------------------------------


def test_sal_senza_quote_ne_fatture_non_ha_importi():
    per_anno, esiti = cassa(sal())
    assert per_anno == {}
    r, _ = ripartizione_sal(sal(), Livello.FISSO, "cassa")
    assert r.non_pianificato == euro(FISSO)
    assert codici(esiti) == ["SAL_NON_PIANIFICATO"]
    assert "2.947.639,75" in esiti[0].messaggio


# --- Rate inserite a mano --------------------------------------------------------------------


def test_le_rate_a_mano_sono_la_fonte_primaria_del_previsto():
    rate = (
        Rata(1, D(2026, 3, 15), D(2026, 5, 31), euro("1000000.00")),
        Rata(2, D(2027, 1, 20), D(2027, 3, 31), euro("500000.00")),
    )
    r, esiti = ripartizione_sal(sal(rate=rate, quote=QUOTE), Livello.FISSO, "cassa")
    assert r.previsto == {2026: euro("1000000.00"), 2027: euro("500000.00")}
    assert r.fonti == ("rate",)
    assert "SAL_QUOTE_E_RATE" in codici(esiti)
    assert r.non_pianificato == euro("1447639.75")


def test_rata_con_fattura_vale_la_fattura():
    fattura = _fatture((D(2026, 4, 9), "620000.00"))[0]
    rate = (
        Rata(1, D(2026, 3, 15), D(2026, 5, 31), euro("600000.00"), consuntivo=fattura),
        Rata(2, D(2027, 1, 20), D(2027, 3, 31), euro("500000.00")),
    )
    r, _ = ripartizione_sal(sal(rate=rate), Livello.FISSO, "cassa")
    assert r.consuntivo_per_anno() == {2026: euro("620000.00")}  # non 600.000 della rata
    assert r.previsto == {2027: euro("500000.00")}


# --- Livelli ---------------------------------------------------------------------------------


def test_il_variabile_segue_il_previsto_e_senza_previsto_resta_non_pianificato():
    con_quote = sal(quote=QUOTE, massimale_variabile=euro("100000.00"))
    per_anno, _ = cassa(con_quote, Livello.MASSIMO)
    assert sum(per_anno.values()) == euro(FISSO) + euro("100000.00")
    senza = sal(massimale_variabile=euro("100000.00"))
    r, _ = ripartizione_sal(senza, Livello.MASSIMO, "cassa")
    assert r.per_anno == {}
    assert r.non_pianificato == euro(FISSO) + euro("100000.00")


# --- Vista «Fatturato e stanziato» -----------------------------------------------------------


def _consuntivo(v):
    viste, esiti = calcola([v])
    return {
        a: i[Livello.FISSO] for a, i in viste["consuntivo"].per_anno.items() if i.get(Livello.FISSO)
    }, esiti


def test_consuntivo_senza_pro_rata_e_senza_doppio_conto():
    # Prima: pro-rata a giorni sull'intero contratto più le fatture.
    per_anno, esiti = _consuntivo(sal(consuntivi=_fatture(*FATTURE)))
    assert sum(per_anno.values()) == euro("2630931.49")
    assert 2024 not in per_anno and 2027 not in per_anno
    assert "SAL_NON_PIANIFICATO" in codici(esiti)


def test_consuntivo_con_quote_per_gli_anni_dopo_l_ultima_fattura():
    per_anno, _ = _consuntivo(sal(quote=QUOTE, consuntivi=_fatture(*FATTURE)))
    assert per_anno == {
        2025: euro("1486870.87"),
        2026: euro("1144060.62"),
        2027: euro("316708.26"),
    }


def test_consuntivo_imputa_le_fatture_a_giorni_sulla_competenza():
    f = Consuntivo(
        TipoConsuntivo.FATTURA, euro("1200.00"), D(2026, 7, 1), D(2027, 6, 30),
        data=D(2026, 9, 1), riferimento=1,
    )  # fmt: skip
    v = replace(sal(consuntivi=(f,)), importo_fisso=euro("1200.00"))
    per_anno, _ = _consuntivo(v)
    assert per_anno == {2026: euro("604.93"), 2027: euro("595.07")}
    # La cassa invece conta per data documento.
    assert cassa(v)[0] == {2026: euro("1200.00")}


def test_stanziamento_senza_fattura_conta_nel_consuntivo_non_nella_cassa():
    s = Consuntivo(TipoConsuntivo.STANZIAMENTO, euro("500.00"), D(2026, 1, 1), D(2026, 12, 31))
    v = replace(sal(consuntivi=(s,)), importo_fisso=euro("1000.00"))
    assert _consuntivo(v)[0] == {2026: euro("500.00")}
    assert cassa(v)[0] == {}


# --- Voci di contratti previsti ---------------------------------------------------------------


def test_voce_prevista_a_sal_resta_a_pro_rata_e_lo_dichiara():
    # Un rinnovo previsto non ha fatture, quote né rate: la previsione è a giorni, segnalata.
    v = replace(sal(), previsto=True)
    per_anno, esiti = cassa(v)
    assert sum(per_anno.values()) == euro(FISSO)
    assert 2024 in per_anno and 2027 in per_anno
    assert "CASSA_PRO_RATA" in codici(esiti)
    assert "SAL_NON_PIANIFICATO" not in codici(esiti)
    assert _consuntivo(v)[0] == per_anno  # anche nella vista Fatturato e stanziato


def test_i_previsti_di_una_voce_a_sal_sono_voci_previste():
    base = ContrattoBase(FINE, 29, (sal(),))
    (previsto,) = previsti(
        base, decisione="rinnovare", orizzonte=D(2027, 6, 1), adeguamento=lambda _: euro("0")
    )
    (v,) = previsto.voci
    assert v.previsto and v.quote == () and v.consuntivi == ()
    assert sum(cassa(v)[0].values()) == euro(FISSO)


# --- Regressione: le altre modalità non cambiano ---------------------------------------------


@pytest.mark.parametrize(
    ("modalita", "periodicita"), [("posticipata", "annuale"), ("una_tantum", "")]
)
def test_altre_modalita_restano_sulle_rate_del_piano(modalita, periodicita):
    v = voce(
        FISSO, INIZIO, FINE, piano=piano(modalita, periodicita), quote=QUOTE,
        consuntivi=_fatture(*FATTURE),
    )  # fmt: skip
    viste, esiti = calcola([v])
    assert "SAL_NON_PIANIFICATO" not in codici(esiti)
    totale_cassa = viste["cassa"].totale()
    assert totale_cassa == euro(FISSO)  # le rate coprono l'intero fisso, come prima
