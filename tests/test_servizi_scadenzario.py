"""Generazione e salvataggio dello scadenzario (rate generate, poi modificabili a mano)."""

import datetime
from decimal import Decimal

import pytest

from contratti import models as m
from contratti.servizi import ScadenzarioBloccato, genera_scadenzario

from . import factories as f

pytestmark = pytest.mark.django_db

D = datetime.date


@pytest.fixture
def voce_tc03():
    c = f.contratto(data_inizio=D(2026, 7, 1), durata_mesi=24)
    v = f.voce(c, importo_fisso=Decimal("24000.00"))
    f.piano(v, modalita="posticipata", periodicita="trimestrale")
    return v


def test_genera_e_salva_le_rate_tc03(voce_tc03):
    rate = genera_scadenzario(voce_tc03)
    salvate = list(m.Rata.objects.filter(piano__voce=voce_tc03).order_by("numero"))
    assert len(rate) == len(salvate) == 8
    assert [r.data_fattura for r in salvate][:2] == [D(2026, 9, 30), D(2026, 12, 31)]
    # Pagamento d.f.f.m. di default: fine del mese di (fattura + 60 gg).
    assert [r.data_pagamento_stimata for r in salvate][:2] == [D(2026, 11, 30), D(2027, 3, 31)]
    assert all(r.importo == Decimal("3000.00") for r in salvate)
    assert not any(r.modificata_manualmente for r in salvate)


def test_rigenerazione_sostituisce_le_rate(voce_tc03):
    genera_scadenzario(voce_tc03)
    piano = voce_tc03.piano_fatturazione
    piano.periodicita = "semestrale"
    piano.save()
    genera_scadenzario(voce_tc03)
    assert m.Rata.objects.filter(piano=piano).count() == 4


@pytest.mark.parametrize("campo", ["modificata_manualmente", "consuntivo"])
def test_rigenerazione_bloccata(voce_tc03, campo):
    genera_scadenzario(voce_tc03)
    rata = m.Rata.objects.get(piano__voce=voce_tc03, numero=2)
    setattr(rata, campo, True)
    rata.save()
    with pytest.raises(ScadenzarioBloccato, match="2"):
        genera_scadenzario(voce_tc03)
    assert m.Rata.objects.filter(piano__voce=voce_tc03).count() == 8


def test_contratto_senza_data_inizio_non_genera():
    c = f.contratto(data_inizio=None)
    v = f.voce(c)
    f.piano(v)
    with pytest.raises(ScadenzarioBloccato, match="data di inizio mancante"):
        genera_scadenzario(v)


def test_sal_nessuna_rata_generata():
    c = f.contratto(data_inizio=D(2026, 1, 1))
    v = f.voce(c)
    f.piano(v, modalita="sal", periodicita="")
    assert genera_scadenzario(v) == []
