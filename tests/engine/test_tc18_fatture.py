"""TC-18 sul motore: passi Rev15, convalida, importi, commento per PAC (SPEC §4, §5.9)."""

import datetime
from decimal import Decimal

import pytest

from contratti.engine.acquisti import (
    DatiPAC,
    FatturaRegistrata,
    LavorazioneFattura,
    PassoFattura,
    anomalie_esecuzione,
    commento_pac,
    esecuzione,
    fattura_da_lavorare,
    importo_quadra,
    indicazioni_validazione,
    passo_fattura,
    primo_referente,
    valore_base_proposto,
)

D = datetime.date
OGGI = D(2026, 10, 7)

PAC_ATTESO = """Contratto: 5800000013
ODA : RDC-0001
MAP: MAP-0001
CDC: C0001
COGE: 600010
WBS: WBS-TEST-01

Valore base prelevato da contratto: € 1.504,17
Oneri previdenziali: € 173,66
Bollo: € 2,00"""

DATI_13 = DatiPAC(
    numero_contratto="5800000013",
    numero_rdc="RDC-0001",
    accettazione="MAP",
    numero_accettazione="MAP-0001",
    centro_costo="C0001",
    conto="600010",
    wbs="WBS-TEST-01",
    valore_base=Decimal("1504.17"),
    oneri=Decimal("173.66"),
    bollo=Decimal("2.00"),
)


@pytest.mark.parametrize(
    ("lavorazione", "atteso"),
    [
        (LavorazioneFattura(in_carico_dal=None, assegnata=False, esito="da_valutare"),
         PassoFattura.PRESA_IN_CARICO),
        (LavorazioneFattura(in_carico_dal=OGGI, assegnata=False, esito="da_valutare"),
         PassoFattura.ASSEGNAZIONE),
        (LavorazioneFattura(in_carico_dal=OGGI, esito="da_valutare"), PassoFattura.CONVALIDA),
        (LavorazioneFattura(in_carico_dal=OGGI, esito="convalidabile", convalidata_il=OGGI),
         PassoFattura.RDC),
        # Presa in carico domani: oggi non conta.
        (LavorazioneFattura(in_carico_dal=D(2026, 10, 8)), PassoFattura.PRESA_IN_CARICO),
    ],
)  # fmt: skip
def test_passi_rev15(lavorazione, atteso):
    assert passo_fattura([], OGGI, None, lavorazione) == atteso


def test_convalida_in_attesa_e_bloccata():
    """FA-1/2026: in attesa e bloccata fino al 06/10/2026: bloccata fino a quella data
    (compresa), poi di nuovo da convalidare."""
    attesa = LavorazioneFattura(
        in_carico_dal=D(2026, 10, 1), esito="in_attesa", bloccata_fino_al=D(2026, 10, 6)
    )
    assert passo_fattura([], D(2026, 10, 6), None, attesa) == PassoFattura.BLOCCATA
    for oggi in (D(2026, 10, 7), D(2026, 12, 31)):
        assert passo_fattura([], oggi, None, attesa) == PassoFattura.CONVALIDA
    convalidabile = LavorazioneFattura(
        in_carico_dal=D(2026, 10, 1), esito="convalidabile", bloccata_fino_al=D(2026, 10, 6)
    )
    # «Fino al» compreso: il 06/10 è ancora bloccata, dal 07/10 si passa alla RdC.
    assert passo_fattura([], D(2026, 10, 6), None, convalidabile) == PassoFattura.BLOCCATA
    assert passo_fattura([], D(2026, 10, 7), None, convalidabile) == PassoFattura.RDC
    non = LavorazioneFattura(in_carico_dal=D(2026, 10, 1), esito="non_convalidabile")
    assert passo_fattura([], OGGI, None, non) == PassoFattura.CONVALIDA


def test_fuori_registro_non_da_lavorare():
    fuori = LavorazioneFattura(in_carico_dal=None, assegnata=False, fuori_registro=True)
    assert not fattura_da_lavorare([], OGGI, None, fuori)
    assert fattura_da_lavorare([], OGGI, None, LavorazioneFattura(in_carico_dal=None))


def test_importi_13_2026():
    base, oneri, bollo = Decimal("1504.17"), Decimal("173.66"), Decimal("2.00")
    assert importo_quadra(Decimal("1679.83"), base, oneri, bollo)
    assert not importo_quadra(Decimal("1679.83"), base, oneri, Decimal("3.00"))
    assert importo_quadra(Decimal("1679.83"), None, None, None)  # senza valore base: non giudica
    assert valore_base_proposto(Decimal("1679.83"), oneri, bollo) == base


def test_fatturato_sul_valore_base():
    """Fatturato di CS: 1.504,17, non 1.679,83; senza valore base non conta ed è segnalata."""
    fatture = [FatturaRegistrata(D(2026, 9, 28), Decimal("1504.17"), "13/2026", 1)]
    assert esecuzione(Decimal(5000), Decimal(0), fatture, OGGI).fatturato == Decimal("1504.17")
    con_vuota = [*fatture, FatturaRegistrata(D(2026, 9, 30), None, "14/2026", 1)]
    assert esecuzione(Decimal(5000), Decimal(0), con_vuota, OGGI).fatturato == Decimal("1504.17")
    assert anomalie_esecuzione(Decimal(5000), Decimal(0), con_vuota, [], None, OGGI) == [
        "VALORE_BASE_MANCANTE"
    ]


def test_commento_per_pac():
    assert commento_pac(DATI_13) == PAC_ATTESO


def test_commento_per_pac_senza_map_ne_oneri():
    dati = DatiPAC(
        numero_rdc="RDC-0001", accettazione="MAP", numero_accettazione=None,
        centro_costo="C0001", conto="600010", wbs="WBS-TEST-01",
        valore_base=Decimal("1504.17"),
    )  # fmt: skip
    righe = commento_pac(dati).splitlines()
    assert righe[0] == "Contratto: --"
    assert righe[2] == "MAP: (da registrare)"
    assert righe[-1] == "Valore base prelevato da contratto: € 1.504,17"
    migo = DatiPAC(None, "MIGO", None, None, None, None, None)
    assert commento_pac(migo).splitlines()[:6] == [
        "Contratto: --", "ODA : (da registrare)", "MIGO: (da registrare)", "CDC: --",
        "COGE: --", "WBS: --",
    ]  # fmt: skip


def test_indicazioni_per_la_validazione():
    assert indicazioni_validazione(DATI_13) == (
        "Contratto 5800000013. Valore base da prelevare € 1.504,17. "
        "COGE: 600010, CDC: C0001, WBS: WBS-TEST-01"
    )


def test_primo_referente():
    assert primo_referente([None, "bianchi", "verdi"]) == "bianchi"
    assert primo_referente([None, None]) is None
