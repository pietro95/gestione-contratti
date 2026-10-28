"""Consuntivo a competenza sul database (SPEC §5.2, Rev21): fatture e stanziamenti."""

import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from contratti import fatture
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import Filtri, calcola_budget

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 1)


@pytest.fixture
def scenario(db):
    c = f.contratto(data_inizio=D(2026, 1, 1), durata_mesi=12, numero_contratto="5800000099")
    v = f.voce(c, importo_fisso=Decimal("1000.00"))
    p = f.piano(v, modalita="anticipata", periodicita="annuale")
    r = f.rata(p, data_fattura=D(2026, 1, 1), data_pagamento_stimata=D(2026, 3, 31))
    return {"contratto": c, "voce": v, "rata": r}


def _consuntivo(anno):
    budget = calcola_budget(Filtri(anno=anno, previsionali=False), OGGI)
    return budget.totali()["totale"]["consuntivo"][Livello.FISSO]


def _fattura(c, **kw):
    kw.setdefault("numero", "F1")
    kw.setdefault("data", D(2026, 1, 15))
    kw.setdefault("importo_documento", Decimal("1220.00"))
    return m.Fattura.objects.create(fornitore=c.fornitore, contratto=c, **kw)


def test_senza_fatture_il_consuntivo_e_la_rata(scenario):
    assert _consuntivo(2026) == Decimal("1000.00")


def test_la_fattura_abbinata_alla_rata_conta_per_competenza(scenario):
    c = scenario["contratto"]
    fa = _fattura(c, valore_base=Decimal("1000.00"), rata=scenario["rata"])
    fa.competenza_dal, fa.competenza_al = D(2025, 7, 1), D(2026, 6, 30)
    fa.save()
    assert _consuntivo(2025) == Decimal("500.00")  # 6 mesi su 12
    assert _consuntivo(2026) == Decimal("500.00")
    # La cassa continua a leggere la data fattura della rata.
    budget = calcola_budget(Filtri(anno=2026, previsionali=False), OGGI)
    assert budget.totali()["totale"]["cassa"][Livello.FISSO] == Decimal("1000.00")


def test_fattura_senza_valore_base_non_conta(scenario):
    _fattura(scenario["contratto"], rata=scenario["rata"])
    assert _consuntivo(2026) == Decimal("1000.00")  # resta la previsione della rata


def test_fattura_senza_competenza_va_all_anno_della_data(scenario):
    fa = _fattura(scenario["contratto"], valore_base=Decimal("900.00"), rata=scenario["rata"])
    assert _consuntivo(2026) == Decimal("900.00")
    assert "COMPETENZA_MANCANTE" in fatture.anomalie(fa)
    budget = calcola_budget(Filtri(anno=2026, previsionali=False), OGGI)
    assert any("senza periodo di competenza" in messaggio for messaggio in budget.avvisi)


def test_stanziamento_sostituisce_la_rata_finche_non_arriva_la_fattura(scenario):
    s = m.Stanziamento.objects.create(
        voce=scenario["voce"], rata=scenario["rata"], importo=Decimal("800.00"),
        competenza_dal=D(2026, 1, 1), competenza_al=D(2026, 12, 31),
    )  # fmt: skip
    assert _consuntivo(2026) == Decimal("800.00")
    assert not s.chiuso
    # Arriva la fattura sulla stessa rata: lo stanziamento si chiude da solo.
    _fattura(
        scenario["contratto"], valore_base=Decimal("950.00"), rata=scenario["rata"],
        competenza_dal=D(2026, 1, 1), competenza_al=D(2026, 12, 31),
    )  # fmt: skip
    s = m.Stanziamento.objects.get(pk=s.pk)
    assert s.chiuso
    assert _consuntivo(2026) == Decimal("950.00")


def test_stanziamento_chiuso_con_la_fattura_o_annullato_esce_dal_budget(scenario):
    c = scenario["contratto"]
    s = m.Stanziamento.objects.create(
        voce=scenario["voce"], importo=Decimal("300.00"),
        competenza_dal=D(2026, 5, 1), competenza_al=D(2026, 5, 31),
    )  # fmt: skip
    assert _consuntivo(2026) == Decimal("1300.00")  # sommato alla rata non abbinata
    s.fattura = _fattura(c)
    s.save()
    assert _consuntivo(2026) == Decimal("1000.00")
    s.fattura = None
    s.archiviato = True
    s.save()
    assert _consuntivo(2026) == Decimal("1000.00")


def test_vincoli_della_competenza(scenario):
    c = scenario["contratto"]
    with pytest.raises(IntegrityError), transaction.atomic():
        _fattura(c, competenza_dal=D(2026, 6, 1))  # manca la fine
    with pytest.raises(IntegrityError), transaction.atomic():
        m.Stanziamento.objects.create(
            voce=scenario["voce"], importo=Decimal("1.00"),
            competenza_dal=D(2026, 6, 2), competenza_al=D(2026, 6, 1),
        )  # fmt: skip
