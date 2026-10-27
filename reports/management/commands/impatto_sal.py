"""Impatto della Rev29 sulle voci a SAL: fatturato per anno prima e dopo, voce per voce.

python manage.py impatto_sal --output impatto_sal.xlsx [--livello probabile]

Solo lettura. Da eseguire prima del rilascio per vedere quali totali cambiano.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from contratti.engine.importi import ZERO
from contratti.engine.tipi import Livello
from reports import xlsx
from reports.budget import ETICHETTE_VISTE
from reports.impatto_sal import VISTE_IMPATTO, impatto_xlsx, righe_impatto


def _euro(valore) -> str:
    return f"{valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Command(BaseCommand):
    help = "Voci a SAL: fatturato per anno prima e dopo la Rev29; report XLSX, solo lettura."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path, required=True, help="XLSX di output.")
        parser.add_argument(
            "--livello", choices=[liv.value for liv in Livello], default=Livello.PROBABILE.value
        )

    def handle(self, *args, output: Path, livello, **options):
        if output.exists():
            raise CommandError(f"{output} esiste già: non lo sovrascrivo.")
        livello = Livello(livello)
        righe = righe_impatto(livello)
        output.write_bytes(xlsx.salva(impatto_xlsx(righe, livello, timezone.localdate())))
        self.stdout.write(f"Voci a SAL: {len(righe)}. Report: {output}")
        for vista in VISTE_IMPATTO:
            anni = sorted({a for r in righe for d in (r.prima[vista], r.dopo[vista]) for a in d})
            self.stdout.write(f"{ETICHETTE_VISTE[vista]} (livello {livello.value}):")
            for anno in anni:
                prima = sum((r.prima[vista].get(anno, ZERO) for r in righe), ZERO)
                dopo = sum((r.dopo[vista].get(anno, ZERO) for r in righe), ZERO)
                self.stdout.write(
                    f"  {anno}: prima {_euro(prima)}  dopo {_euro(dopo)}  "
                    f"delta {_euro(dopo - prima)}"
                )
        fuori = sum((r.non_pianificato["cassa"] for r in righe), ZERO)
        self.stdout.write(f"SAL non pianificato (fuori dai totali): {_euro(fuori)}")
