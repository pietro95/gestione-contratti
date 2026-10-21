"""Permessi dei ruoli sugli stanziamenti (stessa regola di 0026: Editor modifica, Reader legge)."""

from django.contrib.auth.management import create_permissions
from django.db import migrations


def assegna(apps, schema_editor):
    app_config = apps.get_app_config("contratti")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perms = Permission.objects.filter(content_type__app_label="contratti")
    editor, _ = Group.objects.get_or_create(name="Editor")
    reader, _ = Group.objects.get_or_create(name="Reader")
    editor.permissions.add(
        *perms.filter(codename__in=["view_stanziamento", "add_stanziamento", "change_stanziamento"])
    )
    reader.permissions.add(*perms.filter(codename="view_stanziamento"))


class Migration(migrations.Migration):
    dependencies = [("contratti", "0036_competenza_stanziamenti")]

    operations = [migrations.RunPython(assegna, migrations.RunPython.noop)]
