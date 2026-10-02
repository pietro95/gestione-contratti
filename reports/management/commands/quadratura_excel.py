"""Quadratura dei totali per anno con il Dashboard Excel (SPEC §7.8).

python manage.py quadratura_excel Contratti_IT.xlsx --cluster IT
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from reports import xlsx
from reports.export import quadratura_xlsx
from reports.quadratura import CAUSE, quadra


def _anni(testo: str) -> list[int]:
    inizio, _, fine = testo.partition("-")
    return list(range(int(inizio), int(fine or inizio) + 1))


def _euro(valore) -> str:
    if valore is None:
        return "—"
    return f"{valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Command(BaseCommand):
    help = "Confronta la competenza dell'app con la formula del Dashboard Excel; report XLSX."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument(
            "--cluster", "--area", dest="area", required=True, help="Codice del cluster (es. IT)."
        )
        parser.add_argument(
            "--anni", type=_anni, help="Es. 2024-2028 (default: anni del Dashboard)."
        )
        parser.add_argument(
            "--report", type=Path, help="XLSX di output (default: accanto al file)."
        )

    def handle(self, *args, file: Path, area, anni, report, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        q = quadra(file, area=area, anni=anni)
        percorso = report or file.with_name(f"{file.stem}_quadratura.xlsx")
        percorso.write_bytes(xlsx.salva(quadratura_xlsx(q)))

        self.stdout.write(f"Quadratura {q.file} ({area}): {len(q.righe)} righe confrontate.")
        self.stdout.write(
            "Anno  Excel minimo  App fisso  Differenza | Excel massimo  App massimo  Differenza"
        )
        for r in q.riepilogo():
            self.stdout.write(
                f"{r['anno']}  {_euro(r['excel_minimo'])}  {_euro(r['app_fisso'])}  "
                f"{_euro(r['diff_minimo'])} | {_euro(r['excel_massimo'])}  "
                f"{_euro(r['app_massimo'])}  {_euro(r['diff_massimo'])}"
            )
        for codice, righe in q.conteggio_cause().items():
            self.stdout.write(f"- {codice} ({righe} righe): {CAUSE[codice]}")
        for numero, motivo in q.escluse:
            self.stdout.write(f"- riga {numero} esclusa: {motivo}")
        self.stdout.write(f"\nReport: {percorso}")
