"""Rev35: la migration 0053 porta fabbisogni, RDA, WBS, autorizzazioni e conti sul sottocluster."""

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PRIMA = [("contratti", "0051_budget_conto_wbs")]
DOPO = [("contratti", "0054_sottocluster_ovunque_vincoli")]


@pytest.mark.django_db(transaction=True)
def test_dati_esistenti_sul_sottocluster():
    executor = MigrationExecutor(connection)
    executor.migrate(PRIMA)
    apps = executor.loader.project_state(PRIMA).apps
    Cluster = apps.get_model("contratti", "Cluster")
    Sottocluster = apps.get_model("contratti", "Sottocluster")
    Fabbisogno = apps.get_model("contratti", "Fabbisogno")
    Rda = apps.get_model("contratti", "RichiestaAcquisto")
    WBS = apps.get_model("contratti", "WBS")
    Autorizzazione = apps.get_model("contratti", "AutorizzazioneExtraBudget")
    Conto = apps.get_model("contratti", "ContoCoge")

    uno = Cluster.objects.create(codice="UNO", nome="Un solo sottocluster")
    due = Cluster.objects.create(codice="DUE", nome="Due sottocluster")
    zero = Cluster.objects.create(codice="ZER", nome="Nessun sottocluster")
    solo = Sottocluster.objects.create(cluster=uno, nome="Unico")
    a = Sottocluster.objects.create(cluster=due, nome="Alfa")
    b = Sottocluster.objects.create(cluster=due, nome="Beta")
    fab_uno = Fabbisogno.objects.create(descrizione="F1", cluster=uno)
    fab_due = Fabbisogno.objects.create(descrizione="F2", cluster=due)
    fab_classificato = Fabbisogno.objects.create(descrizione="F3", cluster=due, sottocluster=b)
    fab_zero = Fabbisogno.objects.create(descrizione="F4", cluster=zero)
    rda = Rda.objects.create(descrizione="R", cluster=due, origine="manuale")
    wbs = WBS.objects.create(codice_wbs="W/1", descrizione="w", tipo="cluster", cluster=due)
    progetto = WBS.objects.create(codice_wbs="W/2", descrizione="p", tipo="progetto")
    aut = Autorizzazione.objects.create(
        codice="X1",
        descrizione="x",
        cluster=uno,
        protocollo="1",
        data_autorizzazione=datetime.date(2026, 1, 1),
        importo_autorizzato="1.00",
    )
    conto = Conto.objects.create(
        codice="600001", descrizione="c", valido_dal=datetime.date(2020, 1, 1)
    )
    conto.clusters.add(uno, due)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(DOPO)
    apps = executor.loader.project_state(DOPO).apps
    Sottocluster = apps.get_model("contratti", "Sottocluster")
    Fabbisogno = apps.get_model("contratti", "Fabbisogno")

    assert Fabbisogno.objects.get(pk=fab_uno.pk).sottocluster_id == solo.pk  # unico attivo
    ripiego = Sottocluster.objects.get(cluster_id=due.pk, nome="Non classificato")
    assert Fabbisogno.objects.get(pk=fab_due.pk).sottocluster_id == ripiego.pk
    assert Fabbisogno.objects.get(pk=fab_classificato.pk).sottocluster_id == b.pk  # non si tocca
    assert Sottocluster.objects.get(cluster_id=zero.pk).nome == "Non classificato"
    assert Fabbisogno.objects.get(pk=fab_zero.pk).sottocluster.cluster_id == zero.pk
    assert (
        apps.get_model("contratti", "RichiestaAcquisto").objects.get(pk=rda.pk).sottocluster_id
        == ripiego.pk
    )
    assert apps.get_model("contratti", "WBS").objects.get(pk=wbs.pk).sottocluster_id == ripiego.pk
    assert apps.get_model("contratti", "WBS").objects.get(pk=progetto.pk).sottocluster_id is None
    assert (
        apps.get_model("contratti", "AutorizzazioneExtraBudget")
        .objects.get(pk=aut.pk)
        .sottocluster_id
        == solo.pk
    )
    # Il conto passa ai sottocluster attivi di ciascun cluster (anche al ripiego, se serve).
    assert {
        s.pk
        for s in apps.get_model("contratti", "ContoCoge")
        .objects.get(pk=conto.pk)
        .sottocluster.all()
    } == {
        solo.pk,
        a.pk,
        b.pk,
    }

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
