"""Fatturato pregresso dei contratti, totale per anno (Rev20).

python manage.py import_pregresso /import/pregresso.xlsx [--dry-run]

File CSV (separatore ; oppure ,) o XLSX (primo foglio), con intestazione: numero_contratto
(oppure id_contratto), anno, fatturato (imponibile) e, facoltativa, nota. Rieseguirlo non
duplica. La stessa operazione è disponibile dall'interfaccia (Import).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.pregresso import importa_pregresso
from contratti.importer.tabelle import FileNonValido


class Command(BaseCommand):
    help = "Registra il fatturato pregresso (totale per anno) dei contratti."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")

    def handle(self, *args, file: Path, dry_run, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        try:
            report = importa_pregresso(file, dry_run=dry_run)
        except FileNonValido as exc:
            raise CommandError(str(exc)) from exc
        c = report.conteggi
        prefisso = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefisso}Totali creati: {c['creati']}, corretti: {c['corretti']}, "
            f"già uguali: {c['invariati']}, righe scartate: {c['scartati']}."
        )
        for a in report.anomalie:
            self.stdout.write(f"  - {a.messaggio}")
