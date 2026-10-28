"""Budget a mesi frazionati (SPEC §5.2, Rev31, TC-24): caso DPO sul database e report d'impatto."""

import datetime
import io
from decimal import Decimal

import openpyxl
import pytest
from django.core.management import call_command

from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import Filtri, calcola_budget
from reports.impatto_competenza import impatto

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 28)
CANONE = Decimal("6500.00")


@pytest.fixture
def dpo():
    """Due contratti contigui da 12 mesi con lo stesso canone, a cavallo di un anno bisestile."""
    fab = f.fabbisogno("Servizio DPO", decisione="dismettere")
    for inizio in (D(2026, 6, 8), D(2027, 6, 8)):
        c = f.contratto(fabbisogno=fab, data_inizio=inizio, durata_mesi=12)
        f.piano(f.voce(c, importo_fisso=CANONE), modalita="anticipata", periodicita="annuale")
    return fab


def _totale(anno, vista, livello=Livello.FISSO):
    b = calcola_budget(Filtri(anno=anno, previsionali=False), OGGI)
    return b.totali()["totale"][vista][livello]


def test_il_budget_2027_somma_il_canone_in_ogni_vista_a_competenza(dpo):
    assert _totale(2027, "competenza") == CANONE
    assert _totale(2027, "consuntivo") == CANONE
    assert _totale(2026, "competenza") == Decimal("3665.28")
    assert _totale(2028, "competenza") == Decimal("2834.72")


def test_fatturato_e_ordinato_non_cambiano(dpo):
    # Le rate annuali anticipate si fatturano all'avvio, l'ordine è nell'anno di emissione.
    assert _totale(2026, "cassa") == CANONE
    assert _totale(2027, "cassa") == CANONE
    assert _totale(2028, "cassa") == Decimal("0.00")


def test_impatto_prima_e_dopo(dpo):
    r = impatto(2027, m.Natura.OPEX, Livello.FISSO, OGGI)
    # Prima, a giorni: 6.500,00 × 208/365 + 6.500,00 × 157/366 = 2.813,70 + 3.676,23.
    assert r.totale("prima", "competenza") == Decimal("6489.93")
    assert r.totale("dopo", "competenza") == CANONE
    assert r.totale("prima", "cassa") == r.totale("dopo", "cassa") == CANONE
    assert r.totale("prima", "impegno") == r.totale("dopo", "impegno")
    (prima, seconda) = sorted(r.piu_cambiate("competenza"), key=lambda v: v.inizio)
    assert (prima.prima["competenza"], prima.dopo["competenza"]) == (
        Decimal("2813.70"),
        Decimal("2834.72"),
    )
    assert (seconda.prima["competenza"], seconda.dopo["competenza"]) == (
        Decimal("3676.23"),
        Decimal("3665.28"),
    )


def test_il_comando_non_modifica_i_dati_e_scrive_l_xlsx(dpo, tmp_path, capsys):
    voci = m.VoceContratto.objects.count()
    percorso = tmp_path / "impatto.xlsx"
    call_command("impatto_competenza", anno=2027, natura="OPEX", livello="fisso", output=percorso)
    assert m.VoceContratto.objects.count() == voci
    uscita = capsys.readouterr().out
    assert "6.489,93" in uscita and "6.500,00" in uscita
    wb = openpyxl.load_workbook(io.BytesIO(percorso.read_bytes()))
    assert wb.sheetnames == ["Per conto", "Voci competenza", "Voci consuntivo"]
