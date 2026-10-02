"""F9.2: dopo il passaggio dei dati (0013), l'area si toglie e il cluster è obbligatorio.

Migration separata: PostgreSQL non modifica una tabella con aggiornamenti in sospeso nella
stessa transazione.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0013_cluster_dati"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="fabbisogno",
            name="area",
        ),
        migrations.RemoveField(
            model_name="historicalfabbisogno",
            name="area",
        ),
        migrations.AlterField(
            model_name="fabbisogno",
            name="cluster",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fabbisogni",
                to="contratti.cluster",
            ),
        ),
    ]
