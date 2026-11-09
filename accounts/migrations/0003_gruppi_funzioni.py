"""Gruppi Django delle funzioni dell'addetto (SPEC §8.1, Rev39), alimentati dai gruppi AD."""

from django.db import migrations

FUNZIONI = ("Addetto amministrativo", "Addetto al rilascio")


def crea_gruppi(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nome in FUNZIONI:
        Group.objects.get_or_create(name=nome)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_gruppi_ruoli")]

    operations = [migrations.RunPython(crea_gruppi, migrations.RunPython.noop)]
