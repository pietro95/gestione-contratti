import datetime
from pathlib import Path

import openpyxl
import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"
IT = FIXTURES / "contratti_it_sample.xlsx"
TLC = FIXTURES / "contratti_tlc_sample.xlsx"
OGGI = datetime.date(2026, 10, 1)

INTESTAZIONE = [
    "Contratto", "Cig", "Nuovo codice conto da 01/01/26", "Codice conto", "Descrizione",
    "Fornitore", "Codice fornitore", "Corrispettivo Minimo", "Corrispettivo Extra",
    "Corrispettivo Massimo", "Data di attivazione", "Mesi contratto", "Data di scadenza",
    "Periodo rinnovo", "Alert", "Stato", "Note",
]  # fmt: skip


@pytest.fixture
def excel(tmp_path):
    """Costruisce un Excel minimo nello stesso formato dei file reali (dati fittizi)."""

    def _crea(righe, fornitori=(("Fornitore Prova S.r.l.", "900001"),), nome="prova.xlsx"):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Contratti"
        ws.append(INTESTAZIONE)
        for r in righe:
            riga = dict.fromkeys(INTESTAZIONE)
            riga["Corrispettivo Massimo"] = "=H2+I2"
            riga.update(r)
            ws.append([riga[c] for c in INTESTAZIONE])
        ws.append(["Totale"])
        wf = wb.create_sheet("Fornitori")
        wf.append(["Fornitore", "Codice SAP"])
        for f in fornitori:
            wf.append(list(f))
        percorso = tmp_path / nome
        wb.save(percorso)
        return percorso

    return _crea


def riga(**kw):
    base = {
        "Contratto": "5800000001",
        "Cig": "Z000000001",
        "Codice conto": "600001",
        "Descrizione": "Canone di prova",
        "Fornitore": "Fornitore Prova S.r.l.",
        "Corrispettivo Minimo": 1000.0,
        "Corrispettivo Extra": 0,
        "Data di attivazione": datetime.datetime(2026, 1, 1),
        "Mesi contratto": 12,
        "Stato": "Attivo",
    }
    base.update(kw)
    return base
