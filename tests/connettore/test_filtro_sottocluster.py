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
    tutti = esegui(u, "elenco_rda", {"sottocluster": ["tutti"]}, OGGI)
    assert tutti["totale"] == 2 and tutti["sottocluster_filtro"] == "tutti"
    dati = esegui(u, "elenco_rda", {"sottocluster": [a.pk]}, OGGI)
    assert dati["totale"] == 1 and dati["sottocluster_filtro"] == [a.pk]
    da_chiudere = esegui(u, "contratti_da_chiudere", {"sottocluster": ["tutti"]}, OGGI)
    filtrato = esegui(u, "contratti_da_chiudere", {"sottocluster": [a.pk]}, OGGI)
    assert da_chiudere["totale"] == 2 and filtrato["totale"] == 1


def test_altri_strumenti_accettano_il_sottocluster(ambiente):
    u, a = ambiente["admin"], ambiente["a"]
    for nome in ("anomalie_esecuzione", "stanziamenti", "cruscotto_acquisti"):
        dati = esegui(u, nome, {"sottocluster": [a.pk]}, OGGI)
        assert dati["alla_data"] == OGGI.isoformat() or dati["alla_data"] == OGGI
    voci = esegui(u, "piani_da_verificare", {"sottocluster": [a.pk]}, OGGI)
    assert voci["totale"] == 1 and voci["filtri"]["sottocluster"] == [a.pk]
    assert esegui(u, "piani_da_verificare", {"sottocluster": ["tutti"]}, OGGI)["totale"] == 2


def test_budget_e_spese_per_wbs(ambiente):
    u, a = ambiente["admin"], ambiente["a"]
    dati = esegui(u, "budget", {"anno": 2024, "sottocluster": [a.pk]}, OGGI)
    assert dati["sezioni"]
    wbs = m.WBS.objects.create(
        codice_wbs="W-A", descrizione="WBS A", tipo=m.WBS.Tipo.CLUSTER, cluster=ambiente["ict"]
    )
    m.WBS.objects.create(
        codice_wbs="W-B", descrizione="WBS B", tipo=m.WBS.Tipo.CLUSTER, cluster=ambiente["ict"]
    )
    voce = ambiente["contratti"]["a"].voci.get()
    m.VoceContratto.objects.filter(pk=voce.pk).update(wbs=wbs, natura="capex")
    dati = esegui(u, "spese_wbs", {"sottocluster": [a.pk]}, OGGI)
    assert [w["codice"] for w in dati["wbs"]] == ["W-A"]
    assert len(esegui(u, "spese_wbs", {"sottocluster": ["tutti"]}, OGGI)["wbs"]) == 2


def test_sottocluster_sconosciuto_e_rifiutato(ambiente):
    assert "Sottocluster sconosciuti: 99999" in errore(
        ambiente["admin"], "elenco_rda", {"sottocluster": [99999]}
    )


def test_piu_sottocluster_e_default_dai_propri(ambiente, make_user):
    """Rev36: un elenco di id (anche più d'uno), «tutti», e di default i sottocluster propri."""
    from accounts.roles import READER

    a, b = ambiente["a"], ambiente["b"]
    altro = m.Sottocluster.objects.create(cluster=f.cluster("OT"), nome="Altro")  # non tutti
    u = ambiente["admin"]
    due = esegui(u, "elenco_rda", {"sottocluster": [a.pk, b.pk]}, OGGI)
    assert due["totale"] == 2 and due["sottocluster_filtro"] == sorted([a.pk, b.pk])
    assert esegui(u, "elenco_rda", {"sottocluster": [altro.pk]}, OGGI)["totale"] == 0
    # Un lettore assegnato solo ad Alfa vede di default Alfa; «tutti» li vede tutti.
    lettore = make_user("lettore_alfa", role=READER)
    m.AssegnazioneCluster.objects.create(
        username="lettore_alfa", cluster=ambiente["ict"], sottocluster=a
    )
    di_default = esegui(lettore, "elenco_rda", {}, OGGI)
    assert di_default["totale"] == 1 and di_default["sottocluster_filtro"] == [a.pk]
    assert esegui(lettore, "elenco_rda", {"sottocluster": ["tutti"]}, OGGI)["totale"] == 2
    assert "Sottocluster sconosciuti: abc" in errore(u, "elenco_rda", {"sottocluster": ["abc"]})
    assert "argomento sconosciuto «cluster»" in errore(u, "elenco_rda", {"cluster": ["IT"]})


def test_riferimenti_indica_i_sottocluster_propri(ambiente, make_user):
    from accounts.roles import READER

    lettore = make_user("lettore_beta", role=READER)
    m.AssegnazioneCluster.objects.create(
        username="lettore_beta", cluster=ambiente["ict"], sottocluster=ambiente["b"]
    )
    dati = esegui(lettore, "riferimenti", {}, OGGI)
    propri = {s["id"]: s["proprio"] for s in dati["sottocluster"]}
    assert propri[ambiente["b"].pk] is True and propri[ambiente["a"].pk] is False
    conti = esegui(lettore, "riferimenti", {"includi": ["conti"], "sottocluster": ["tutti"]}, OGGI)
    assert conti["sottocluster_filtro"] == "tutti"
