"""Gruppi Django dei tre ruoli applicativi (SPEC §8.1). I permessi arrivano con F1."""

from django.db import migrations

RUOLI = ("Admin", "Editor", "Reader")


def crea_gruppi(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nome in RUOLI:
        Group.objects.get_or_create(name=nome)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        # Nessuna cancellazione fisica in rollback: i gruppi restano.
        migrations.RunPython(crea_gruppi, migrations.RunPython.noop),
    ]
