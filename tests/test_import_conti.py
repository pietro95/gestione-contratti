"""Comando import_conti: piano dei conti da CSV, idempotente, tutto o niente."""

import datetime

import pytest
from django.core.management import CommandError, call_command

from contratti.models import ContoCoge

pytestmark = pytest.mark.django_db


def _csv(tmp_path, testo, nome="conti.csv"):
    percorso = tmp_path / nome
    percorso.write_text(testo, encoding="utf-8-sig")  # come lo salva Excel
    return percorso


def test_carica_e_aggiorna(tmp_path, capsys):
    f = _csv(
        tmp_path,
        "Codice;Descrizione;Valido_dal;Valido_al\n"
        "600001;Canoni software;01/01/2020;31/12/2025\n"
        "600002;Manutenzioni;2026-01-01;\n",
    )
    call_command("import_conti", str(f))
    assert "creati: 2" in capsys.readouterr().out
    conto = ContoCoge.objects.get(codice="600001")
    assert conto.valido_dal == datetime.date(2020, 1, 1)
    assert conto.valido_al == datetime.date(2025, 12, 31)

    f = _csv(tmp_path, "codice,descrizione,valido_dal\n600002,Manutenzioni HW,01/01/2026\n")
    call_command("import_conti", str(f))
    assert "aggiornati: 1" in capsys.readouterr().out
    assert ContoCoge.objects.get(codice="600002").descrizione == "Manutenzioni HW"
    call_command("import_conti", str(f))
    assert "invariati: 1" in capsys.readouterr().out
    assert ContoCoge.objects.count() == 2


def test_dry_run_non_scrive(tmp_path, capsys):
    f = _csv(tmp_path, "codice;descrizione;valido_dal\n600001;Canoni;01/01/2020\n")
    call_command("import_conti", str(f), "--dry-run")
    assert "[dry-run] Conti creati: 1" in capsys.readouterr().out
    assert not ContoCoge.objects.exists()


@pytest.mark.parametrize(
    ("testo", "messaggio"),
    [
        ("codice;descrizione\n600001;Canoni\n", "Colonne mancanti: valido_dal"),
        ("codice;descrizione;valido_dal\n600001;Canoni;31/02/2020\n", "Riga 2"),
        ("codice;descrizione;valido_dal\n;Canoni;01/01/2020\n", "codice e descrizione"),
    ],
)
def test_errori(tmp_path, testo, messaggio):
    with pytest.raises(CommandError, match=messaggio):
        call_command("import_conti", str(_csv(tmp_path, testo)))


def test_errore_annulla_tutto_il_file(tmp_path):
    f = _csv(tmp_path, "codice;descrizione;valido_dal\n600001;Canoni;01/01/2020\n600002;X;ieri\n")
    with pytest.raises(CommandError):
        call_command("import_conti", str(f))
    assert not ContoCoge.objects.exists()
