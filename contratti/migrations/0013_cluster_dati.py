"""F9.2: IT e TLC diventano cluster e ogni fabbisogno prende il cluster della sua area.

Si aggiungono gli altri cluster dell'ufficio ICTDINN proposti nel modello di import (da
completare o correggere dall'amministrazione o dall'import della struttura).
"""

from django.db import migrations

# Cluster iniziali: IT e TLC esistono già come aree; gli altri sono quelli del modello di
# import della struttura (Pietro, 02/10/2026). Si correggono dall'amministrazione o dall'import.
CLUSTER = [
    ("IT", "IT"),
    ("TLC", "TLC"),
    ("OT", "OT"),
    ("SICFIS", "Sicurezza fisica"),
    ("INN", "Innovazione"),
]


def da_area_a_cluster(apps, schema_editor):
    Cluster = apps.get_model("contratti", "Cluster")
    per_codice = {}
    for codice, nome in CLUSTER:
        per_codice[codice], _ = Cluster.objects.get_or_create(
            codice=codice, defaults={"nome": nome}
        )
    for nome in ("Fabbisogno", "HistoricalFabbisogno"):
        modello = apps.get_model("contratti", nome)
        for area in modello.objects.values_list("area", flat=True).distinct():
            cluster = per_codice.get(area)
            if cluster is None:
                cluster, _ = Cluster.objects.get_or_create(codice=area, defaults={"nome": area})
                per_codice[area] = cluster
            modello.objects.filter(area=area).update(cluster=cluster)


def da_cluster_ad_area(apps, schema_editor):
    for nome in ("Fabbisogno", "HistoricalFabbisogno"):
        modello = apps.get_model("contratti", nome)
        for f in modello.objects.select_related("cluster"):
            modello.objects.filter(pk=f.pk).update(area=f.cluster.codice[:3] if f.cluster else "IT")


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0012_cluster"),
    ]

    operations = [
        migrations.RunPython(da_area_a_cluster, da_cluster_ad_area),
    ]
