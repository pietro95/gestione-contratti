"""Processo d'acquisto (F11.1): parametri iniziali, permessi dei ruoli, RDA dai contratti.

- Parametri provvisori (SPEC §5.7): RDA ferma dopo 30 giorni, fattura ferma dopo 15.
- Permessi come in 0003: Editor aggiunge e modifica RDA, posizioni, storico, fatture e
  documenti; Reader legge. Le tabelle SAP e le funzioni degli utenti sono configurazione:
  solo Admin (gli altri le leggono).
- Il n. RDA già registrato sui contratti diventa una RDA collegata come RDA d'origine
  (SPEC §7): senza date, con il cluster del fabbisogno del contratto e senza referente. Solo
  i numeri validi (10 cifre); un testo diverso resta com'è sul contratto.
"""

import datetime
import re
from decimal import Decimal

from django.contrib.auth.management import create_permissions
from django.db import migrations

SEMPRE = datetime.date(2000, 1, 1)
PARAMETRI = [("rda_ferma_giorni", Decimal("30")), ("fattura_ferma_giorni", Decimal("15"))]

DOMINIO = ["richiestaacquisto", "posizionerda", "eventorda", "fattura", "documentoesecuzione"]
CONFIGURAZIONE = ["richiedentesap", "gruppoacquisti", "gruppomerci", "funzioneutente"]
NUMERO_VALIDO = re.compile(r"^\d{10}$")


def parametri(apps, schema_editor):
    Parametro = apps.get_model("contratti", "Parametro")
    for chiave, valore in PARAMETRI:
        Parametro.objects.get_or_create(
            chiave=chiave, valido_dal=SEMPRE, defaults={"valore": valore}
        )


def permessi(apps, schema_editor):
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
    tutti = DOMINIO + CONFIGURAZIONE
    editor.permissions.add(*perms(["view"], tutti), *perms(["add", "change"], DOMINIO))
    reader.permissions.add(*perms(["view"], tutti))


def rda_dai_contratti(apps, schema_editor):
    Contratto = apps.get_model("contratti", "Contratto")
    RichiestaAcquisto = apps.get_model("contratti", "RichiestaAcquisto")
    per_numero: dict[str, list] = {}
    contratti = (
        Contratto.objects.filter(numero_rda__isnull=False, rda__isnull=True)
        .select_related("fabbisogno")
        .order_by("pk")
    )
    for c in contratti:
        numero = (c.numero_rda or "").strip().lstrip("﻿")
        if NUMERO_VALIDO.match(numero):
            per_numero.setdefault(numero, []).append(c)
    for numero, gruppo in per_numero.items():
        rda = RichiestaAcquisto.objects.filter(numero_rda=numero, archiviato=False).first()
        if rda is None:
            primo = gruppo[0]
            date = [d for c in gruppo for d in (c.data_emissione, c.data_inizio) if d]
            rda = RichiestaAcquisto.objects.create(
                origine="import",
                cluster_id=primo.fabbisogno.cluster_id,
                descrizione=(primo.descrizione or primo.fabbisogno.descrizione)[:250],
                numero_rda=numero,
                data_creazione=min(date) if date else datetime.date.today(),
                note="Creata dal n. RDA dei contratti (migrazione F11.1).",
            )
        Contratto.objects.filter(pk__in=[c.pk for c in gruppo]).update(rda=rda)


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0025_processo_acquisto"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    # Nessuna cancellazione fisica in rollback.
    operations = [
        migrations.RunPython(parametri, migrations.RunPython.noop),
        migrations.RunPython(permessi, migrations.RunPython.noop),
        migrations.RunPython(rda_dai_contratti, migrations.RunPython.noop),
    ]
