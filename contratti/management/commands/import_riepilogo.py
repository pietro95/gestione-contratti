"""Import del Riepilogo RDA Ordini (F11.4b, SPEC §7): stessa operazione di Gestione → Import.

python manage.py import_riepilogo /import/<file.xlsx> [--dry-run] [--report anomalie.csv]
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.riepilogo import importa_riepilogo
from contratti.importer.tabelle import FileNonValido


class Command(BaseCommand):
    help = "Import riepilogo da Excel (vedi SPEC §7)."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")
        parser.add_argument("--report", type=Path, help="CSV delle anomalie.")

    def handle(self, *args, file: Path, dry_run, report=None, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        try:
            esito = importa_riepilogo(file, dry_run=dry_run)
        except FileNonValido as exc:
            raise CommandError(str(exc)) from exc
        prefisso = "[dry-run] " if dry_run else ""
        conteggi = ", ".join(f"{k} {v}" for k, v in esito.conteggi.items())
        self.stdout.write(f"{prefisso}{conteggi}.")
        codici = esito.codici()
        if codici:
            self.stdout.write(
                "Anomalie: " + ", ".join(f"{k} {v}" for k, v in sorted(codici.items()))
            )
        if report:
            esito.scrivi_csv(report)
