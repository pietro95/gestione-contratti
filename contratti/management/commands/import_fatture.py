"""Import settimanale delle fatture dall'estrazione SAP (SPEC §7, Rev15).

python manage.py import_fatture /import/estrazione_fatture.xlsx [--dry-run]

Primo foglio, colonne Fornitore, Numero Documento, Data, Importo SAP (le altre si ignorano).
Le fatture entrano da prendere in carico; una fattura già registrata non si duplica. La stessa
operazione è disponibile dall'interfaccia (Import).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.fatture import importa_fatture
from contratti.importer.tabelle import FileNonValido


class Command(BaseCommand):
    help = "Importa le fatture dall'estrazione SAP settimanale."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")
        parser.add_argument("--report", type=Path, help="CSV delle anomalie.")

    def handle(self, *args, file: Path, dry_run, report=None, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        try:
            esito = importa_fatture(file, dry_run=dry_run)
        except FileNonValido as exc:
            raise CommandError(str(exc)) from exc
        c = esito.conteggi
        prefisso = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefisso}Righe lette {c['righe_lette']}: create {c['create']}, già registrate "
            f"{c['gia_presenti']}, non importate {c['non_importate']}, con contratto proposto "
            f"{c['con_contratto_proposto']}."
        )
        for a in esito.anomalie:
            self.stdout.write(f"  riga {a.riga}: {a.codice} {a.valore} — {a.messaggio}")
        if report:
            esito.scrivi_csv(report)
