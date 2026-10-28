"""Ripartizione della competenza a mesi frazionati (SPEC §5.2, Rev31, TC-24)."""

import calendar
import datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contratti.engine.budget import calcola
from contratti.engine.date import aggiungi_mesi
from contratti.engine.mesi_frazionati import competenza_per_anno, pesi_per_anno
from contratti.engine.tipi import Livello

from .casi import D, euro, piano, voce

UN_GIORNO = datetime.timedelta(days=1)
CANONE = Decimal("6500.00")


def somma(per_anno: dict[int, Decimal]) -> Decimal:
    return sum(per_anno.values(), Decimal("0.00"))


# --- TC-24: il caso DPO (canone annuo, contratti contigui a cavallo d'anno) --------------------


def test_dpo_primo_contratto():
    assert competenza_per_anno(CANONE, D(2026, 6, 8), D(2027, 6, 7)) == {
        2026: euro("3665.28"),
        2027: euro("2834.72"),
    }


def test_dpo_secondo_contratto():
    assert competenza_per_anno(CANONE, D(2027, 6, 8), D(2028, 6, 7)) == {
        2027: euro("3665.28"),
        2028: euro("2834.72"),
    }


def test_dpo_i_due_contratti_sommano_il_canone_nell_anno_coperto_per_intero():
    primo = competenza_per_anno(CANONE, D(2026, 6, 8), D(2027, 6, 7))
    secondo = competenza_per_anno(CANONE, D(2027, 6, 8), D(2028, 6, 7))
    assert primo[2027] + secondo[2027] == euro("6500.00")


def test_dpo_nel_motore_del_budget_la_competenza_2027_e_il_canone():
    """Stesso caso, attraverso le viste del budget (non solo la funzione)."""
    contratti = [
        voce("6500.00", D(2026, 6, 8), D(2027, 6, 7), piano=piano("anticipata", "annuale")),
        voce("6500.00", D(2027, 6, 8), D(2028, 6, 7), piano=piano("anticipata", "annuale")),
    ]
    viste, _ = calcola(contratti)
    assert viste["competenza"].importo(2027, Livello.FISSO) == euro("6500.00")
    # Il consuntivo senza fatture segue le rate: il budget di riferimento non cambia.
    assert viste["cassa"].importo(2027, Livello.FISSO) == euro("6500.00")


# --- Casi particolari ---------------------------------------------------------------------------


CASI = {
    "un_giorno": ("100.00", D(2026, 3, 15), D(2026, 3, 15), {2026: "100.00"}),
    "un_giorno_a_capodanno": ("100.00", D(2026, 12, 31), D(2026, 12, 31), {2026: "100.00"}),
    "annuale_solare": ("1200.00", D(2026, 1, 1), D(2026, 12, 31), {2026: "1200.00"}),
    "annuale_solare_bisestile": ("1200.00", D(2028, 1, 1), D(2028, 12, 31), {2028: "1200.00"}),
    "mesi_interi_a_cavallo": (
        "1200.00",
        D(2026, 7, 1),
        D(2027, 6, 30),
        {2026: "600.00", 2027: "600.00"},
    ),
    "inizio_il_31": ("1200.00", D(2026, 1, 31), D(2027, 1, 30), {2026: "1103.23", 2027: "96.77"}),
    "inizio_il_29_febbraio": (
        "1000.00",
        D(2028, 2, 29),
        D(2029, 2, 28),
        {2028: "833.81", 2029: "166.19"},
    ),
    "pluriennale_36_mesi": (
        "36000.00",
        D(2026, 3, 1),
        D(2029, 2, 28),
        {2026: "10000.00", 2027: "12000.00", 2028: "12000.00", 2029: "2000.00"},
    ),
    "pluriennale_24_mesi": (
        "24000.00",
        D(2026, 7, 1),
        D(2028, 6, 30),
        {2026: "6000.00", 2027: "12000.00", 2028: "6000.00"},
    ),
    "a_cavallo_di_anno_bisestile": (
        "4800.00",
        D(2027, 12, 21),
        D(2028, 12, 20),
        {2027: "141.94", 2028: "4658.06"},
    ),
    "importo_zero": ("0.00", D(2026, 5, 1), D(2027, 4, 30), {2026: "0.00", 2027: "0.00"}),
}


@pytest.mark.parametrize("nome", CASI)
def test_casi_particolari(nome):
    importo, inizio, fine, atteso = CASI[nome]
    risultato = competenza_per_anno(Decimal(importo), inizio, fine)
    assert risultato == {anno: Decimal(v) for anno, v in atteso.items()}
    assert somma(risultato) == Decimal(importo)


