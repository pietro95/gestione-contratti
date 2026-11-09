"""Rev41: la migration sposta il legame fattura-rata sulla rata e non perde gli abbinamenti."""

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PRIMA = [("contratti", "0056_fattura_imponibile_senza_iva")]
DOPO = [("contratti", "0057_fattura_su_piu_rate")]


def _storico(apps):
    Fornitore = apps.get_model("contratti", "Fornitore")
    Fattura = apps.get_model("contratti", "Fattura")
    Contratto = apps.get_model("contratti", "Contratto")
    Fabbisogno = apps.get_model("contratti", "Fabbisogno")
    Cluster = apps.get_model("contratti", "Cluster")
    Sottocluster = apps.get_model("contratti", "Sottocluster")
    VoceContratto = apps.get_model("contratti", "VoceContratto")
    Piano = apps.get_model("contratti", "PianoFatturazione")
    Rata = apps.get_model("contratti", "Rata")
    Procedura = apps.get_model("contratti", "Procedura")
    cluster = Cluster.objects.get_or_create(codice="ZZ", defaults={"nome": "Prova"})[0]
    sottocluster = Sottocluster.objects.create(cluster=cluster, nome="Prova")
    fornitore = Fornitore.objects.create(ragione_sociale="Fornitore di prova")
    fabbisogno = Fabbisogno.objects.create(
        descrizione="F", cluster=cluster, sottocluster=sottocluster
    )
    contratto = Contratto.objects.create(
        fabbisogno=fabbisogno,
        procedura=Procedura.objects.get_or_create(
            codice="prova", defaults={"nome": "Prova", "lead_time_mesi": 1}
        )[0],
        fornitore=fornitore,
        data_inizio=datetime.date(2026, 1, 1),
        durata_mesi=12,
    )
    voce = VoceContratto.objects.create(contratto=contratto, importo_fisso=Decimal("100.00"))
    piano = Piano.objects.create(voce=voce, modalita="anticipata", periodicita="trimestrale")
    rate = [
        Rata.objects.create(
            piano=piano, numero=n, data_fattura=datetime.date(2026, n, 1),
            data_pagamento_stimata=datetime.date(2026, n, 28), importo=Decimal("25.00"),
        )
        for n in (1, 2)
    ]  # fmt: skip
    fattura = Fattura.objects.create(
        fornitore=fornitore, contratto=contratto, numero="F1", data=datetime.date(2026, 1, 5),
        importo_documento=Decimal("25.00"), rata=rate[0],
    )  # fmt: skip
    return fattura, rate


@pytest.mark.django_db(transaction=True)
def test_il_legame_passa_alla_rata_e_torna_indietro():
    executor = MigrationExecutor(connection)
    executor.migrate(PRIMA)
    fattura, rate = _storico(executor.loader.project_state(PRIMA).apps)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(DOPO)
    apps = executor.loader.project_state(DOPO).apps
    Rata = apps.get_model("contratti", "Rata")
    assert Rata.objects.get(pk=rate[0].pk).fattura_id == fattura.pk
    assert Rata.objects.get(pk=rate[1].pk).fattura_id is None
    # Una seconda rata sulla stessa fattura: indietro resta la prima.
    Rata.objects.filter(pk=rate[1].pk).update(fattura=fattura.pk)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(PRIMA)
    apps = executor.loader.project_state(PRIMA).apps
    assert apps.get_model("contratti", "Fattura").objects.get(pk=fattura.pk).rata_id == rate[0].pk

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
