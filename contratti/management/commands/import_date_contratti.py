"""Date di emissione dei contratti già registrati, da un'estrazione SAP (F8).

python manage.py import_date_contratti /import/date_contratti.csv [--dry-run]

File CSV (separatore ; oppure ,) o XLSX (primo foglio), con intestazione: numero_contratto
(oppure contratto) e data_emissione (oppure data). Date gg/mm/aaaa, gg.mm.aaaa o aaaa-mm-gg.
Riempie solo le date vuote; le discordanze vanno nel report. La stessa operazione è
disponibile dall'interfaccia (Import).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.date_emissione import PROBLEMI_FILE, importa_date
from contratti.importer.tabelle import FileNonValido


class Command(BaseCommand):
    help = "Compila la data di emissione dei contratti da un file CSV o XLSX."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")

    def handle(self, *args, file: Path, dry_run, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        try:
            report = importa_date(file, dry_run=dry_run)
        except FileNonValido as exc:
            raise CommandError(str(exc)) from exc
        c = report.conteggi
        problemi = sum(1 for a in report.anomalie if a.codice in PROBLEMI_FILE)
        prefisso = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefisso}Date compilate: {c['compilati']}, già uguali: {c['invariati']}, "
            f"discordanti: {c['discordanti']}, numeri non trovati: {c['non_trovati']}, "
            f"problemi nel file: {problemi}."
        )
        ordinate = [a for a in report.anomalie if a.codice in PROBLEMI_FILE]
        ordinate += [a for a in report.anomalie if a.codice not in PROBLEMI_FILE]
        for a in ordinate:
            self.stdout.write(f"  - {a.messaggio}")
