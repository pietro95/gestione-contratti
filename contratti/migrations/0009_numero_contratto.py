"""F8: l'OdA è il numero di contratto; lo stato "OdA emesso" diventa "Contratto emesso"."""

from django.db import migrations, models

STATI = [
    ("non_avviata", "Non avviata"),
    ("offerta_richiesta", "Offerta richiesta"),
    ("offerta_ricevuta", "Offerta ricevuta"),
    ("rda_richiesta", "RDA richiesta"),
    ("rda_predisposta", "RDA predisposta"),
    ("rda_approvata", "RDA approvata"),
    ("contratto_emesso", "Contratto emesso"),
    ("contratto_attivo", "Contratto attivo"),
]
RIFERIMENTO = "Protocollo, contratto integrativo o atto aggiuntivo."


def rinomina_stato(apps, schema_editor):
    for nome in ("StatoPratica", "HistoricalStatoPratica"):
        apps.get_model("contratti", nome).objects.filter(stato="oda_emesso").update(
            stato="contratto_emesso"
        )


def ripristina_stato(apps, schema_editor):
    for nome in ("StatoPratica", "HistoricalStatoPratica"):
        apps.get_model("contratti", nome).objects.filter(stato="contratto_emesso").update(
            stato="oda_emesso"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0008_import_configurazione"),
    ]

    operations = [
        migrations.RenameField("contratto", "numero_oda", "numero_contratto"),
        migrations.RenameField("contratto", "data_oda", "data_emissione"),
        migrations.RenameField("historicalcontratto", "numero_oda", "numero_contratto"),
        migrations.RenameField("historicalcontratto", "data_oda", "data_emissione"),
        migrations.RunPython(rinomina_stato, ripristina_stato),
        migrations.AlterField(
            model_name="contratto",
            name="numero_contratto",
            field=models.CharField(
                blank=True, max_length=20, null=True, verbose_name="numero contratto"
            ),
        ),
        migrations.AlterField(
            model_name="contratto",
            name="data_emissione",
            field=models.DateField(blank=True, null=True, verbose_name="data emissione contratto"),
        ),
        migrations.AlterField(
            model_name="historicalcontratto",
            name="numero_contratto",
            field=models.CharField(
                blank=True, max_length=20, null=True, verbose_name="numero contratto"
            ),
        ),
        migrations.AlterField(
            model_name="historicalcontratto",
            name="data_emissione",
            field=models.DateField(blank=True, null=True, verbose_name="data emissione contratto"),
        ),
        migrations.AlterField(
            model_name="proroga",
            name="riferimento",
            field=models.CharField(blank=True, help_text=RIFERIMENTO, max_length=200),
        ),
        migrations.AlterField(
            model_name="historicalproroga",
            name="riferimento",
            field=models.CharField(blank=True, help_text=RIFERIMENTO, max_length=200),
        ),
        migrations.AlterField(
            model_name="statopratica",
            name="stato",
            field=models.CharField(choices=STATI, max_length=20),
        ),
        migrations.AlterField(
            model_name="historicalstatopratica",
            name="stato",
            field=models.CharField(choices=STATI, max_length=20),
        ),
    ]
