"""Rev35, passo 2: ogni fabbisogno, RDA, WBS di cluster, autorizzazione e conto ha un sottocluster.

Regola (SPEC §4): dove il sottocluster manca si usa l'unico sottocluster attivo del cluster; se
il cluster ne ha più d'uno (o nessuno), si crea «Non classificato», da riclassificare a mano.
I conti passano da «cluster» a tutti i sottocluster attivi di quel cluster, ai quali già
appartenevano di fatto: l'amministrazione li restringe.
"""

from django.db import migrations

NOME = "Non classificato"


def _ripiego(Sottocluster, cluster_id, cache):
    if cluster_id not in cache:
        attivi = list(Sottocluster.objects.filter(cluster_id=cluster_id, archiviato=False)[:2])
        if len(attivi) == 1:
            cache[cluster_id] = attivi[0]
        else:
            cache[cluster_id], _ = Sottocluster.objects.get_or_create(
                cluster_id=cluster_id, nome=NOME, defaults={"archiviato": False}
            )
    return cache[cluster_id]


def porta_al_sottocluster(apps, schema_editor):
    Sottocluster = apps.get_model("contratti", "Sottocluster")
    Fabbisogno = apps.get_model("contratti", "Fabbisogno")
    Rda = apps.get_model("contratti", "RichiestaAcquisto")
    WBS = apps.get_model("contratti", "WBS")
    Autorizzazione = apps.get_model("contratti", "AutorizzazioneExtraBudget")
    Conto = apps.get_model("contratti", "ContoCoge")
    cache: dict = {}

    for modello in (Fabbisogno, Rda, Autorizzazione):
        for oggetto in modello.objects.filter(sottocluster__isnull=True):
            oggetto.sottocluster = _ripiego(Sottocluster, oggetto.cluster_id, cache)
            oggetto.save(update_fields=["sottocluster"])
    for wbs in WBS.objects.filter(sottocluster__isnull=True, cluster__isnull=False):
        wbs.sottocluster = _ripiego(Sottocluster, wbs.cluster_id, cache)
        wbs.save(update_fields=["sottocluster"])

    for conto in Conto.objects.all():
        for cluster in conto.clusters.all():
            attivi = list(Sottocluster.objects.filter(cluster=cluster, archiviato=False))
            conto.sottocluster.add(*(attivi or [_ripiego(Sottocluster, cluster.pk, cache)]))


def ripristina(apps, schema_editor):
    """Il passo indietro non perde nulla: il cluster resta sempre valorizzato."""
    Conto = apps.get_model("contratti", "ContoCoge")
    for conto in Conto.objects.all():
        conto.clusters.set({s.cluster_id for s in conto.sottocluster.all()})


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0052_sottocluster_ovunque_campi"),
    ]

    operations = [
        migrations.RunPython(porta_al_sottocluster, ripristina),
    ]
