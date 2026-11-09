"""Rev39: una fattura può coprire più rate dello scadenzario.

Il legame passa da ``Fattura.rata`` (uno a uno) a ``Rata.fattura`` (molte rate, una fattura).
I legami esistenti si copiano prima di togliere il vecchio campo.
"""

import django.db.models.deletion
from django.db import migrations, models


def rate_sulla_fattura(apps, schema_editor):
    Fattura = apps.get_model("contratti", "Fattura")
    Rata = apps.get_model("contratti", "Rata")
    for fattura in Fattura.objects.exclude(rata__isnull=True).only("pk", "rata_id"):
        Rata.objects.filter(pk=fattura.rata_id).update(fattura=fattura.pk)


def fattura_sulla_rata(apps, schema_editor):
    """Indietro: a una fattura con più rate resta la prima (il vecchio legame è uno a uno)."""
    Fattura = apps.get_model("contratti", "Fattura")
    Rata = apps.get_model("contratti", "Rata")
    viste = set()
    for rata in Rata.objects.exclude(fattura__isnull=True).order_by("piano_id", "numero"):
        if rata.fattura_id in viste:
            continue
        viste.add(rata.fattura_id)
        Fattura.objects.filter(pk=rata.fattura_id).update(rata=rata.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0055_invio_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalrata",
            name="fattura",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="Fattura abbinata alla rata.",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="contratti.fattura",
            ),
        ),
        migrations.AddField(
            model_name="rata",
            name="fattura",
            field=models.ForeignKey(
                blank=True,
                help_text="Fattura abbinata alla rata.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rate",
                to="contratti.fattura",
            ),
        ),
        migrations.RunPython(rate_sulla_fattura, fattura_sulla_rata),
        migrations.RemoveField(
            model_name="fattura",
            name="rata",
        ),
        migrations.RemoveField(
            model_name="historicalfattura",
            name="rata",
        ),
    ]