def test_la_tariffa_non_dipende_dalla_lunghezza_dell_anno():
    # Due contratti identici di 12 mesi interi: uno su anni bisestili (2028), uno no (2026).
    normale = competenza_per_anno(CANONE, D(2026, 4, 1), D(2027, 3, 31))
    bisestile = competenza_per_anno(CANONE, D(2028, 4, 1), D(2029, 3, 31))
    assert list(normale.values()) == list(bisestile.values()) == [euro("4875.00"), euro("1625.00")]


def test_il_residuo_di_centesimi_va_all_anno_di_peso_maggiore():
    # 26 mesi (12 + 12 + 2): 46,15 + 46,15 + 7,69 = 99,99, manca un centesimo. Va a uno dei due
    # anni di peso maggiore (l'ultimo dei due), non all'ultimo anno del periodo.
    risultato = competenza_per_anno(Decimal("100.00"), D(2026, 1, 1), D(2028, 2, 29))
    assert risultato == {2026: euro("46.15"), 2027: euro("46.16"), 2028: euro("7.69")}
    assert somma(risultato) == euro("100.00")


def test_il_residuo_a_parita_di_peso_va_all_ultimo_anno():
    # 4 mesi, 2 + 2: 50,005 per anno, arrotondati a 50,01 + 50,01 = 100,02: un centesimo di troppo.
    risultato = competenza_per_anno(Decimal("100.01"), D(2026, 11, 1), D(2027, 2, 28))
    assert risultato == {2026: euro("50.01"), 2027: euro("50.00")}


@pytest.mark.parametrize("importo", ["0.01", "0.02", "0.03", "99.99", "1234.57", "-250.25"])
def test_centesimi_dispari_quadrano(importo):
    risultato = competenza_per_anno(Decimal(importo), D(2026, 8, 17), D(2029, 2, 3))
    assert somma(risultato) == Decimal(importo)


def test_i_pesi_sono_frazioni_esatte_di_mese():
    pesi = pesi_per_anno(D(2026, 6, 8), D(2027, 6, 7))
    assert pesi == {2026: Fraction(6) + Fraction(23, 30), 2027: Fraction(5) + Fraction(7, 30)}
    assert sum(pesi.values()) == 12


def test_gli_importi_sono_decimal_e_le_quote_hanno_due_decimali():
    risultato = competenza_per_anno(Decimal("1234.56"), D(2026, 3, 9), D(2028, 9, 8))
    assert all(
        isinstance(v, Decimal) and v == v.quantize(Decimal("0.01")) for v in risultato.values()
    )


@pytest.mark.parametrize(
    ("inizio", "fine"),
    [
        (D(2026, 5, 2), D(2026, 5, 1)),
        (D(2026, 5, 2), D(2025, 12, 31)),
        (D(2027, 1, 1), D(2026, 1, 1)),
    ],
)
def test_periodo_degenere_solleva_value_error(inizio, fine):
    with pytest.raises(ValueError):
        competenza_per_anno(CANONE, inizio, fine)


# --- Invariante 2: contratti contigui sommano il canone annuo ----------------------------------


def _catena(inizio: datetime.date, contratti: int = 4) -> dict[int, Decimal]:
    """Competenza per anno di ``contratti`` contratti da 12 mesi contigui (SPEC §5.1)."""
    totale: dict[int, Decimal] = {}
    for k in range(contratti):
        da = aggiungi_mesi(inizio, 12 * k)
        a = aggiungi_mesi(inizio, 12 * (k + 1)) - UN_GIORNO
        for anno, importo in competenza_per_anno(CANONE, da, a).items():
            totale[anno] = totale.get(anno, Decimal("0.00")) + importo
    return totale


def _anni_coperti_per_intero(inizio: datetime.date, contratti: int = 4) -> range:
    fine = aggiungi_mesi(inizio, 12 * contratti) - UN_GIORNO
    return range(inizio.year + 1, fine.year)


def giorni_dell_anno(anno: int):
    return (
        datetime.date(anno, 1, 1) + datetime.timedelta(days=n)
        for n in range(366 if calendar.isleap(anno) else 365)
    )


@pytest.mark.parametrize("anno_inizio", [2025, 2026, 2027, 2028])
def test_catena_di_contratti_annuali_somma_il_canone(anno_inizio):
    """Per ogni giorno di confine fuori da febbraio, gli anni solari interi valgono il canone."""
    for inizio in giorni_dell_anno(anno_inizio):
        if inizio.month == 2:
            continue
        catena = _catena(inizio)
        for anno in _anni_coperti_per_intero(inizio):
            assert catena[anno] == CANONE, (inizio, anno, catena[anno])


