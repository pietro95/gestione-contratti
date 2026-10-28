"""Budget e voci a SAL (SPEC §5.2, Rev29): niente pro-rata come fatturato, residuo visibile."""

import datetime
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounts.roles import READER
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import Filtri, calcola_budget

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 27)
PASSWORD = "password-locale-di-prova"


def _sal(importo="10000.00", mesi=12, decisione="da_valutare"):
    c = f.contratto(
        fabbisogno=f.fabbisogno("Lavori", decisione=decisione),
        data_inizio=D(2026, 1, 1),
        durata_mesi=mesi,
    )
    voce = f.voce(c, descrizione="Lavori", importo_fisso=Decimal(importo))
    f.piano(voce, modalita="sal", periodicita="")
    return c, voce


def _totale(b, vista, livello=Livello.FISSO, parte="totale"):
    return b.totali()[parte][vista][livello]


def test_sal_senza_niente_e_fuori_dai_totali_ma_visibile():
    _sal()
    b = calcola_budget(Filtri(anno=2026, previsionali=False), OGGI)
    assert _totale(b, "cassa") == 0 and _totale(b, "consuntivo") == 0
    assert _totale(b, "competenza") == Decimal("10000.00")  # la competenza resta a mesi frazionati
    (x,) = b.sal_non_pianificati
    assert x.importo == Decimal("10000.00")
    assert b.sal_non_pianificato == Decimal("10000.00")
    assert any("SAL non pianificato" in a for a in b.avvisi) or not b.voci


def test_sal_con_quote_entra_nei_totali_e_non_e_non_pianificato():
    _, voce = _sal()
    m.QuotaPeriodo.objects.create(
        voce=voce, dal=D(2026, 1, 1), al=D(2026, 12, 31), importo=Decimal("10000.00")
    )
    b = calcola_budget(Filtri(anno=2026, previsionali=False), OGGI)
    assert _totale(b, "cassa") == Decimal("10000.00")
    assert b.sal_non_pianificati == []


def test_sal_con_fatture_conta_le_fatture_e_il_resto_e_non_pianificato():
    c, _ = _sal()
    m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, numero="F-1", data=D(2026, 5, 4),
        importo_documento=Decimal("3660.00"), valore_base=Decimal("3000.00"),
        competenza_dal=D(2026, 4, 1), competenza_al=D(2026, 4, 30),
    )  # fmt: skip
    b = calcola_budget(Filtri(anno=2026, previsionali=False), OGGI)
    assert _totale(b, "cassa") == Decimal("3000.00")
    assert _totale(b, "consuntivo") == Decimal("3000.00")
    assert b.sal_non_pianificato == Decimal("7000.00")


def test_sal_non_pianificato_solo_per_gli_anni_del_servizio():
    _sal()
    assert calcola_budget(Filtri(anno=2025, previsionali=False), OGGI).sal_non_pianificati == []
    assert calcola_budget(Filtri(anno=2027, previsionali=False), OGGI).sal_non_pianificati == []


def test_il_rinnovo_previsto_di_un_sal_resta_a_pro_rata_dichiarato():
    _sal(decisione="rinnovare")
    b = calcola_budget(Filtri(anno=2027), OGGI)
    previsionale = _totale(b, "cassa", Livello.PROBABILE, "previsionale")
    assert previsionale > 0  # prima come dopo la Rev29: la previsione è a mesi frazionati
    assert any("mesi frazionati" in a.lower() for a in b.avvisi)
    assert b.sal_non_pianificati == []  # i previsti non hanno fatture, quote né rate


def test_pagina_budget_mostra_il_sal_non_pianificato(make_user):
    _sal()
    make_user("u_lettore", role=READER)
    client = Client()
    client.login(username="u_lettore", password=PASSWORD)
    html = client.get(reverse("reports:budget") + "?anno=2026").content.decode()
    assert "SAL non pianificato" in html and "10.000,00" in html
    assert "fuori dai totali" in html
