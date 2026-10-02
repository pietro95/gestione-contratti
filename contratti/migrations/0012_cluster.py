"""F9.2: il cluster sostituisce l'area (schema; i dati in 0013, i vincoli in 0014)."""

import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0011_registro_import"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Area facoltativa prima di toglierla (0014): all'indietro torna obbligatoria solo qui,
        # dopo che 0013 ha rimesso i valori.
        migrations.AlterField(
            model_name="fabbisogno",
            name="area",
            field=models.CharField(choices=[("IT", "IT"), ("TLC", "TLC")], max_length=3, null=True),
        ),
        migrations.AlterField(
            model_name="historicalfabbisogno",
            name="area",
            field=models.CharField(choices=[("IT", "IT"), ("TLC", "TLC")], max_length=3, null=True),
        ),
        migrations.CreateModel(
            name="Cluster",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("archiviato", models.BooleanField(db_index=True, default=False)),
                ("codice", models.CharField(max_length=10, unique=True)),
                ("nome", models.CharField(max_length=100)),
                ("note", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "cluster",
                "verbose_name_plural": "cluster",
                "ordering": ["codice"],
            },
        ),
        migrations.AlterModelOptions(
            name="fabbisogno",
            options={
                "ordering": ["cluster__codice", "descrizione"],
                "verbose_name": "fabbisogno",
                "verbose_name_plural": "fabbisogni",
            },
        ),
        migrations.AddField(
            model_name="fabbisogno",
            name="cluster",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fabbisogni",
                to="contratti.cluster",
            ),
        ),
        migrations.AddField(
            model_name="historicalfabbisogno",
            name="cluster",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="contratti.cluster",
            ),
        ),
        migrations.CreateModel(
            name="HistoricalCluster",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                ("archiviato", models.BooleanField(db_index=True, default=False)),
                ("codice", models.CharField(db_index=True, max_length=10)),
                ("nome", models.CharField(max_length=100)),
                ("note", models.TextField(blank=True)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical cluster",
                "verbose_name_plural": "historical cluster",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
