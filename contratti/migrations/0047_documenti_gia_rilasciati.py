from django.db import migrations


def marca_rilasciati(apps, schema_editor):
    """Rilascio su SAP introdotto dopo la registrazione: RdC, MAP e MIGO già registrati sulle
    fatture risultano rilasciati alla data del documento, senza utente (dato storico)."""
    Documento = apps.get_model("contratti", "DocumentoEsecuzione")
    for documento in Documento.objects.filter(
        tipo__in=["ODA_RDC", "MAP", "MIGO"], fattura__isnull=False, data_rilascio__isnull=True
    ).only("pk", "data"):
        Documento.objects.filter(pk=documento.pk).update(data_rilascio=documento.data)


class Migration(migrations.Migration):
    dependencies = [("contratti", "0046_rda_rilasciata_da")]
    operations = [migrations.RunPython(marca_rilasciati, migrations.RunPython.noop)]
