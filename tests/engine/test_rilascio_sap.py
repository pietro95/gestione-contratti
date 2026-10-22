"""Rilascio su SAP di RdC, MAP e MIGO: passi della fattura (motore puro)."""

import datetime

from contratti.engine.acquisti import PassoFattura, passo_fattura

D = datetime.date
OGGI = D(2026, 10, 7)
Passo = PassoFattura
ODA, MAP, MIGO = "ODA_RDC", "MAP", "MIGO"


def passo(*documenti):
    return passo_fattura(list(documenti), OGGI)


def test_rdc_registrata_e_non_rilasciata_va_rilasciata():
    assert passo((ODA, D(2026, 10, 1), False)) == Passo.RDC_RILASCIO


def test_rdc_rilasciata_passa_al_map_migo():
    assert passo((ODA, D(2026, 10, 1), True)) == Passo.MAP_MIGO


def test_map_non_rilasciato_va_rilasciato():
    documenti = [(ODA, D(2026, 10, 1), True), (MAP, D(2026, 10, 2), False)]
    assert passo(*documenti) == Passo.MAP_MIGO_RILASCIO


def test_migo_non_rilasciato_va_rilasciato():
    documenti = [(ODA, D(2026, 10, 1), True), (MIGO, D(2026, 10, 2), False)]
    assert passo(*documenti) == Passo.MAP_MIGO_RILASCIO


def test_tutto_rilasciato_da_trasferire():
    documenti = [(ODA, D(2026, 10, 1), True), (MAP, D(2026, 10, 2), True)]
    assert passo(*documenti) == Passo.TRASFERIMENTO


def test_il_rilascio_della_rdc_viene_prima_del_map_registrato_fuori_ordine():
    documenti = [(ODA, D(2026, 10, 1), False), (MAP, D(2026, 10, 2), True)]
    assert passo(*documenti) == Passo.RDC_RILASCIO


def test_documenti_senza_rilascio_valgono_rilasciati():
    """Le coppie (tipo, data) dei casi di prova precedenti non cambiano (TC-15 e, TC-18)."""
    assert passo((ODA, D(2026, 10, 1)), (MAP, D(2026, 10, 2))) == Passo.TRASFERIMENTO
    assert passo((ODA, D(2026, 10, 1))) == Passo.MAP_MIGO


def test_documento_con_data_futura_non_conta():
    assert passo((ODA, D(2026, 10, 8), False)) == Passo.RDC


def test_rilasciato_un_solo_map_basta():
    documenti = [
        (ODA, D(2026, 10, 1), True),
        (MAP, D(2026, 10, 2), False),
        (MAP, D(2026, 10, 3), True),
    ]
    assert passo(*documenti) == Passo.TRASFERIMENTO
