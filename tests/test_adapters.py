"""Adapter ORM → motore: i casi di TEST_CASES costruiti dal database."""

import datetime
from decimal import Decimal

import pytest

from contratti import adapters
from contratti import models as m
from contratti.engine.budget import calcola
from contratti.engine.tipi import Alert, Livello

from . import factories as f

pytestmark = pytest.mark.django_db

D = datetime.date
E = Decimal


def tc10_contratto():
    c = f.contratto(
        data_inizio=D(2025, 4, 1),
        durata_mesi=12,
        data_emissione=D(2025, 3, 15),
        lead_time_mesi_override=4,
    )
    base = f.voce(c, importo_fisso=E("12000.00"))
    f.piano(base, modalita="anticipata", periodicita="annuale")
    p1 = m.Proroga.objects.create(
        contratto=c, data_atto=D(2026, 2, 10), nuova_data_fine=D(2026, 9, 30)
    )
    p2 = m.Proroga.objects.create(
        contratto=c, data_atto=D(2026, 9, 1), nuova_data_fine=D(2027, 3, 31)
    )
    for proroga, importo in ((p1, "6000.00"), (p2, "6300.00")):
        v = f.voce(c, proroga=proroga, descrizione="Proroga", importo_fisso=E(importo))
        f.piano(v, modalita="una_tantum", periodicita="")
    return c


def test_parametro_con_validita_temporale():
    m.Parametro.objects.create(chiave="adeguamento_pct", valore=E("3"), valido_dal=D(2027, 1, 1))
    assert adapters.parametro("adeguamento_pct", D(2026, 12, 31)) == E("0")
    assert adapters.parametro("adeguamento_pct", D(2027, 1, 1)) == E("3")


def test_parametro_mancante():
    with pytest.raises(adapters.ParametroMancante):
        adapters.parametro("giorni_pagamento", D(1999, 1, 1))


def test_piano_con_default_risolti():
    p = f.piano(modalita="posticipata", periodicita="trimestrale")
    piano = adapters.piano_engine(p, D(2026, 1, 1))
    assert piano.giorni_pagamento == 60
    assert piano.pagamento_fine_mese is True
    p.giorni_pagamento, p.pagamento_fine_mese = 30, False
    piano = adapters.piano_engine(p, D(2026, 1, 1))
    assert (piano.giorni_pagamento, piano.pagamento_fine_mese) == (30, False)


def test_tc10_dal_database():
    c = tc10_contratto()
    assert adapters.data_fine_effettiva(c) == D(2027, 3, 31)
    assert adapters.data_limite_avvio(c) == D(2026, 11, 30)
    voci, esiti = adapters.voci_contratto(c)
    assert esiti == []
    assert [(v.inizio, v.fine, v.anno_impegno) for v in voci] == [
        (D(2025, 4, 1), D(2026, 3, 31), 2025),
        (D(2026, 4, 1), D(2026, 9, 30), 2026),
        (D(2026, 10, 1), D(2027, 3, 31), 2026),
    ]
    viste, _ = calcola(voci)
    assert viste["competenza"].importo(2026) == E("12150.00")
    assert viste["impegno"].importo(2026) == E("12300.00")
    assert viste["cassa"].importo(2026) == E("12300.00")


def test_alert_dal_database():
    c = tc10_contratto()
    c.fabbisogno.decisione = "rinnovare"
    c.fabbisogno.save()
    assert adapters.alert_contratto(c, D(2026, 12, 15)) == Alert.ARANCIONE
    m.StatoPratica.objects.create(contratto=c, stato="rda_predisposta", data=D(2026, 12, 1))
    assert adapters.alert_contratto(c, D(2026, 12, 15)) == Alert.GIALLO
    f.contratto(fabbisogno=c.fabbisogno, predecessore=c, data_inizio=D(2027, 4, 1))
    assert adapters.alert_contratto(c, D(2026, 12, 15)) is None


def test_lead_time_dalla_procedura():
    c = f.contratto(data_inizio=D(2026, 1, 1), durata_mesi=12, procedura=f.procedura("negoziata"))
    assert adapters.data_limite_avvio(c) == D(2026, 6, 30)  # lead time provvisorio 6 mesi


def test_contratto_senza_data_di_inizio_escluso():
    c = f.contratto(data_inizio=None)
    f.voce(c)
    voci, esiti = adapters.voci_contratto(c)
    assert voci == []
    assert [e.codice for e in esiti] == ["DATA_MANCANTE"]
    assert adapters.alert_contratto(c, D(2026, 1, 1)) is None


def test_voci_archiviate_escluse():
    c = f.contratto()
    f.voce(c, archiviato=True)
    assert adapters.voci_contratto(c)[0] == []


def test_rate_salvate_prevalgono():
    c = f.contratto(data_inizio=D(2026, 1, 1))
    v = f.voce(c, importo_fisso=E("1000.00"))
    p = f.piano(v)
    f.rata(
        p, importo=E("1100.00"), data_fattura=D(2026, 2, 1), data_pagamento_stimata=D(2026, 4, 30)
    )
    (voce,), _ = adapters.voci_contratto(c)
    viste, _ = calcola([voce])
    assert viste["cassa"].importo(2026) == E("1100.00")


# --- TC-07 dal database -----------------------------------------------------------------


@pytest.fixture
def tc07():
    m.Parametro.objects.create(chiave="adeguamento_pct", valore=E("3"), valido_dal=D(2026, 1, 1))
    fab = f.fabbisogno(decisione="rinnovare")
    c = f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12)
    f.piano(f.voce(c, importo_fisso=E("10000.00")), modalita="anticipata", periodicita="annuale")
    return fab, c


