"""Rev35, passo 1: WBS, autorizzazioni extra budget e conti si legano al sottocluster."""

import django.db.models.deletion
from django.db import migrations, models


def _storico(related="+"):
    return models.ForeignKey(
        blank=True,
        db_constraint=False,
        null=True,
        on_delete=django.db.models.deletion.DO_NOTHING,
        related_name=related,
        to="contratti.sottocluster",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0051_budget_conto_wbs"),
    ]

    operations = [
        migrations.AddField(
            model_name="wbs",
            name="sottocluster",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="wbs",
                to="contratti.sottocluster",
            ),
        ),
        migrations.AddField(model_name="historicalwbs", name="sottocluster", field=_storico()),
        # Nullo finché la migration dei dati non lo valorizza; il passo 3 lo rende obbligatorio.
        migrations.AddField(
            model_name="autorizzazioneextrabudget",
            name="sottocluster",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="autorizzazioni_extra_budget",
                to="contratti.sottocluster",
            ),
        ),
        migrations.AddField(
            model_name="historicalautorizzazioneextrabudget",
            name="sottocluster",
            field=_storico(),
        ),
        migrations.AddField(
            model_name="contocoge",
            name="sottocluster",
            field=models.ManyToManyField(
                blank=True, related_name="conti", to="contratti.sottocluster"
            ),
        ),
    ]
