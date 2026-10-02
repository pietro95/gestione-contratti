"""F9.2: natura e WBS passano dal contratto alle sue voci.

- Ogni voce prende la natura del contratto; i contratti finanziati sono CAPEX sulla WBS del
  loro progetto (WBS a progetto).
- Natura e conto dei rinnovi decisi sul fabbisogno (F8) passano alle voci dei contratti da cui
  partono i rinnovi; sul fabbisogno restano solo per il previsto manuale.
"""

from django.db import migrations


def avanti(apps, schema_editor):
    Contratto = apps.get_model("contratti", "Contratto")
    Voce = apps.get_model("contratti", "VoceContratto")
    Fabbisogno = apps.get_model("contratti", "Fabbisogno")
    for c in Contratto.objects.all():
        voci = Voce.objects.filter(contratto=c)
        if c.finanziamento == "finanziato" and c.progetto_id:
            voci.update(natura="CAPEX", wbs_id=c.progetto_id)
        else:
            voci.update(natura=c.natura)
    for f in Fabbisogno.objects.exclude(natura_previsti="", conto_previsti__isnull=True):
        contratti = Contratto.objects.filter(fabbisogno=f, archiviato=False)
        if not contratti.exists():
            continue  # fabbisogno nuovo: i dati restano per il previsto manuale
        terminali = contratti.filter(successore__isnull=True)
        voci = Voce.objects.filter(contratto__in=terminali, proroga__isnull=True)
        if f.natura_previsti:
            voci.update(natura_rinnovi=f.natura_previsti)
        if f.conto_previsti_id:
            voci.update(conto_rinnovi_id=f.conto_previsti_id)
        Fabbisogno.objects.filter(pk=f.pk).update(natura_previsti="", conto_previsti=None)


def indietro(apps, schema_editor):
    Contratto = apps.get_model("contratti", "Contratto")
    Voce = apps.get_model("contratti", "VoceContratto")
    for c in Contratto.objects.all():
        voci = Voce.objects.filter(contratto=c)
        su_progetto = voci.filter(wbs__tipo="progetto").values_list("wbs_id", flat=True).first()
        c.natura = "CAPEX" if voci.filter(natura="CAPEX").exists() else "OPEX"
        c.finanziamento = "finanziato" if su_progetto else "ordinario"
        c.progetto_id = su_progetto
        c.save(update_fields=["natura", "finanziamento", "progetto"])


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0016_wbs_voci"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
