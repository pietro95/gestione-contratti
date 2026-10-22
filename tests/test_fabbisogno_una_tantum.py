"""Fabbisogno una tantum: un solo previsto, nessun rinnovo (SPEC §4, §5.3, Rev27)."""

import datetime
from decimal import Decimal

import pytest

from contratti import adapters, selettori
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import Filtri, calcola_budget
from tests import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 22)


def fabbisogno_nuovo(durata, **kw):
    return f.fabbisogno(
        "Fornitura una tantum",
        decisione=kw.pop("decisione", "da_valutare"),
        stima_prossimo_importo=Decimal("3000.00"),
        previsto_data_avvio=D(2027, 3, 1),
        previsto_durata_mesi=durata,
        previsto_modalita="posticipata",
        previsto_periodicita="intera_durata",
        previsto_procedura=f.procedura(),
        sottocluster=f.sottocluster(),
        **kw,
    )


def previsti(fab):
    return adapters.previsti_fabbisogno(fab, adapters.orizzonte_default(OGGI))


@pytest.mark.parametrize("durata", [1, 12])
def test_senza_il_flag_il_previsto_si_ripete_a_ogni_scadenza(durata):
    assert len(previsti(fabbisogno_nuovo(durata))) > 1  # il difetto che il flag risolve


@pytest.mark.parametrize("durata", [1, 12])
@pytest.mark.parametrize("decisione", ["da_valutare", "rinnovare", "dismettere"])
def test_una_tantum_un_solo_previsto(durata, decisione):
    (p,) = previsti(fabbisogno_nuovo(durata, una_tantum=True, decisione=decisione))
    assert p.inizio == D(2027, 3, 1)
    assert sum((v.importo_fisso for v in p.voci), Decimal("0")) == Decimal("3000.00")


def test_una_tantum_nel_budget_solo_l_anno_dell_acquisto():
    fab = fabbisogno_nuovo(1, una_tantum=True, decisione="dismettere")
    totale = {
        anno: calcola_budget(Filtri(anno=anno, fabbisogno=fab.pk), OGGI).totali()["totale"]
        for anno in (2026, 2027, 2028, 2029)
    }
    importi = {a: t["competenza"][Livello.PROBABILE] for a, t in totale.items()}
    assert importi[2027] == Decimal("3000.00")
    assert importi[2026] == importi[2028] == importi[2029] == 0


def test_una_tantum_registrato_il_contratto_non_resta_il_previsto():
    fab = fabbisogno_nuovo(1, una_tantum=True)
    f.voce(f.contratto(fabbisogno=fab, data_inizio=D(2027, 3, 1), durata_mesi=1))
    assert previsti(fab) == []


def test_una_tantum_con_un_contratto_non_genera_rinnovi():
    fab = f.fabbisogno("Licenze", una_tantum=True, decisione="rinnovare")
    f.voce(f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12))
    assert previsti(fab) == []


def test_alert_del_previsto_anche_con_decisione_dismettere():
    fab = fabbisogno_nuovo(1, una_tantum=True, decisione="dismettere")
    (riga,) = [r for r in selettori.righe_previsti_manuali(OGGI, {}) if r.previsto_manuale == fab]
    assert riga.alert is not None
    altro = fabbisogno_nuovo(1, decisione="dismettere")
    (riga,) = [r for r in selettori.righe_previsti_manuali(OGGI, {}) if r.previsto_manuale == altro]
    assert riga.alert is None  # un fabbisogno da dismettere resta senza alert


def test_stima_complessiva_senza_doppio_conteggio_sul_rinnovo():
    fab = f.fabbisogno("Vigilanza", decisione="rinnovare", stima_prossimo_importo=Decimal("8600"))
    c = f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12)
    v = f.voce(c, importo_fisso=Decimal("5000.00"), massimale_variabile=Decimal("5000.00"))
    m.VoceContratto.objects.filter(pk=v.pk).update(stima_consumo_importo=Decimal("3600.00"))
    f.piano(v, modalita="anticipata", periodicita="annuale")
    primo, *successivi = previsti(fab)
    assert sum((x.importo_fisso for x in primo.voci), Decimal("0")) == Decimal("8600.00")
    for p in [primo, *successivi]:  # il consumo non rientra nemmeno dai rinnovi successivi
        assert all(x.massimale_variabile == 0 for x in p.voci)
