"""Permessi dei ruoli sulle quote per periodo (stessa regola di 0003)."""

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
    Group.objects.get(name="Editor").permissions.add(
        *perms.filter(codename__in=["view_quotaperiodo", "add_quotaperiodo", "change_quotaperiodo"])
    )
    Group.objects.get(name="Reader").permissions.add(*perms.filter(codename="view_quotaperiodo"))


class Migration(migrations.Migration):
    dependencies = [("contratti", "0005_quote_per_periodo")]

    operations = [migrations.RunPython(assegna, migrations.RunPython.noop)]
