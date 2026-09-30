"""Permessi dei ruoli sui modelli del registro.

Editor: aggiunge e modifica; Reader: solo lettura. Nessuno ha il permesso di cancellare:
i dati si archiviano (CLAUDE.md, regola 8). Admin è superuser e non ne ha bisogno.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

MODELLI = [
    "procedura",
    "soglia",
    "parametro",
    "categoria",
    "impianto",
    "progetto",
    "contocoge",
    "fornitore",
    "fabbisogno",
    "contratto",
    "opzionecontratto",
    "proroga",
    "vocecontratto",
    "pianofatturazione",
    "rata",
    "statopratica",
]
# Le tabelle di configurazione le modifica solo Admin.
CONFIGURAZIONE = {"procedura", "soglia", "parametro", "contocoge"}


def assegna(apps, schema_editor):
    # I permessi nascono dopo le migration (post_migrate): qui vanno creati esplicitamente.
    app_config = apps.get_app_config("contratti")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    def perms(azioni, modelli):
        codenames = [f"{a}_{mod}" for a in azioni for mod in modelli]
        return Permission.objects.filter(
            content_type__app_label="contratti", codename__in=codenames
        )

    editor, _ = Group.objects.get_or_create(name="Editor")
    reader, _ = Group.objects.get_or_create(name="Reader")
    dominio = [mod for mod in MODELLI if mod not in CONFIGURAZIONE]
    editor.permissions.add(*perms(["view"], MODELLI), *perms(["add", "change"], dominio))
    reader.permissions.add(*perms(["view"], MODELLI))


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0002_configurazione_iniziale"),
        ("accounts", "0002_gruppi_ruoli"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(assegna, migrations.RunPython.noop)]
