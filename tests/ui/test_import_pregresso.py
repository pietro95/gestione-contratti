"""Rev20: fatturato pregresso (totale per anno) da un foglio CSV o XLSX. Dati di fantasia."""

import io
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command

from contratti import models as m
from contratti.importer.pregresso import importa_pregresso
from contratti.importer.tabelle import FileNonValido

from .. import factories as f

pytestmark = pytest.mark.django_db
D = Decimal


def _esegui(file, *opzioni):
    out = io.StringIO()
    call_command("import_pregresso", str(file), *opzioni, stdout=out)
    return out.getvalue()


@pytest.fixture
def contratti():
    return {
        "a": f.contratto(numero_contratto="5800000001"),
        "b": f.contratto(numero_contratto="5800000002"),
        "doppio1": f.contratto(numero_contratto="5800000009"),
        "doppio2": f.contratto(numero_contratto="5800000009"),
    }


def _csv(tmp_path, righe):
    file = tmp_path / "pregresso.csv"
    file.write_text("numero_contratto;id_contratto;anno;fatturato;nota\n" + righe, encoding="utf-8")
    return file


def test_crea_corregge_e_non_duplica(tmp_path, contratti):
    file = _csv(
        tmp_path,
        "5800000001;;2024;12.000,50;da Excel\n"
        "5800000001;;2025;8000;\n"
        f";{contratti['b'].pk};2024;300,00;per id\n",
    )
    assert "creati: 3" in _esegui(file)
    a = contratti["a"].fatturato_pregresso
    assert a.get(anno=2024).importo == D("12000.50") and a.get(anno=2024).note == "da Excel"
    assert contratti["b"].fatturato_pregresso.get().importo == D("300.00")
    assert "già uguali: 3" in _esegui(file)  # idempotente
    assert m.FatturatoPregresso.objects.count() == 3
    corretto = _csv(tmp_path, "5800000001;;2024;13000;\n")
    assert "corretti: 1" in _esegui(corretto)
    riga = a.get(anno=2024)
    assert riga.importo == D("13000.00") and riga.history.count() == 2


def test_dry_run_non_scrive(tmp_path, contratti):
    out = _esegui(_csv(tmp_path, "5800000001;;2024;100;\n"), "--dry-run")
    assert "[dry-run]" in out and "creati: 1" in out
    assert not m.FatturatoPregresso.objects.exists()


def test_righe_non_applicabili_nel_report(tmp_path, contratti):
    file = _csv(
        tmp_path,
        "5899999999;;2024;100;\n"  # non trovato
        "5800000009;;2024;100;\n"  # su due contratti
        "5800000001;;1850;100;\n"  # anno non valido
        "5800000001;;2024;abc;\n"  # importo non valido
        "5800000001;;2024;-5;\n"  # importo negativo
        "5800000001;;2023;10;\n"  # buona
        "5800000001;;2023;20;\n",  # anno ripetuto
    )
    report = importa_pregresso(file)
    assert report.conteggi["creati"] == 1 and report.conteggi["scartati"] == 6
    assert report.codici() == {
        "CONTRATTO_NON_TROVATO": 1,
        "NUMERO_SU_PIU_CONTRATTI": 1,
        "ANNO_NON_VALIDO": 1,
        "IMPORTO_NON_VALIDO": 2,
        "ANNO_RIPETUTO": 1,
    }
    assert m.FatturatoPregresso.objects.get().importo == D("10.00")


def test_cluster_non_ammesso(tmp_path, contratti):
    file = _csv(tmp_path, "5800000001;;2024;100;\n")
    report = importa_pregresso(file, contratti=m.Contratto.objects.filter(pk=contratti["b"].pk))
    assert report.codici() == {"FUORI_CLUSTER": 1} and not m.FatturatoPregresso.objects.exists()


def test_colonne_mancanti(tmp_path):
    file = tmp_path / "x.csv"
    file.write_text("anno;fatturato\n2024;100\n", encoding="utf-8")
    with pytest.raises(FileNonValido, match="numero_contratto"):
        importa_pregresso(file)
    with pytest.raises(CommandError):
        _esegui(tmp_path / "non_esiste.csv")


def test_dall_interfaccia_con_xlsx(editor, contratti, tmp_path):
    import openpyxl
    from django.core.files.uploadedfile import SimpleUploadedFile

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["numero_contratto", "anno", "fatturato"])
    ws.append(["5800000001", 2024, 4321.5])
    buffer = io.BytesIO()
    wb.save(buffer)
    risposta = editor.post(
        "/import/carica/pregresso/",
        {"pregresso-file": SimpleUploadedFile("pregresso.xlsx", buffer.getvalue())},
    )
    assert risposta.status_code in (200, 302), risposta.content[:300]
    imp = m.Importazione.objects.get(tipo="pregresso")
    assert imp.anteprima["conteggi"]["creati"] == 1
    assert not m.FatturatoPregresso.objects.exists()  # anteprima: nessuna scrittura
    risposta = editor.post(f"/import/{imp.pk}/conferma/")
    assert m.FatturatoPregresso.objects.get().importo == D("4321.50")
