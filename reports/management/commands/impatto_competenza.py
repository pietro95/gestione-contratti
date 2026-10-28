"""Impatto della Rev31 sul budget: competenza a mesi frazionati contro la ripartizione a giorni.

python manage.py impatto_competenza --anno 2027 --natura OPEX [--output impatto.xlsx]

Solo lettura. Mostra per conto i totali delle quattro viste prima e dopo e le voci il cui valore
cambia di più. Da eseguire prima del rilascio.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from contratti import models as m
from contratti.engine.tipi import Livello
from reports import xlsx
from reports.budget import VISTE
from reports.impatto_competenza import impatto, impatto_xlsx


def _euro(valore) -> str:
    return f"{valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Command(BaseCommand):
    help = "Budget di un anno prima e dopo la Rev31 (mesi frazionati); solo lettura."

    def add_arguments(self, parser):
        parser.add_argument("--anno", type=int, required=True)
        parser.add_argument("--natura", choices=list(m.Natura.values), default=m.Natura.OPEX)
        parser.add_argument(
            "--livello", choices=[liv.value for liv in Livello], default=Livello.PROBABILE.value
        )
        parser.add_argument("--voci", type=int, default=15, help="Quante voci elencare.")
        parser.add_argument("--output", type=Path, help="XLSX di output (non sovrascrive).")

    def handle(self, *args, anno, natura, livello, voci, output, **options):
        if output and output.exists():
            raise CommandError(f"{output} esiste già: non lo sovrascrivo.")
        oggi = timezone.localdate()
        r = impatto(anno, natura, Livello(livello), oggi)
        self.stdout.write(f"Budget {anno} {natura}, livello {livello}. Importi in euro.")
        for vista in VISTE:
            self.stdout.write(f"\nVista {vista}, per conto (prima → dopo, delta):")
            for c in r.conti:
                if c.delta(vista):
                    self.stdout.write(
                        f"  {c.codice:<12} {_euro(c.prima[vista]):>16} → "
                        f"{_euro(c.dopo[vista]):>16}  {_euro(c.delta(vista)):>14}  {c.conto}"
                    )
            prima, dopo = r.totale("prima", vista), r.totale("dopo", vista)
            self.stdout.write(
                f"  {'TOTALE':<12} {_euro(prima):>16} → {_euro(dopo):>16}  "
                f"{_euro(dopo - prima):>14}"
            )
        for vista in ("consuntivo", "competenza"):
            self.stdout.write(f"\nLe {voci} voci che cambiano di più, vista {vista}:")
            for v in r.piu_cambiate(vista, voci):
                self.stdout.write(
                    f"  {_euro(v.delta(vista)):>12}  {_euro(v.prima[vista]):>12} → "
                    f"{_euro(v.dopo[vista]):>12}  "
                    f"{v.fabbisogno} — {v.descrizione} ({v.inizio:%d/%m/%Y}–{v.fine:%d/%m/%Y})"
                )
        if output:
            output.write_bytes(xlsx.salva(impatto_xlsx(r, oggi)))
            self.stdout.write(f"\nReport: {output}")