def test_confine_a_febbraio_tra_anno_bisestile_e_non_scarto_documentato():
    """Caso in cui l'invariante (2) NON vale: il peso del mese iniziale e quello del mese finale
    di uno stesso contratto sono frazioni di febbraio di lunghezza diversa (28 e 29 giorni), quindi
    il peso totale non è 12 mesi esatti. Non si corregge con un workaround: si segnala (SPEC §5.2).
    """
    primo = competenza_per_anno(CANONE, D(2027, 2, 15), D(2028, 2, 14))
    secondo = competenza_per_anno(CANONE, D(2028, 2, 15), D(2029, 2, 14))
    assert somma(primo) == somma(secondo) == CANONE  # invariante (1): sempre valida
    scarto = primo[2028] + secondo[2028] - CANONE
    assert scarto == euro("-7.01")
    assert abs(scarto) / CANONE < Decimal("0.0025")  # sempre sotto lo 0,25% del canone


def test_gli_unici_confini_che_non_quadrano_sono_a_febbraio():
    fuori = {}
    for anno_inizio in range(2024, 2029):
        for inizio in giorni_dell_anno(anno_inizio):
            catena = _catena(inizio)
            for anno in _anni_coperti_per_intero(inizio):
                if catena[anno] != CANONE:
                    fuori[inizio] = catena[anno] - CANONE
    assert {d.month for d in fuori} <= {2}
    assert all(abs(s) < Decimal("16.00") for s in fuori.values())  # 0,25% di 6.500,00


# --- Invariante 1 + oracolo indipendente (proprietà) -------------------------------------------


def oracolo(importo: Decimal, inizio: datetime.date, fine: datetime.date) -> dict[int, Fraction]:
    """Ogni giorno pesa 1 / giorni del suo mese; quota esatta, non arrotondata."""
    pesi: dict[int, Fraction] = {}
    giorno = inizio
    while giorno <= fine:
        pesi[giorno.year] = pesi.get(giorno.year, Fraction(0)) + Fraction(
            1, calendar.monthrange(giorno.year, giorno.month)[1]
        )
        giorno += UN_GIORNO
    totale = sum(pesi.values(), Fraction(0))
    esatto = Fraction(importo)
    return {anno: esatto * peso / totale for anno, peso in pesi.items()}


importi = st.decimals(min_value=Decimal("-99999999.99"), max_value=Decimal("99999999.99"), places=2)
inizi = st.dates(min_value=datetime.date(2015, 1, 1), max_value=datetime.date(2045, 12, 31))


@st.composite
def periodi(draw):
    inizio = draw(inizi)
    return inizio, inizio + datetime.timedelta(days=draw(st.integers(0, 12 * 366)))


@settings(max_examples=300, deadline=None)
@given(importo=importi, periodo=periodi())
def test_proprieta_la_somma_per_anno_e_l_importo(importo, periodo):
    inizio, fine = periodo
    risultato = competenza_per_anno(importo, inizio, fine)
    assert somma(risultato) == importo
    assert set(risultato) == set(range(inizio.year, fine.year + 1))


@settings(max_examples=200, deadline=None)
@given(importo=importi, periodo=periodi())
def test_proprieta_ogni_quota_dista_poco_dal_valore_esatto(importo, periodo):
    """Scarto = mezzo centesimo di arrotondamento + residuo; il residuo vale al più mezzo centesimo
    per anno (con il fallback cumulato, meno di un centesimo in tutto)."""
    inizio, fine = periodo
    risultato = competenza_per_anno(importo, inizio, fine)
    esatto = oracolo(importo, inizio, fine)
    limite = Fraction(len(risultato) + 1, 200)
    for anno, quota in risultato.items():
        assert abs(Fraction(quota) - esatto[anno]) <= limite


@settings(max_examples=200, deadline=None)
@given(
    importo=st.decimals(min_value=Decimal("0"), max_value=Decimal("99999999.99"), places=2),
    periodo=periodi(),
)
def test_proprieta_nessuna_quota_di_segno_opposto_all_importo(importo, periodo):
    inizio, fine = periodo
    assert all(v >= 0 for v in competenza_per_anno(importo, inizio, fine).values())


def test_arrotondamento_half_up_come_decimal():
    # 0,5 centesimi esatti: 0,01 su due anni di peso pari → 0,005 ciascuno → half up = 0,01.
    risultato = competenza_per_anno(Decimal("0.01"), D(2026, 12, 1), D(2027, 1, 31))
    assert somma(risultato) == euro("0.01")
    assert Decimal("0.005").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == euro("0.01")
