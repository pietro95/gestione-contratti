"""Contratto che vale come ODA (Rev41): la fattura salta RdC e rilascio della RdC."""

import datetime

import pytest

from contratti.engine.acquisti import (
    DatiPAC,
    LavorazioneFattura,
    PassoFattura,
    commento_pac,
    passo_fattura,
)

D = datetime.date
OGGI = D(2026, 10, 7)
CONVALIDATA = LavorazioneFattura(in_carico_dal=OGGI, esito="convalidabile", convalidata_il=OGGI)
CONVALIDATA_ODA = LavorazioneFattura(
    in_carico_dal=OGGI, esito="convalidabile", convalidata_il=OGGI, contratto_oda=True
)


@pytest.mark.parametrize(
    ("documenti", "lavorazione", "atteso"),
    [
        ([], CONVALIDATA, PassoFattura.RDC),
        ([], CONVALIDATA_ODA, PassoFattura.MAP_MIGO),
        # RdC registrata e non rilasciata: senza ODA aspetta il rilascio, con ODA non conta.
        ([("ODA_RDC", OGGI, False)], CONVALIDATA, PassoFattura.RDC_RILASCIO),
        ([("ODA_RDC", OGGI, False)], CONVALIDATA_ODA, PassoFattura.MAP_MIGO),
        ([("MAP", OGGI, False)], CONVALIDATA_ODA, PassoFattura.MAP_MIGO_RILASCIO),
        ([("MAP", OGGI, True)], CONVALIDATA_ODA, PassoFattura.TRASFERIMENTO),
        ([("MIGO", OGGI)], CONVALIDATA_ODA, PassoFattura.TRASFERIMENTO),
    ],
)
def test_passi_con_contratto_oda(documenti, lavorazione, atteso):
    assert passo_fattura(documenti, OGGI, None, lavorazione) == atteso


def test_la_convalida_resta_prima_della_rdc_anche_con_oda():
    lav = LavorazioneFattura(in_carico_dal=OGGI, esito="da_valutare", contratto_oda=True)
    assert passo_fattura([], OGGI, None, lav) == PassoFattura.CONVALIDA


def _pac(**kw):
    return DatiPAC(
        numero_rdc=None,
        accettazione="MAP",
        numero_accettazione="MAP-0001",
        centro_costo="C0001",
        conto="600010",
        wbs=None,
        valore_base=None,
        numero_contratto="5800000013",
        **kw,
    )


def test_commento_pac_riporta_il_contratto_come_oda():
    assert "ODA : 5800000013" in commento_pac(_pac(contratto_oda=True)).splitlines()
    assert "ODA : (da registrare)" in commento_pac(_pac()).splitlines()
