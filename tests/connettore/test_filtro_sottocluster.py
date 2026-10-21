"""Rev25: il parametro «sottocluster» negli strumenti di lettura che filtrano per cluster."""

import datetime
from decimal import Decimal

import pytest

from accounts.roles import ADMIN
from contratti import models as m
from tests import factories as f
from tests.connettore.test_strumenti_acquisti import errore, esegui

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 21)


@pytest.fixture
def ambiente(make_user):
    ict = f.cluster("ICT")
    a, b = f.sottocluster("Alfa sotto", "ICT"), f.sottocluster("Beta sotto", "ICT")
    contratti = {}
    for chiave, sotto in (("a", a), ("b", b)):
        fab = f.fabbisogno(f"Fabbisogno {chiave}", cluster=ict, sottocluster=sotto)
        c = f.contratto(
            fabbisogno=fab, data_inizio=D(2024, 1, 1), durata_mesi=12,
            numero_contratto=f"580000000{'1' if chiave == 'a' else '2'}",
        )  # fmt: skip
        f.voce(c, importo_fisso=Decimal("1000.00"))
        contratti[chiave] = c
        m.RichiestaAcquisto.objects.create(
            cluster=ict, sottocluster=sotto, descrizione=f"RDA {chiave}", origine="manuale",
            numero_rda=f"510000000{'1' if chiave == 'a' else '2'}",
        )  # fmt: skip
    return {
        "admin": make_user("amm_mcp", role=ADMIN, is_superuser=True),
        "a": a, "b": b, "contratti": contratti, "ict": ict,
    }  # fmt: skip


def _id(dati, chiave="contratto"):
    return {r[chiave]["id"] if isinstance(r.get(chiave), dict) else r["id"] for r in dati["righe"]}


def test_elenco_rda_e_contratti_da_chiudere(ambiente):
    u, a = ambiente["admin"], ambiente["a"]
    tutti = esegui(u, "elenco_rda", {"cluster": ["tutti"]}, OGGI)
    assert tutti["totale"] == 2 and tutti["sottocluster_filtro"] == "tutti"
    dati = esegui(u, "elenco_rda", {"cluster": ["tutti"], "sottocluster": a.pk}, OGGI)
    assert dati["totale"] == 1 and dati["sottocluster_filtro"] == a.pk
    da_chiudere = esegui(u, "contratti_da_chiudere", {"cluster": ["tutti"]}, OGGI)
    filtrato = esegui(
        u, "contratti_da_chiudere", {"cluster": ["tutti"], "sottocluster": a.pk}, OGGI
    )
    assert da_chiudere["totale"] == 2 and filtrato["totale"] == 1


def test_altri_strumenti_accettano_il_sottocluster(ambiente):
    u, a = ambiente["admin"], ambiente["a"]
    for nome in ("anomalie_esecuzione", "stanziamenti", "cruscotto_acquisti"):
        dati = esegui(u, nome, {"cluster": ["tutti"], "sottocluster": a.pk}, OGGI)
        assert dati["alla_data"] == OGGI.isoformat() or dati["alla_data"] == OGGI
    voci = esegui(u, "piani_da_verificare", {"cluster": ["tutti"], "sottocluster": a.pk}, OGGI)
    assert voci["totale"] == 1 and voci["filtri"]["sottocluster"] == a.pk
    assert esegui(u, "piani_da_verificare", {"cluster": ["tutti"]}, OGGI)["totale"] == 2


def test_budget_e_spese_per_wbs(ambiente):
    u, a = ambiente["admin"], ambiente["a"]
    dati = esegui(u, "budget", {"anno": 2024, "cluster": ["tutti"], "sottocluster": a.pk}, OGGI)
    assert dati["sezioni"]
    wbs = m.WBS.objects.create(
        codice_wbs="W-A", descrizione="WBS A", tipo=m.WBS.Tipo.CLUSTER, cluster=ambiente["ict"]
    )
    m.WBS.objects.create(
        codice_wbs="W-B", descrizione="WBS B", tipo=m.WBS.Tipo.CLUSTER, cluster=ambiente["ict"]
    )
    voce = ambiente["contratti"]["a"].voci.get()
    m.VoceContratto.objects.filter(pk=voce.pk).update(wbs=wbs, natura="capex")
    dati = esegui(u, "spese_wbs", {"cluster": ["tutti"], "sottocluster": a.pk}, OGGI)
    assert [w["codice"] for w in dati["wbs"]] == ["W-A"]
    assert len(esegui(u, "spese_wbs", {"cluster": ["tutti"]}, OGGI)["wbs"]) == 2


def test_sottocluster_sconosciuto_e_rifiutato(ambiente):
    assert "Sottocluster sconosciuto: 99999" in errore(
        ambiente["admin"], "elenco_rda", {"cluster": ["tutti"], "sottocluster": 99999}
    )
