"""Import di un file Excel del registro (SPEC §7).

python manage.py import_excel Contratti_IT.xlsx --cluster IT --dry-run
"""

import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.carica import importa


class Command(BaseCommand):
    help = "Importa un Excel dei contratti; produce il report delle anomalie (CSV + riepilogo)."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument(
            "--cluster", "--area", dest="area", required=True, help="Codice del cluster (es. IT)."
        )
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
        try:
            esito = importa(file, area=area, dry_run=dry_run, oggi=data_stato)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        percorso = report or file.with_name(f"{file.stem}_anomalie_import.csv")
        esito.scrivi_csv(percorso)
        self.stdout.write(esito.riepilogo())
        self.stdout.write(f"\nReport delle anomalie: {percorso}")
