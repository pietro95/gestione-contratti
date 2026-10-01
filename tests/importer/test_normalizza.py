"""TC-08 — Normalizzazione in import: valori della tabella di docs/TEST_CASES.md."""

import datetime
from decimal import Decimal

import pytest

from contratti.importer import normalizza as n


def test_bom_rimosso_da_oda_e_cig():
    assert n.oda("﻿5800005402") == ("5800005402", [])
    assert n.cig("﻿B8A520EED4") == ("B8A520EED4", [])


@pytest.mark.parametrize("valore", ["n/a", "N/A", "n/d", "", None, "  ", "0"])
def test_nulli_dei_campi_codice(valore):
    assert n.codice(valore) is None
    assert n.oda(valore) == (None, [])
    assert n.cig(valore) == (None, [])


def test_trim_del_fornitore():
    assert n.testo("  POSDATA S.r.l. ") == "POSDATA S.r.l."


def test_cig_di_9_caratteri_conservato_con_anomalia():
    valore, anomalie = n.cig("B941B595B")
    assert valore == "B941B595B"
    assert [a.codice for a in anomalie] == ["CIG_LUNGHEZZA"]


def test_oda_di_9_cifre_conservato_con_anomalia():
    valore, anomalie = n.oda(580006042)
    assert valore == "580006042"
    assert [a.codice for a in anomalie] == ["ODA_FORMATO"]


def test_oda_numerico_da_excel():
    assert n.oda(5800845502) == ("5800845502", [])
    assert n.oda(5800845502.0) == ("5800845502", [])


def test_importi_in_decimal_senza_artefatti_binari():
    assert n.importo(20623.04, "minimo") == (Decimal("20623.04"), [])
    assert n.importo(0.1, "minimo") == (Decimal("0.10"), [])
    assert n.importo(1222, "minimo") == (Decimal("1222.00"), [])
    assert n.importo("1.234,56", "minimo") == (Decimal("1234.56"), [])
    assert n.importo(None, "minimo") == (None, [])


def test_importo_da_formula_non_calcolata():
    valore, anomalie = n.importo("=A1+B1", "minimo")
    assert valore is None
    assert [a.codice for a in anomalie] == ["IMPORTO_NON_LEGGIBILE"]


def test_date():
    assert n.data(datetime.datetime(2025, 1, 1)) == datetime.date(2025, 1, 1)
    assert n.data("31/12/2026") == datetime.date(2026, 12, 31)
    assert n.data("n/a") is None
    assert n.data(None) is None


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Fornitore 10 S.r.l.", "FORNITORE 10 SRL"),
        ("Fornitore  10 s.r.l", "fornitore 10"),
        ("Società Esempio S.p.A.", "SOCIETA ESEMPIO SPA"),
    ],
)
def test_chiave_nome(a, b):
    assert n.chiave_nome(a) == n.chiave_nome(b)


@pytest.mark.parametrize(
    ("nota", "rda"),
    [
        ("RDA 3563270716", "3563270716"),
        ("vedi rda3563270716 del fornitore", "3563270716"),
        ("5100004438", "5100004438"),
        ("Gestito da terzi", None),
        ("5800005402", None),  # 10 cifre ma non 51…: non è una RDA
        ("", None),
    ],
)
def test_rda_dalla_nota(nota, rda):
    assert n.rda_da_nota(nota) == rda
