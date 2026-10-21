"""Rev25: i dati dei vecchi cluster passano ai sottocluster della nuova struttura."""

import datetime

import pytest
from django.core.management import call_command

from contratti import models as m
from contratti.importer.migra_cluster import migra_cluster

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def dopo_import():
    """Nuova struttura (ICT con IT e Telecomunicazioni; INN con Innovazione) e dati vecchi."""
    ict = m.Cluster.objects.create(codice="ICT", nome="ICT")
    sc_it = m.Sottocluster.objects.create(cluster=ict, nome="IT", owner="Mario Rossi")
    sc_tlc = m.Sottocluster.objects.create(cluster=ict, nome="Telecomunicazioni")
    inn = f.cluster("INN")
    inn.nome = "Innovazione"
    inn.save()
    sc_inn = m.Sottocluster.objects.create(cluster=inn, nome="Innovazione")
    vecchio_it = f.cluster("IT")
    vecchio_tlc = f.cluster("TLC")
    vecchio_tlc.nome = "Telecomunicazioni"
    vecchio_tlc.save()
    return {
        "ict": ict, "sc_it": sc_it, "sc_tlc": sc_tlc, "sc_inn": sc_inn, "inn": inn,
        "it": vecchio_it, "tlc": vecchio_tlc,
    }  # fmt: skip


def _dati(c):
    fab_it = f.fabbisogno("Licenze", cluster=c["it"])
    fab_tlc = f.fabbisogno("Fonia", cluster=c["tlc"])
    fab_inn = f.fabbisogno("PoC", cluster=c["inn"])
    wbs = m.WBS.objects.create(
        codice_wbs="VJ/1", descrizione="w", tipo=m.WBS.Tipo.CLUSTER, cluster=c["it"]
    )
    conto = f.conto("600001", cluster=[c["it"], c["tlc"]])
    rda = m.RichiestaAcquisto.objects.create(
        cluster=c["tlc"], descrizione="r", origine=m.RichiestaAcquisto.Origine.MANUALE
    )
    ass = m.AssegnazioneCluster.objects.create(username="m.rossi", cluster=c["it"])
    return fab_it, fab_tlc, fab_inn, wbs, conto, rda, ass


def test_sposta_i_dati_e_archivia_il_vecchio_cluster(dopo_import):
    c = dopo_import
    fab_it, fab_tlc, fab_inn, wbs, conto, rda, ass = _dati(c)
    r = migra_cluster()
    for fab, sotto in ((fab_it, c["sc_it"]), (fab_tlc, c["sc_tlc"]), (fab_inn, c["sc_inn"])):
        fab.refresh_from_db()
        assert (fab.cluster, fab.sottocluster) == (sotto.cluster, sotto)
    wbs.refresh_from_db()
    rda.refresh_from_db()
    assert wbs.cluster == c["ict"] and rda.cluster == c["ict"] and rda.sottocluster == c["sc_tlc"]
    assert {x.codice for x in conto.clusters.all()} == {"ICT"}
    ass.refresh_from_db()
    assert (ass.cluster, ass.sottocluster) == (c["ict"], c["sc_it"])
    c["it"].refresh_from_db()
    c["tlc"].refresh_from_db()
    c["inn"].refresh_from_db()
    assert c["it"].archiviato and c["tlc"].archiviato and not c["inn"].archiviato
    assert dict(r.conteggi) == {
        "fabbisogni_spostati": 2,
        "fabbisogni_classificati": 1,
        "richieste_spostate": 1,
        "richieste_classificate": 0,
        "wbs_spostate": 1,
        "autorizzazioni_spostate": 0,
        "conti_aggiornati": 2,
        "assegnazioni_convertite": 1,
        "cluster_archiviati": 2,
    }
    # storia delle modifiche
    assert fab_it.history.first().history_change_reason == "Migrazione cluster/sottocluster"


def test_idempotente_e_anteprima_non_scrive(dopo_import):
    fab_it = _dati(dopo_import)[0]
    anteprima = migra_cluster(dry_run=True)
    assert anteprima.conteggi["fabbisogni_spostati"] == 2
    fab_it.refresh_from_db()
    assert fab_it.cluster == dopo_import["it"]
    migra_cluster()
    seconda = migra_cluster()
    assert not any(seconda.conteggi.values())


def test_fabbisogno_con_sottocluster_vecchio_non_si_tocca(dopo_import):
    c = dopo_import
    vecchio = f.sottocluster("Licenze software", "IT")
    fab = f.fabbisogno("Con sottocluster", cluster=c["it"], sottocluster=vecchio)
    r = migra_cluster()
    fab.refresh_from_db()
    assert fab.cluster == c["it"] and r.codici()["FABBISOGNO_CON_SOTTOCLUSTER_VECCHIO"] == 1
    c["it"].refresh_from_db()
    assert not c["it"].archiviato  # ha ancora un fabbisogno


def test_corrispondenza_ambigua_e_mappa_forzata(dopo_import):
    c = dopo_import
    altro = m.Cluster.objects.create(codice="ALT", nome="Altro")
    m.Sottocluster.objects.create(cluster=altro, nome="IT")
    fab = f.fabbisogno("Licenze", cluster=c["it"])
    r = migra_cluster()
    assert r.codici()["SOTTOCLUSTER_AMBIGUO"] == 1
    fab.refresh_from_db()
    assert fab.cluster == c["it"]
    migra_cluster(mappa={"IT": ("ICT", "IT")})
    fab.refresh_from_db()
    assert fab.cluster == c["ict"] and fab.sottocluster == c["sc_it"]


def test_cluster_senza_corrispondenza_segnalato(dopo_import):
    f.cluster("XYZ")
    r = migra_cluster()
    assert any(a.valore == "XYZ" for a in r.anomalie if a.codice == "CLUSTER_SENZA_CORRISPONDENZA")


def test_assegnazione_gia_presente_non_si_duplica(dopo_import):
    c = dopo_import
    m.AssegnazioneCluster.objects.create(username="u", cluster=c["it"])
    esistente = m.AssegnazioneCluster.objects.create(
        username="u", cluster=c["ict"], sottocluster=c["sc_it"], archiviato=True
    )
    migra_cluster()
    esistente.refresh_from_db()
    assert not esistente.archiviato  # torna attiva; quella vecchia è archiviata
    assert m.AssegnazioneCluster.objects.filter(username="u", archiviato=False).count() == 1


def test_comando(dopo_import, capsys):
    _dati(dopo_import)
    call_command("migra_cluster", "--dry-run")
    assert "[dry-run] fabbisogni_spostati: 2" in capsys.readouterr().out
    call_command("migra_cluster")
    assert m.Fabbisogno.objects.filter(cluster__codice="ICT").count() == 2
