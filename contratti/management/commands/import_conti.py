"""Caricamento del piano dei conti da CSV o XLSX (SPEC §7.2).

python manage.py import_conti /import/piano_conti.csv [--dry-run]

Colonne (intestazione obbligatoria, separatore ; oppure , per il CSV): codice, descrizione,
valido_dal e, facoltativa, valido_al. Date gg/mm/aaaa o aaaa-mm-gg. Idempotente; un errore
annulla tutto il file. La stessa operazione è disponibile dall'interfaccia (Import).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.conti import importa_conti
from contratti.importer.tabelle import FileNonValido


class Command(BaseCommand):
    help = "Carica o aggiorna il piano dei conti da un file CSV o XLSX."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")

    def handle(self, *args, file: Path, dry_run, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        try:
            report = importa_conti(file, dry_run=dry_run)
        except FileNonValido as exc:
            raise CommandError(str(exc)) from exc
        c = report.conteggi
        prefisso = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefisso}Conti creati: {c['creati']}, aggiornati: {c['aggiornati']}, "
            f"invariati: {c['invariati']}."
        )
