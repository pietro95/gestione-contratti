"""Valori per l'import Excel: procedura e categoria di attesa, permessi sulle proposte."""

from django.contrib.auth.management import create_permissions
from django.db import migrations


def carica(apps, schema_editor):
    Procedura = apps.get_model("contratti", "Procedura")
    Categoria = apps.get_model("contratti", "Categoria")
    # Lead time di 6 mesi: lo stesso preavviso fisso dei file Excel attuali.
    Procedura.objects.get_or_create(
        codice="da_verificare",
        defaults={
            "nome": "Da verificare",
            "lead_time_mesi": 6,
            "ordine": 99,
            "note": "Assegnata dall'import Excel: procedura non indicata nei file.",
        },
    )
    Categoria.objects.get_or_create(nome="Da classificare")

    app_config = apps.get_app_config("contratti")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perms = Permission.objects.filter(content_type__app_label="contratti")
    modelli = ["propostaraggruppamento", "propostapredecessore"]
    Group.objects.get(name="Editor").permissions.add(
        *perms.filter(codename__in=[f"{a}_{m}" for a in ("view", "change") for m in modelli])
    )
    Group.objects.get(name="Reader").permissions.add(
        *perms.filter(codename__in=[f"view_{m}" for m in modelli])
    )


class Migration(migrations.Migration):
    dependencies = [("contratti", "0007_import_staging")]

    operations = [migrations.RunPython(carica, migrations.RunPython.noop)]
