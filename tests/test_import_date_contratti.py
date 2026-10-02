"""F8: date di emissione da un'estrazione SAP; solo le date vuote, discordanze segnalate."""

import datetime
import io

import openpyxl
import pytest
from django.core.management import CommandError, call_command

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


def _esegui(file, *opzioni):
    out = io.StringIO()
    call_command("import_date_contratti", str(file), *opzioni, stdout=out)
    return out.getvalue()


@pytest.fixture
def contratti():
    return {
        "vuoto": f.contratto(numero_contratto="5800000001"),
        "uguale": f.contratto(numero_contratto="5800000002", data_emissione=D(2025, 12, 1)),
        "diverso": f.contratto(numero_contratto="5800000003", data_emissione=D(2025, 11, 1)),
    }


def test_compila_solo_le_date_vuote_e_segnala_le_discordanze(tmp_path, contratti):
    file = tmp_path / "date.csv"
    file.write_text(
        "﻿Numero_contratto;Data_emissione\n"
        "5800000001;15/12/2025\n"
        "5800000002;2025-12-01\n"
        "5800000003;01.12.2025\n"
        "5899999999;01/01/2026\n",
        encoding="utf-8",
    )
    out = _esegui(file)
    for c in contratti.values():
        c.refresh_from_db()
    assert contratti["vuoto"].data_emissione == D(2025, 12, 15)
    assert contratti["uguale"].data_emissione == D(2025, 12, 1)
    assert contratti["diverso"].data_emissione == D(2025, 11, 1)  # non toccata
    assert "compilate: 1, già uguali: 1, discordanti: 1, numeri non trovati: 1" in out
    assert "registrata 01/11/2025, nel file 01/12/2025" in out
    motivo = contratti["vuoto"].history.first().history_change_reason
    assert motivo == "Data di emissione da import_date_contratti"
    # Rieseguire non cambia nulla.
    assert "compilate: 0, già uguali: 2" in _esegui(file)


def test_dry_run_non_scrive(tmp_path, contratti):
    file = tmp_path / "date.csv"
    file.write_text("contratto,data\n5800000001,15/12/2025\n", encoding="utf-8")
    assert _esegui(file, "--dry-run").startswith("[dry-run] Date compilate: 1")
    contratti["vuoto"].refresh_from_db()
    assert contratti["vuoto"].data_emissione is None


def test_xlsx_con_numeri_e_date_di_excel(tmp_path, contratti):
    wb = openpyxl.Workbook()
    wb.active.append(["Contratto", "Data emissione"])
    wb.active.append([5800000001, datetime.datetime(2025, 12, 15)])
    file = tmp_path / "date.xlsx"
    wb.save(file)
    _esegui(file)
    contratti["vuoto"].refresh_from_db()
    assert contratti["vuoto"].data_emissione == D(2025, 12, 15)


def test_date_contrastanti_nel_file_non_si_applicano(tmp_path, contratti):
    file = tmp_path / "date.csv"
    file.write_text(
        "numero_contratto;data_emissione\n5800000001;15/12/2025\n5800000001;16/12/2025\n"
        "5800000002;31/02/2025\n",
        encoding="utf-8",
    )
    out = _esegui(file)
    contratti["vuoto"].refresh_from_db()
    assert contratti["vuoto"].data_emissione is None
    assert "date diverse nel file" in out and "data non valida" in out


def test_colonne_mancanti(tmp_path):
    file = tmp_path / "date.csv"
    file.write_text("numero;quando\n1;2\n", encoding="utf-8")
    with pytest.raises(CommandError, match="Colonna mancante: numero_contratto"):
        _esegui(file)
