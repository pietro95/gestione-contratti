"""Valori iniziali di configurazione, tutti marcati come provvisori (SPEC §9).

Da confermare con Procurement; si modificano dall'admin, senza nuove migration.
"""

import datetime
from decimal import Decimal

from django.db import migrations

SEMPRE = datetime.date(2000, 1, 1)

PROCEDURE = [
    # codice, nome, lead time in mesi, ordine
    ("affidamento_diretto", "Affidamento diretto", 2, 10),
    ("mepa_oda", "MEPA / ODA", 3, 20),
    ("rdo", "RDO", 4, 30),
    ("negoziata", "Procedura negoziata", 6, 40),
    ("aperta", "Procedura aperta", 9, 50),
    ("adesione_convenzione", "Adesione a convenzione / AQ", 2, 60),
]

SOGLIE = [
    # codice, descrizione, importo, valida dal, riferimento
    (
        "affidamento_diretto_servizi_forniture",
        "Affidamento diretto di servizi e forniture (limite escluso)",
        Decimal("140000.00"),
        datetime.date(2023, 7, 1),
        "D.Lgs. 36/2023, art. 50, c. 1, lett. b); applicabilità ai settori speciali da confermare",
    ),
]

PARAMETRI = [
    ("giorni_pagamento", Decimal("60")),
    ("pagamento_fine_mese", Decimal("1")),
    ("adeguamento_pct", Decimal("0")),
    ("finestra_alert_mesi", Decimal("3")),
    ("orizzonte_anni", Decimal("3")),
]

CATEGORIE = [
    "Licenze software",
    "Manutenzione hardware",
    "Connettività",
    "Servizi professionali",
    "Noleggio",
]


def carica(apps, schema_editor):
    Procedura = apps.get_model("contratti", "Procedura")
    Soglia = apps.get_model("contratti", "Soglia")
    Parametro = apps.get_model("contratti", "Parametro")
    Categoria = apps.get_model("contratti", "Categoria")

    for codice, nome, lead_time, ordine in PROCEDURE:
        Procedura.objects.get_or_create(
            codice=codice,
            defaults={"nome": nome, "lead_time_mesi": lead_time, "ordine": ordine},
        )
    for codice, descrizione, valore, dal, riferimento in SOGLIE:
        Soglia.objects.get_or_create(
            codice=codice,
            valida_dal=dal,
            defaults={
                "descrizione": descrizione,
                "importo": valore,
                "riferimento_normativo": riferimento,
            },
        )
    for chiave, valore in PARAMETRI:
        Parametro.objects.get_or_create(
            chiave=chiave, valido_dal=SEMPRE, defaults={"valore": valore}
        )
    for nome in CATEGORIE:
        Categoria.objects.get_or_create(nome=nome)


class Migration(migrations.Migration):
    dependencies = [("contratti", "0001_initial")]

    operations = [
        # Nessuna cancellazione fisica in rollback.
        migrations.RunPython(carica, migrations.RunPython.noop),
    ]
