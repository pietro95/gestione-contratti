"""Report di impatto della Rev29: fatturato delle voci a SAL per anno, prima e dopo."""

import datetime
import io
from decimal import Decimal

import openpyxl
import pytest
from django.core.management import CommandError, call_command

from contratti import models as m
from contratti.engine.tipi import Livello
from reports.impatto_sal import righe_impatto

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
FISSO = Decimal("2947639.75")


@pytest.fixture
def archivio_sal():
    """Il caso 230 (quote e sei fatture), un SAL senza niente e una voce non a SAL."""
    wbs = m.WBS.objects.create(codice_wbs="P.0001.01.0001", descrizione="Automazione impianto")
    c = f.contratto(
        fabbisogno=f.fabbisogno("Lavori impianto"),
        data_inizio=D(2024, 10, 15),
        durata_mesi=29,
        data_fine_override=D(2027, 3, 31),
        numero_contratto="5800000230",
    )
    lavori = f.voce(c, descrizione="Lavori", natura="CAPEX", wbs=wbs, importo_fisso=FISSO)
    f.piano(lavori, modalita="sal", periodicita="")
    for anno, importo in ((2025, "1486870.87"), (2026, "1144060.62"), (2027, "316708.26")):
        m.QuotaPeriodo.objects.create(
            voce=lavori, dal=D(anno, 1, 1), al=D(anno, 12, 31), importo=Decimal(importo)
        )
    for i, (data, importo) in enumerate(
        [(D(2025, 2, 20), "1486870.87"), (D(2026, 4, 9), "1144060.62")], start=1
    ):
        m.Fattura.objects.create(
            fornitore=c.fornitore, contratto=c, voce=lavori, numero=f"F-{i}", data=data,
            importo_documento=Decimal(importo), valore_base=Decimal(importo),
        )  # fmt: skip
    vuota = f.voce(c, descrizione="Collaudo", importo_fisso=Decimal("10000.00"))
    f.piano(vuota, modalita="sal", periodicita="")
    canone = f.voce(c, descrizione="Canone", importo_fisso=Decimal("1000.00"))
    f.piano(canone, modalita="posticipata", periodicita="annuale")
    return {"lavori": lavori, "vuota": vuota, "canone": canone}


def test_solo_le_voci_a_sal(archivio_sal):
    righe = righe_impatto(Livello.FISSO)
    assert {r.voce.pk for r in righe} == {archivio_sal["lavori"].pk, archivio_sal["vuota"].pk}


def test_prima_e_il_pro_rata_dopo_fatture_e_quote(archivio_sal):
    righe = {r.voce.pk: r for r in righe_impatto(Livello.FISSO)}
    lavori = righe[archivio_sal["lavori"].pk]
    # Prima: i numeri del report che ha dato origine alla Rev29.
    assert lavori.prima["cassa"] == {
        2024: Decimal("256031.07"),
        2025: Decimal("1198094.11"),
        2026: Decimal("1198094.11"),
        2027: Decimal("295420.46"),
    }
    # Dopo: fatture 2025 e 2026, quota 2027 come previsto.
    assert lavori.dopo["cassa"] == {
        2025: Decimal("1486870.87"),
        2026: Decimal("1144060.62"),
        2027: Decimal("316708.26"),
    }
    assert lavori.delta("cassa", 2024) == Decimal("-256031.07")
    assert lavori.delta("cassa", 2027) == Decimal("21287.80")
    assert (lavori.n_fatture, lavori.fatturato) == (2, Decimal("2630931.49"))
    assert (lavori.n_quote, lavori.somma_quote) == (3, FISSO)
    assert lavori.fonti == "fatture, quote"
    assert lavori.non_pianificato["cassa"] == 0


def test_voce_sal_senza_niente_passa_da_pro_rata_a_non_pianificato(archivio_sal):
    vuota = {r.voce.pk: r for r in righe_impatto(Livello.FISSO)}[archivio_sal["vuota"].pk]
    assert sum(vuota.prima["cassa"].values()) == Decimal("10000.00")
    assert vuota.dopo["cassa"] == {}
    assert vuota.non_pianificato["cassa"] == Decimal("10000.00")
    assert vuota.fonti == "nessuna: tutto non pianificato"
    assert any("SAL non pianificato" in a for a in vuota.avvisi)


def test_comando_scrive_il_report_senza_modificare_i_dati(archivio_sal, tmp_path, capsys):
    prima = {M: M.objects.count() for M in (m.Fattura, m.QuotaPeriodo, m.VoceContratto)}
    percorso = tmp_path / "impatto.xlsx"
    call_command("impatto_sal", output=percorso, livello="fisso")
    assert {M: M.objects.count() for M in prima} == prima
    uscita = capsys.readouterr().out
    assert "Voci a SAL: 2" in uscita and "SAL non pianificato" in uscita
    wb = openpyxl.load_workbook(io.BytesIO(percorso.read_bytes()))
    assert wb.sheetnames == [
        "Totali per anno", "Voci a SAL", "Fatturato per anno", "Consuntivo per anno",
    ]  # fmt: skip
    valori = [c for riga in wb["Voci a SAL"].iter_rows(values_only=True) for c in riga]
    assert "5800000230" in valori and 2947639.75 in valori and 2630931.49 in valori


def test_comando_non_sovrascrive(archivio_sal, tmp_path):
    percorso = tmp_path / "impatto.xlsx"
    percorso.write_bytes(b"x")
    with pytest.raises(CommandError, match="non lo sovrascrivo"):
        call_command("impatto_sal", output=percorso)
