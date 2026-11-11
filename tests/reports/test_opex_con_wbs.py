"""Rev48: una voce OPEX può avere una WBS, ma solo a progetto (fuori dai budget dei cluster)."""

import datetime
from decimal import Decimal

import pytest

from contratti import adapters, forms
from contratti import models as m
from reports.budget import Filtri, calcola_budget

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 6, 1)


def _wbs(codice, tipo):
    return m.WBS.objects.create(
        codice_wbs=codice,
        descrizione=f"WBS {codice}",
        tipo=tipo,
        cluster=f.cluster("IT") if tipo == m.WBS.Tipo.CLUSTER else None,
    )


@pytest.fixture
def wbs_cluster():
    return _wbs("WBS-IT-01", m.WBS.Tipo.CLUSTER)


@pytest.fixture
def wbs_progetto():
    return _wbs("WBS-PRJ-01", m.WBS.Tipo.PROGETTO)


@pytest.fixture
def contratto():
    c = f.contratto(
        fabbisogno=f.fabbisogno("Servizio", decisione="rinnovare"),
        data_inizio=D(2026, 1, 1),
        durata_mesi=12,
    )
    return c


def _form(contratto, wbs, natura="OPEX", **extra):
    return forms.VoceForm(
        {
            "descrizione": "Voce",
            "natura": natura,
            "importo_fisso": "1200,00",
            "massimale_variabile": "0,00",
            "wbs": wbs.pk if wbs else "",
            **extra,
        },
        contratto=contratto,
    )


def test_voce_opex_su_wbs_a_progetto_e_ammessa(contratto, wbs_progetto):
    assert _form(contratto, wbs_progetto).is_valid()


def test_voce_opex_senza_wbs_resta_ammessa(contratto):
    assert _form(contratto, None).is_valid()


def test_voce_opex_su_wbs_di_cluster_e_rifiutata(contratto, wbs_cluster):
    form = _form(contratto, wbs_cluster)
    assert not form.is_valid()
    assert "solo su una WBS a progetto" in form.errors["wbs"][0]


def test_voce_capex_senza_wbs_resta_rifiutata(contratto):
    form = _form(contratto, None, natura="CAPEX")
    assert not form.is_valid()
    assert "CAPEX" in form.errors["wbs"][0]


def test_rinnovi_opex_su_wbs_di_cluster_rifiutati(contratto, wbs_cluster):
    form = _form(contratto, None, natura_rinnovi="OPEX", wbs_rinnovi=wbs_cluster.pk)
    assert not form.is_valid()
    assert "wbs_rinnovi" in form.errors


def test_la_voce_opex_su_progetto_esce_dai_budget_dei_cluster(contratto, wbs_progetto):
    voce = f.voce(
        contratto, importo_fisso=Decimal("1200.00"), natura=m.Natura.OPEX, wbs=wbs_progetto
    )
    f.piano(voce)
    assert adapters.classificazione(voce).a_progetto
    base = calcola_budget(Filtri(anno=2026, natura="OPEX"), OGGI)
    assert not any(v.wbs == wbs_progetto for v in base.voci)
    con = calcola_budget(Filtri(anno=2026, natura="OPEX", progetti="solo"), OGGI)
    assert [v.wbs for v in con.voci] == [wbs_progetto]


def test_il_rinnovo_opex_conserva_la_wbs_a_progetto(contratto, wbs_progetto):
    voce = f.voce(
        contratto, importo_fisso=Decimal("1200.00"), natura=m.Natura.OPEX, wbs=wbs_progetto
    )
    classe = adapters.classificazione_prevista(contratto.fabbisogno, voce)
    assert (classe.natura, classe.wbs) == ("OPEX", wbs_progetto)


def test_il_rinnovo_da_capex_su_wbs_di_cluster_a_opex_perde_la_wbs(contratto, wbs_cluster):
    voce = f.voce(
        contratto,
        importo_fisso=Decimal("5000.00"),
        natura=m.Natura.CAPEX,
        wbs=wbs_cluster,
        natura_rinnovi=m.Natura.OPEX,
    )
    classe = adapters.classificazione_prevista(contratto.fabbisogno, voce)
    assert (classe.natura, classe.wbs) == ("OPEX", None)


def test_wbs_per_natura(wbs_cluster, wbs_progetto):
    assert adapters.wbs_per_natura(m.Natura.CAPEX, wbs_cluster) == wbs_cluster
    assert adapters.wbs_per_natura(m.Natura.OPEX, wbs_progetto) == wbs_progetto
    assert adapters.wbs_per_natura(m.Natura.OPEX, wbs_cluster) is None
    assert adapters.wbs_per_natura(m.Natura.OPEX, None) is None
