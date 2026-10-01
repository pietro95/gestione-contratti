"""Viste dei report (F5): lettura per tutti i ruoli, export XLSX coerente con la pagina."""

import datetime
import io
from decimal import Decimal

import openpyxl
import pytest
from django.urls import reverse

from contratti.engine.tipi import Livello
from reports.budget import LIVELLI, VISTE, Filtri, calcola_budget
from reports.piano_ordini import calcola_piano
from reports.xlsx import TIPO_XLSX

pytestmark = pytest.mark.django_db
OGGI = datetime.date.today()


@pytest.mark.parametrize("nome", ["reports:budget", "reports:piano_ordini"])
def test_anonimo_va_al_login(client, nome):
    risposta = client.get(reverse(nome))
    assert risposta.status_code == 302
    assert reverse("accounts:login") in risposta["Location"]


@pytest.mark.parametrize("nome", ["reports:budget", "reports:piano_ordini"])
def test_reader_vede_i_report(reader, dati, nome):
    assert reader.get(reverse(nome)).status_code == 200
    xlsx = reader.get(reverse(nome), {"formato": "xlsx"})
    assert xlsx.status_code == 200
    assert xlsx["Content-Type"] == TIPO_XLSX


def test_pagina_budget(reader, dati):
    html = reader.get(
        reverse("reports:budget"), {"anno": 2026, "per": "fornitore"}
    ).content.decode()
    assert "Budget 2026" in html and "IVA esclusa" in html
    assert "10.000,00 €" in html  # impegno, cassa e competenza del contratto annuale
    assert str(dati["fornitore"]) in html


def test_anno_non_valido(reader, dati):
    risposta = reader.get(reverse("reports:budget"), {"anno": "duemila"})
    assert risposta.status_code == 200
    assert "budget" not in risposta.context or risposta.context.get("budget") is None


def _righe(foglio, da=7):
    return list(foglio.iter_rows(min_row=da, values_only=True))


def test_export_budget_coincide_con_il_calcolo(reader, dati):
    risposta = reader.get(reverse("reports:budget"), {"anno": 2027, "formato": "xlsx"})
    assert "_Budget_2027.xlsx" in risposta["Content-Disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(risposta.content))
    assert wb.sheetnames[:3] == ["Riepilogo", "Per conto", "Dettaglio voci"]
    totali = calcola_budget(Filtri(anno=2027), OGGI).totali()
    attese = [
        (
            vista,
            livello.value,
            *[totali[p][vista][livello] for p in ("consolidato", "previsionale", "totale")],
        )
        for vista in VISTE
        for livello in LIVELLI
    ]
    lette = _righe(wb["Riepilogo"])
    assert len(lette) == len(attese)
    for letta, attesa in zip(lette, attese, strict=True):
        assert [Decimal(str(x)) for x in letta[2:]] == list(attesa[2:])
    # Rinnovo 2027 (10.000) + previsto manuale (5.000).
    assert totali["previsionale"]["impegno"][Livello.FISSO] == Decimal("15000.00")


def test_export_piano_ordini(reader, dati):
    risposta = reader.get(reverse("reports:piano_ordini"), {"anno": 2027, "formato": "xlsx"})
    wb = openpyxl.load_workbook(io.BytesIO(risposta.content))
    righe = _righe(wb["Piano ordini"])
    piano = calcola_piano(2027, OGGI)
    assert len(righe) == len(piano.righe) + 1
    totale = righe[-1]
    assert totale[0] == "Totale"
    assert [Decimal(str(x)) for x in totale[11:14]] == [piano.totali()[liv] for liv in LIVELLI]
    assert isinstance(righe[0][6], datetime.datetime)  # date come date, non testo
