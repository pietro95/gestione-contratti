"""Budget assegnato per conto e stato (SPEC §5.2, Rev34): pagina, export e connettore MCP."""

import datetime
import io
from decimal import Decimal

import openpyxl
import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from contratti import models as m
from reports.budget import Filtri, assegnati_per_conto, assegnati_per_wbs

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 1)


def _gruppi(risposta):
    (sezione,) = risposta.context["sezioni"]
    return {g["etichetta"].split()[0]: g["confronto"] for g in sezione["gruppi"]}


def test_stato_per_conto_in_pagina(reader, conti_assegnati):
    r = reader.get(reverse("reports:budget"), {"anno": 2026, "natura": "OPEX"})
    c = _gruppi(r)
    assert {k: v.stato.value for k, v in c.items()} == {
        "C-OK": "ok",
        "C-AVV": "in_avvicinamento",
        "C-SUP": "superato",
        "C-NO": "non_assegnato",
    }
    assert c["C-AVV"].assegnato == Decimal("10500.00")
    assert c["C-AVV"].speso == Decimal("10000.00")
    assert c["C-NO"].assegnato is None
    html = r.content.decode()
    assert "Budget assegnato" in html and "In avvicinamento" in html and "Superato" in html


def test_assegnato_per_conto_segue_cluster_e_sottocluster(conti_assegnati):
    altro = m.Sottocluster.objects.create(cluster=f.cluster("TLC"), nome="Altro")
    m.BudgetConto.objects.create(
        sottocluster=altro,
        conto=conti_assegnati["conti"]["C-OK"],
        anno=2026,
        importo=Decimal("5.00"),
    )
    base = {"anno": 2026, "natura": "OPEX"}
    assert assegnati_per_conto(Filtri(**base))["C-OK"] == Decimal("20005.00")
    assert assegnati_per_conto(Filtri(**base, area=("IT",)))["C-OK"] == Decimal("20000.00")
    assert assegnati_per_conto(Filtri(**base, sottocluster=altro.pk)) == {"C-OK": Decimal("5.00")}


def test_archiviato_e_altro_anno_ignorati(conti_assegnati):
    c = conti_assegnati["conti"]["C-OK"]
    sc = conti_assegnati["sc"]
    m.BudgetConto.objects.filter(conto=c).update(archiviato=True)
    m.BudgetConto.objects.create(sottocluster=sc, conto=c, anno=2027, importo=1)
    assert "C-OK" not in assegnati_per_conto(Filtri(anno=2026, natura="OPEX"))


def test_unico_per_sottocluster_conto_anno(conti_assegnati):
    with pytest.raises(IntegrityError), transaction.atomic():
        m.BudgetConto.objects.create(
            sottocluster=conti_assegnati["sc"],
            conto=conti_assegnati["conti"]["C-OK"],
            anno=2026,
            importo=Decimal("1.00"),
        )


def test_la_soglia_e_in_tabella_di_configurazione(reader, conti_assegnati):
    # Valore iniziale 90%; con 105% il conto a 10.000 su 10.500 (95,2%) torna «ok».
    m.Parametro.objects.create(
        chiave=m.Parametro.Chiave.BUDGET_SOGLIA_AVVICINAMENTO,
        valore=Decimal("99"),
        valido_dal=D(2026, 1, 1),
    )
    r = reader.get(reverse("reports:budget"), {"anno": 2026, "natura": "OPEX"})
    assert _gruppi(r)["C-AVV"].stato.value == "ok"


def test_senza_colonna_se_non_si_raggruppa_per_conto(reader, conti_assegnati):
    r = reader.get(reverse("reports:budget"), {"anno": 2026, "natura": "OPEX", "per": "fornitore"})
    assert r.context["sezioni"][0]["con_confronto"] is False
    assert "Budget assegnato" not in r.content.decode()


def test_export_xlsx_ha_assegnato_e_stato(reader, conti_assegnati):
    r = reader.get(reverse("reports:budget"), {"anno": 2026, "natura": "OPEX", "formato": "xlsx"})
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    foglio = wb["Per conto"]
    righe = list(foglio.iter_rows(min_row=6, values_only=True))
    intestazione = righe[0]
    assert intestazione[-3:] == ("Budget assegnato (conto OPEX, WBS CAPEX)", "Stato", "Utilizzo %")
    per_conto = {riga[1].split()[0]: riga[-3:] for riga in righe[1:] if riga[1]}
    assert per_conto["C-SUP"][1] == "Superato"
    assert per_conto["C-NO"] == (None, "Non assegnato", None)
    assert Decimal(str(per_conto["C-AVV"][0])) == Decimal("10500.00")