def test_tc07_previsti_dal_database(tc07):
    fab, _ = tc07
    previsti = adapters.previsti_fabbisogno(fab, D(2028, 12, 31))
    assert [(p.inizio, p.voci[0].importo_fisso) for p in previsti] == [
        (D(2027, 1, 1), E("10300.00")),
        (D(2028, 1, 1), E("10609.00")),
    ]
    viste, _ = calcola(v for p in previsti for v in p.voci)
    assert viste["impegno"].importo(2027) == E("10300.00")


def test_tc07_stima_manuale_dal_database(tc07):
    fab, _ = tc07
    fab.stima_prossimo_importo = E("12000.00")
    fab.save()
    previsti = adapters.previsti_fabbisogno(fab, D(2028, 12, 31))
    assert [p.voci[0].importo_fisso for p in previsti] == [E("12000.00"), E("12360.00")]


def test_tc07_dismettere_dal_database(tc07):
    fab, _ = tc07
    fab.decisione = "dismettere"
    fab.save()
    assert adapters.previsti_fabbisogno(fab, D(2028, 12, 31)) == []


def test_tc07_successore_reale_dal_database(tc07):
    fab, c = tc07
    succ = f.contratto(fabbisogno=fab, predecessore=c, data_inizio=D(2027, 1, 1), durata_mesi=12)
    f.piano(f.voce(succ, importo_fisso=E("11000.00")), modalita="anticipata", periodicita="annuale")
    previsti = adapters.previsti_fabbisogno(fab, D(2028, 12, 31))
    assert [(p.inizio, p.voci[0].importo_fisso) for p in previsti] == [
        (D(2028, 1, 1), E("11330.00"))
    ]


def test_previsti_escludono_le_voci_di_proroga():
    m.Parametro.objects.create(chiave="adeguamento_pct", valore=E("3"), valido_dal=D(2026, 1, 1))
    c = tc10_contratto()
    c.fabbisogno.decisione = "rinnovare"
    c.fabbisogno.save()
    (p1,) = adapters.previsti_fabbisogno(c.fabbisogno, D(2027, 12, 31))
    assert (p1.inizio, p1.fine) == (D(2027, 4, 1), D(2028, 3, 31))
    assert [v.importo_fisso for v in p1.voci] == [E("12360.00")]


def test_previsto_manuale_di_fabbisogno_nuovo():
    fab = f.fabbisogno(
        decisione="rinnovare",
        stima_prossimo_importo=E("8000.00"),
        previsto_data_avvio=D(2027, 7, 1),
        previsto_durata_mesi=12,
        previsto_modalita="anticipata",
        previsto_periodicita="annuale",
    )
    previsti = adapters.previsti_fabbisogno(fab, D(2028, 12, 31))
    assert [(p.numero, p.inizio, p.voci[0].importo_fisso) for p in previsti] == [
        (1, D(2027, 7, 1), E("8000.00")),
        (2, D(2028, 7, 1), E("8000.00")),  # adeguamento provvisorio 0%
    ]
    viste, _ = calcola(v for p in previsti for v in p.voci)
    assert viste["cassa"].totale(Livello.FISSO) == E("16000.00")


def test_orizzonte_default():
    assert adapters.orizzonte_default(D(2026, 10, 1)) == D(2029, 12, 31)


def test_previsti_dal_solo_contratto_terminale_piu_recente(tc07):
    # Contratto vecchio non collegato alla catena (caso da import): non genera previsti.
    fab, _ = tc07
    vecchio = f.contratto(fabbisogno=fab, data_inizio=D(2020, 1, 1), durata_mesi=12)
    f.piano(
        f.voce(vecchio, importo_fisso=E("500.00")), modalita="anticipata", periodicita="annuale"
    )
    previsti = adapters.previsti_fabbisogno(fab, D(2028, 12, 31))
    assert [(p.inizio, p.voci[0].importo_fisso) for p in previsti] == [
        (D(2027, 1, 1), E("10300.00")),
        (D(2028, 1, 1), E("10609.00")),
    ]


def tc11_contratto():
    c = f.contratto(data_inizio=D(2026, 7, 1), durata_mesi=36, data_emissione=D(2026, 6, 1))
    v = f.voce(c, importo_fisso=E("31500.00"))
    f.piano(v, modalita="anticipata", periodicita="annuale")
    for dal, al, importo in (
        (D(2026, 7, 1), D(2027, 6, 30), "10000.00"),
        (D(2027, 7, 1), D(2028, 6, 30), "10500.00"),
        (D(2028, 7, 1), D(2029, 6, 30), "11000.00"),
    ):
        m.QuotaPeriodo.objects.create(voce=v, dal=dal, al=al, importo=E(importo))
    return c


def test_tc11_dal_database():
    voci, _ = adapters.voci_contratto(tc11_contratto())
    viste, esiti = calcola(voci)
    assert esiti == []
    assert [viste["competenza"].importo(a) for a in (2026, 2027, 2028, 2029)] == [
        E("5000.00"),
        E("10250.00"),
        E("10750.00"),
        E("5500.00"),
    ]
    assert viste["cassa"].importo(2027) == E("10500.00")


def test_previsto_riparte_dal_totale_senza_quote():
    c = tc11_contratto()
    c.fabbisogno.decisione = "rinnovare"
    c.fabbisogno.save()
    (p1,) = adapters.previsti_fabbisogno(c.fabbisogno, D(2029, 12, 31))
    assert (p1.inizio, p1.fine) == (D(2029, 7, 1), D(2032, 6, 30))
    assert p1.voci[0].importo_fisso == E("31500.00")  # adeguamento provvisorio 0%
    assert p1.voci[0].quote == ()
