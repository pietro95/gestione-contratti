"""TC-17 (SPEC §5.4 Rev16-17): piano ordini da avviare, da concludere e ritardi."""

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


def _p1(anno, oggi):
    piano = calcola_piano(anno, oggi)
    righe = [r for r in piano.righe if r.numero_previsto == 1]
    return piano, (righe[0] if righe else None)


def _pratica(c, stato, data):
    m.StatoPratica.objects.create(contratto=c, stato=stato, data=data)


def test_da_avviare_nell_anno_della_data_limite(c):
    piano, r = _p1(2026, D(2026, 10, 12))
    assert (r.avvio, r.fine, r.data_limite) == (D(2027, 3, 1), D(2028, 2, 29), D(2026, 10, 31))
    assert r.da_avviare and not r.in_ritardo
    assert piano.totali()[Livello.FISSO] >= Decimal("1200.00")


def test_da_concludere_fuori_dai_totali(c):
    piano, r = _p1(2027, D(2026, 10, 12))
    assert r.fase == "da_concludere" and not r.in_ritardo
    assert r not in piano.da_avviare
    assert piano.totali()[Livello.FISSO] == sum(
        (x.importi[Livello.FISSO] for x in piano.da_avviare), Decimal("0")
    )


def test_ritardo_con_pratica_non_avviata(c):
    _, r = _p1(2027, D(2027, 1, 15))
    assert r.fase == "da_concludere" and r.in_ritardo
    _pratica(c, "offerta_richiesta", D(2027, 1, 10))
    _, r = _p1(2027, D(2027, 1, 15))
    assert r.fase == "da_concludere" and not r.in_ritardo


def test_pratica_conclusa_toglie_la_riga(c):
    _pratica(c, "contratto_emesso", D(2027, 1, 10))
    assert _p1(2027, D(2027, 1, 15))[1] is None


def test_servizio_gia_partito(c):
    _pratica(c, "offerta_ricevuta", D(2027, 2, 1))
    _, r = _p1(2027, D(2027, 4, 15))
    assert r.fase == "da_concludere" and r.in_ritardo
    assert _p1(2028, D(2027, 4, 15))[1] is None
