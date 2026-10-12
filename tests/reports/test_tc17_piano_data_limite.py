"""TC-17 (SPEC §5.4 Rev16): piano ordini per data limite di avvio e recupero dei ritardi."""

import datetime
from decimal import Decimal

import pytest

from contratti import models as m
from reports.piano_ordini import calcola_piano

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def c():
    fab = f.fabbisogno("Servizio di prova", decisione="rinnovare")
    c = f.contratto(
        fabbisogno=fab, data_inizio=D(2026, 3, 1), durata_mesi=12, lead_time_mesi_override=4
    )
    f.piano(f.voce(c, descrizione="Servizio", importo_fisso=Decimal("1200.00")))
    return c


def _righe(anno, oggi):
    return [r for r in calcola_piano(anno, oggi).righe if r.numero_previsto == 1]


def test_a_cavallo_d_anno_conta_la_data_limite(c):
    (r,) = _righe(2026, D(2026, 10, 12))
    assert (r.avvio, r.fine, r.data_limite) == (D(2027, 3, 1), D(2028, 2, 29), D(2026, 10, 31))
    assert not r.in_ritardo
    assert _righe(2027, D(2026, 10, 12)) == []


def test_ritardo_recuperato_solo_nell_anno_in_corso(c):
    oggi = D(2027, 1, 15)
    (r,) = _righe(2027, oggi)
    assert r.in_ritardo and r.data_limite == D(2026, 10, 31)
    (r,) = _righe(2026, oggi)
    assert not r.in_ritardo
    assert _righe(2028, oggi) == []


def test_pratica_conclusa_niente_ritardo(c):
    m.StatoPratica.objects.create(contratto=c, stato="contratto_emesso", data=D(2027, 1, 10))
    assert _righe(2027, D(2027, 1, 15)) == []
