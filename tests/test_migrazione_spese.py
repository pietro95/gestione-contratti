"""F9.5.3: la migration che toglie la spesa ricorrente ne conserva i dati nelle note."""

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PRIMA = [("contratti", "0021_fabbisogno_spesa_ricorrente")]
DOPO = [("contratti", "0022_senza_contratto_sul_contratto")]


@pytest.mark.django_db(transaction=True)
def test_spesa_ricorrente_conservata_nelle_note():
    executor = MigrationExecutor(connection)
    executor.migrate(PRIMA)
    apps = executor.loader.project_state(PRIMA).apps
    Fabbisogno = apps.get_model("contratti", "Fabbisogno")
    Cluster = apps.get_model("contratti", "Cluster")
    Categoria = apps.get_model("contratti", "Categoria")
    Fornitore = apps.get_model("contratti", "Fornitore")
    cluster = Cluster.objects.get_or_create(codice="ZZ", defaults={"nome": "Prova"})[0]
    categoria = Categoria.objects.get_or_create(nome="Categoria di prova")[0]
    f = Fabbisogno.objects.create(
        descrizione="Dominio di prova",
        cluster=cluster,
        categoria=categoria,
        note="Nota esistente.",
        senza_contratto=True,
        spesa_fornitore=Fornitore.objects.create(ragione_sociale="Registrar di prova"),
        spesa_importo=Decimal("25.00"),
        spesa_periodicita="annuale",
        spesa_dal=datetime.date(2025, 3, 15),
    )
    altro = Fabbisogno.objects.create(descrizione="Altro", cluster=cluster, categoria=categoria)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(DOPO)
    apps = executor.loader.project_state(DOPO).apps
    Fabbisogno = apps.get_model("contratti", "Fabbisogno")
    assert Fabbisogno.objects.get(pk=f.pk).note == (
        "Nota esistente.\n\nSpesa ricorrente senza contratto (rimossa in F9.5.3): fornitore "
        "Registrar di prova, 25.00 € annuale, prima spesa 15/03/2025"
    )
    assert Fabbisogno.objects.get(pk=altro.pk).note == ""
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
