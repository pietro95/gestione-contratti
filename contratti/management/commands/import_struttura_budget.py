"""Struttura dal riepilogo del budget ICTDINN: cluster, sottocluster, conti e WBS (Rev25).

python manage.py import_struttura_budget /import/struttura_ictdinn.xlsx [--dry-run]
                                         [--valido-dal 01/01/2026]

Legge il file «Clusterizzazione budget» così com'è (celle unite comprese). Idempotente; un
errore annulla tutto il file. La stessa operazione è disponibile dall'interfaccia (Import).
Dopo l'import si spostano i fabbisogni esistenti con ``migra_cluster``.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer import tabelle
from contratti.importer.struttura_budget import importa_struttura_budget


class Command(BaseCommand):
    help = "Carica cluster, sottocluster, conti e WBS dal riepilogo del budget ICTDINN."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")
        parser.add_argument(
            "--valido-dal",
            help="Inizio di validità dei conti nuovi (gg/mm/aaaa); default 1/1 dell'anno del file.",
        )

    def handle(self, *args, file: Path, dry_run, valido_dal, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        try:
            dal = tabelle.data(valido_dal) if valido_dal else None
            report = importa_struttura_budget(file, dry_run=dry_run, valido_dal=dal)
        except (tabelle.FileNonValido, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        prefisso = "[dry-run] " if dry_run else ""
        for chiave, valore in report.conteggi.items():
            self.stdout.write(f"{prefisso}{chiave}: {valore}")
        for a in report.anomalie:
            self.stdout.write(f"  riga {a.riga or '-'} {a.codice}: {a.messaggio}")
