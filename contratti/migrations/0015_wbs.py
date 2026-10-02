"""F9.2: il progetto finanziato diventa WBS (stessa tabella e stessa storia).

Le WBS esistenti sono i progetti dei contratti finanziati: tipo "a progetto".
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0014_cluster_obbligatorio"),
    ]

    operations = [
        migrations.RenameModel("Progetto", "WBS"),
        migrations.RenameModel("HistoricalProgetto", "HistoricalWBS"),
        migrations.RenameField("vocecontratto", "wbs", "codice_wbs_importato"),
        migrations.RenameField("historicalvocecontratto", "wbs", "codice_wbs_importato"),
    ]
