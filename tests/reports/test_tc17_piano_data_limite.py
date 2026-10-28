"""TC-17 (SPEC §5.4 Rev20): piano ordini per anno di avvio, ritardi."""

import datetime
from decimal import Decimal

import pytest

from contratti import models as m
from contratti.engine.tipi import Livello
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


def _p(numero, anno, oggi):
    piano = calcola_piano(anno, oggi)
    righe = [r for r in piano.righe if r.numero_previsto == numero]
    return piano, (righe[0] if righe else None)


def _p1(anno, oggi):
    return _p(1, anno, oggi)


def _pratica(c, stato, data):
    m.StatoPratica.objects.create(contratto=c, stato=stato, data=data)


def test_un_previsto_e_nel_piano_dell_anno_di_avvio(c):
    assert _p1(2026, D(2026, 10, 12))[1] is None  # data limite 2026, ma avvio 2027
    piano, r = _p1(2027, D(2026, 10, 12))
    assert (r.avvio, r.fine, r.data_limite) == (D(2027, 3, 1), D(2028, 2, 29), D(2026, 10, 31))
    assert r.da_avviare and not r.in_ritardo
    assert piano.totali()[Livello.FISSO] >= Decimal("1200.00")


def test_un_solo_contratto_annuale_per_anno(c):
    # P2: avvio 01/03/2028, data limite 31/10/2027. Non è nel piano 2027, solo nel 2028.
    piano, p2 = _p(2, 2027, D(2026, 10, 12))
    assert p2 is None
    assert [r.numero_previsto for r in piano.righe if r.contratto is None] == [1]
    piano, p2 = _p(2, 2028, D(2026, 10, 12))
    assert p2.da_avviare and _p1(2028, D(2026, 10, 12))[1] is None


def test_ritardo_con_pratica_non_avviata(c):
    _, r = _p1(2027, D(2027, 1, 15))
    assert r.da_avviare and r.in_ritardo
    _pratica(c, "offerta_richiesta", D(2027, 1, 10))
    _, r = _p1(2027, D(2027, 1, 15))
    assert r.da_avviare and not r.in_ritardo


def test_ritardo_con_avvio_nell_anno_successivo(c):
    # 15/11/2026: data limite 31/10/2026 passata, pratica non avviata, avvio nel 2027.
    piano, r = _p1(2026, D(2026, 11, 15))
    assert r.fase == "da_concludere" and r.in_ritardo
    assert r not in piano.da_avviare
    assert _p1(2027, D(2026, 11, 15))[1].da_avviare
    _pratica(c, "offerta_richiesta", D(2026, 11, 10))
    assert _p1(2026, D(2026, 11, 15))[1] is None


def test_pratica_conclusa_toglie_la_riga(c):
    _pratica(c, "contratto_emesso", D(2027, 1, 10))
    assert _p1(2027, D(2027, 1, 15))[1] is None


def test_servizio_gia_partito(c):
    _pratica(c, "offerta_ricevuta", D(2027, 2, 1))
    _, r = _p1(2027, D(2027, 4, 15))
    assert r.da_avviare and r.in_ritardo
    assert _p1(2028, D(2027, 4, 15))[1] is None
    # Piano 2028 nel 2028 (anno in corso): P1 è in corso, servizio partito e pratica non conclusa.
    _, r = _p1(2028, D(2028, 1, 15))
    assert r.fase == "da_concludere" and r.in_ritardo
