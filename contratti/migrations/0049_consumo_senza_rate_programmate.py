from django.db import migrations


def togli_rate_fittizie(apps, schema_editor):
    """A consumo non ha rate programmate: via le rate generate da zero (SPEC §4, Rev27).

    Restano le rate modificate a mano o consuntivate e quelle con un importo: sono dati
    inseriti da una persona o fissi a contratto.
    """
    Rata = apps.get_model("contratti", "Rata")
    Rata.objects.filter(
        piano__modalita="consumo",
        modificata_manualmente=False,
        consuntivo=False,
        importo=0,
        fattura__isnull=True,
        stanziamenti__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("contratti", "0048_fabbisogno_campi_competenza_dichiarata")]

    operations = [migrations.RunPython(togli_rate_fittizie, migrations.RunPython.noop)]