def test_pdf_ha_assegnato_e_stato(reader, conti_assegnati):
    r = reader.get(reverse("reports:budget"), {"anno": 2026, "natura": "OPEX", "formato": "pdf"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def _gruppi_wbs(risposta):
    (sezione,) = risposta.context["sezioni"]
    return sezione, {g["etichetta"].split()[0]: g["confronto"] for g in sezione["gruppi"]}


def test_capex_assegnato_sulla_wbs_non_sul_conto(reader, conti_assegnati):
    """Le spese CAPEX gravano sulla WBS: due voci su conti diversi sommano sulla stessa WBS."""
    r = reader.get(reverse("reports:budget"), {"anno": 2026, "natura": "CAPEX"})
    sezione, c = _gruppi_wbs(r)
    assert sezione["con_confronto"] is True
    assert {k: v.stato.value for k, v in c.items()} == {
        "W-OK": "ok",
        "W-SUP": "superato",
        "W-NO": "non_assegnato",
    }
    assert c["W-OK"].speso == Decimal("20000.00")  # 10.000 + 10.000, conti diversi
    assert c["W-OK"].assegnato == Decimal("25000.00")
    assert c["W-OK"].percentuale == Decimal("80.0")
    # I conti sotto la WBS non hanno confronto, né l'assegnato per conto conta sul CAPEX.
    assert all(len(sotto) == 2 for g in sezione["gruppi"] for sotto in g["sotto"])
    assert assegnati_per_conto(Filtri(anno=2026, natura="CAPEX")) == {}


def test_assegnati_per_wbs_per_cluster_sottocluster_e_natura(conti_assegnati):
    altro = m.Sottocluster.objects.create(cluster=f.cluster("TLC"), nome="Altro")
    m.BudgetWBS.objects.create(
        sottocluster=altro, wbs=conti_assegnati["wbs"]["W-OK"], anno=2026, importo=Decimal("1.00")
    )
    base = {"anno": 2026, "natura": "CAPEX"}
    assert assegnati_per_wbs(Filtri(**base))["W-OK"] == Decimal("25001.00")
    assert assegnati_per_wbs(Filtri(**base, area=("IT",)))["W-OK"] == Decimal("25000.00")
    assert assegnati_per_wbs(Filtri(**base, sottocluster=altro.pk)) == {"W-OK": Decimal("1.00")}
    assert assegnati_per_wbs(Filtri(anno=2026, natura="OPEX")) == {}


def test_nessun_confronto_per_gruppi_diversi_da_conto_opex_e_wbs_capex(reader, conti_assegnati):
    url = reverse("reports:budget")
    r = reader.get(url, {"anno": 2026, "natura": "OPEX", "per": "wbs"})
    assert r.context["sezioni"][0]["con_confronto"] is False
    r = reader.get(url, {"anno": 2026, "natura": "CAPEX", "per": "conto"})
    assert r.context["sezioni"][0]["con_confronto"] is False
    assert "Budget assegnato" not in r.content.decode()


def test_unico_per_sottocluster_wbs_anno(conti_assegnati):
    with pytest.raises(IntegrityError), transaction.atomic():
        m.BudgetWBS.objects.create(
            sottocluster=conti_assegnati["sc"],
            wbs=conti_assegnati["wbs"]["W-OK"],
            anno=2026,
            importo=Decimal("1.00"),
        )


def test_export_xlsx_capex_per_wbs_con_assegnato_e_stato(reader, conti_assegnati):
    r = reader.get(reverse("reports:budget"), {"anno": 2026, "natura": "CAPEX", "formato": "xlsx"})
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    righe = list(wb["Per wbs"].iter_rows(min_row=6, values_only=True))
    per_wbs = {riga[1].split()[0]: riga[-3:] for riga in righe[1:] if riga[1]}
    assert per_wbs["W-SUP"][1] == "Superato"
    assert per_wbs["W-OK"][1] == "OK" and Decimal(str(per_wbs["W-OK"][0])) == Decimal("25000.00")
    assert per_wbs["W-NO"] == (None, "Non assegnato", None)
    # Nel foglio per WBS e conto non c'è nessun assegnato: grava sulla WBS.
    intestazione = next(
        wb["CAPEX per WBS e conto"].iter_rows(min_row=6, max_row=6, values_only=True)
    )
    assert "Stato" not in intestazione
