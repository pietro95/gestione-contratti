"""Import di un file Excel del registro (SPEC §7).

python manage.py import_excel Contratti_IT.xlsx --area IT --dry-run
"""

import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.carica import importa
from contratti.models import Area


class Command(BaseCommand):
    help = "Importa un Excel dei contratti; produce il report delle anomalie (CSV + riepilogo)."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--area", required=True, choices=Area.values)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")
        parser.add_argument(
            "--report", type=Path, help="CSV delle anomalie (default: accanto al file)."
        )
        parser.add_argument(
            "--data-stato",
            type=datetime.date.fromisoformat,
            help="Data dei passaggi di pratica importati (default: oggi).",
        )

    def handle(self, *args, file: Path, area, dry_run, report, data_stato, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        esito = importa(file, area=area, dry_run=dry_run, oggi=data_stato)
        percorso = report or file.with_name(f"{file.stem}_anomalie_import.csv")
        esito.scrivi_csv(percorso)
        self.stdout.write(esito.riepilogo())
        self.stdout.write(f"\nReport delle anomalie: {percorso}")
