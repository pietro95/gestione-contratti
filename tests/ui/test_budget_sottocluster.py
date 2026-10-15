"""Budget assegnato al sottocluster: filtro nel budget e box con assegnato e residuo."""

import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from contratti import models as m
from reports.budget import Filtri, calcola_budget

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 1)


@pytest.fixture
def sotto(db):
    it = f.cluster("IT")
    reti = m.Sottocluster.objects.create(cluster=it, nome="Reti")
    server = m.Sottocluster.objects.create(cluster=it, nome="Server")
    for nome, sc, fisso in (("Rete A", reti, "10000.00"), ("Server B", server, "4000.00")):
        fab = f.fabbisogno(nome, cluster=it, sottocluster=sc, decisione="dismettere")
        c = f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12)
        f.piano(
            f.voce(c, importo_fisso=Decimal(fisso)), modalita="anticipata", periodicita="annuale"
        )
    return {"reti": reti, "server": server}


def _totale(sc):
    b = calcola_budget(Filtri(anno=2026, sottocluster=sc.pk, natura="OPEX"), OGGI)
    return b.di_natura("OPEX").totali()["totale"]["impegno"]


def test_filtro_sottocluster_partiziona_il_budget(sotto):
    tutto = calcola_budget(Filtri(anno=2026, natura="OPEX"), OGGI).totali()["totale"]["impegno"]
    somma = {liv: _totale(sotto["reti"])[liv] + _totale(sotto["server"])[liv] for liv in tutto}
    assert somma == tutto
    assert _totale(sotto["reti"]) != _totale(sotto["server"])


def test_unico_per_sottocluster_anno_natura(sotto):
    m.BudgetSottocluster.objects.create(
        sottocluster=sotto["reti"], anno=2026, natura="OPEX", importo=Decimal("1.00")
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        m.BudgetSottocluster.objects.create(
            sottocluster=sotto["reti"], anno=2026, natura="OPEX", importo=Decimal("2.00")
        )


def test_box_assegnato_e_residuo(reader, sotto):
    m.BudgetSottocluster.objects.create(
        sottocluster=sotto["reti"], anno=2026, natura="OPEX", importo=Decimal("12000.00")
    )
    risposta = reader.get(
        reverse("reports:budget"),
        {"anno": 2026, "natura": "OPEX", "sottocluster": sotto["reti"].pk, "area": "IT"},
    )
    (sezione,) = risposta.context["sezioni"]
    a = sezione["assegnato"]
    assert a["importo"] == Decimal("12000.00")
    assert a["residuo"] == a["importo"] - a["speso"]
    html = risposta.content.decode()
    assert 'id="assegnato-OPEX"' in html and "12.000,00 €" in html


def test_box_non_assegnato_e_senza_filtro(reader, sotto):
    url = reverse("reports:budget")
    r = reader.get(url, {"anno": 2026, "natura": "OPEX", "sottocluster": sotto["server"].pk})
    assert r.context["sezioni"][0]["assegnato"]["importo"] is None
    assert "Non assegnato" in r.content.decode()
    r = reader.get(url, {"anno": 2026, "natura": "OPEX"})
    assert r.context["sezioni"][0]["assegnato"] is None
    assert 'id="assegnato-' not in r.content.decode()


def test_box_nascosto_fuori_dai_cluster_filtrati(reader, sotto):
    f.cluster("TLC")
    r = reader.get(
        reverse("reports:budget"),
        {"anno": 2026, "natura": "OPEX", "sottocluster": sotto["reti"].pk, "area": "TLC"},
    )
    assert r.context["sezioni"][0]["assegnato"] is None


def test_assegnato_archiviato_e_altro_anno_ignorati(sotto):
    from reports.budget import budget_assegnato

    m.BudgetSottocluster.objects.create(
        sottocluster=sotto["reti"],
        anno=2026,
        natura="OPEX",
        importo=Decimal("5.00"),
        archiviato=True,
    )
    m.BudgetSottocluster.objects.create(
        sottocluster=sotto["reti"], anno=2027, natura="OPEX", importo=Decimal("7.00")
    )
    assert budget_assegnato(Filtri(anno=2026, sottocluster=sotto["reti"].pk)) == {
        "OPEX": None,
        "CAPEX": None,
    }
