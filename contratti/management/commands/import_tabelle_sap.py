"""Caricamento delle tabelle SAP del processo d'acquisto da Excel (SPEC §7, Rev13).

python manage.py import_tabelle_sap /import/tabelle_sap.xlsx [--dry-run]

Fogli «Richiedenti», «Gruppi merci», «Gruppi acquisti» (almeno uno), colonne codice,
descrizione (o nome), predefinito e, per i gruppi merci, categoria. Idempotente; un errore
annulla tutto il file. La stessa operazione è disponibile dall'interfaccia (Import).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.tabelle import FileNonValido
from contratti.importer.tabelle_sap import FOGLI, importa_tabelle_sap


class Command(BaseCommand):
    help = "Carica o aggiorna richiedenti SAP, gruppi merci e gruppi acquisti da un Excel."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")

    def handle(self, *args, file: Path, dry_run, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        try:
            report = importa_tabelle_sap(file, dry_run=dry_run)
        except FileNonValido as exc:
            raise CommandError(str(exc)) from exc
        c = report.conteggi
        prefisso = "[dry-run] " if dry_run else ""
        for foglio in FOGLI:
            k = foglio.chiave
            self.stdout.write(
                f"{prefisso}{foglio.nome}: creati {c[f'{k}_creati']}, "
                f"aggiornati {c[f'{k}_aggiornati']}, invariati {c[f'{k}_invariati']}."
            )
