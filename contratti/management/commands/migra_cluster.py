"""Sposta i dati dai vecchi cluster ai sottocluster della nuova struttura (Rev25).

python manage.py migra_cluster [--dry-run] [--mappa IT=ICT/IT ...]

Da lanciare dopo ``import_struttura_budget``: i fabbisogni, le richieste d'acquisto, le WBS, i
conti e le assegnazioni del vecchio cluster (IT, TLC, OT, ...) passano al cluster del
sottocluster con lo stesso nome. Con ``--mappa COD=CLUSTER/Sottocluster`` si forza una
corrispondenza. Idempotente; nessuna cancellazione.
"""

from django.core.management.base import BaseCommand, CommandError

from contratti.importer.migra_cluster import migra_cluster


class Command(BaseCommand):
    help = "Sposta fabbisogni, RDA, WBS, conti e assegnazioni dai vecchi cluster ai sottocluster."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")
        parser.add_argument(
            "--mappa",
            action="append",
            default=[],
            metavar="COD=CLUSTER/SOTTOCLUSTER",
            help="Forza la corrispondenza di un vecchio cluster (ripetibile).",
        )

    def handle(self, *args, dry_run, mappa, **options):
        forzate = {}
        for voce in mappa:
            try:
                vecchio, destinazione = voce.split("=", 1)
                cluster, sottocluster = destinazione.split("/", 1)
            except ValueError as exc:
                raise CommandError(
                    f"Mappa non valida: «{voce}» (COD=CLUSTER/Sottocluster)."
                ) from exc
            forzate[vecchio.strip()] = (cluster.strip(), sottocluster.strip())
        report = migra_cluster(dry_run=dry_run, mappa=forzate)
        prefisso = "[dry-run] " if dry_run else ""
        for chiave, valore in report.conteggi.items():
            self.stdout.write(f"{prefisso}{chiave}: {valore}")
        for a in report.anomalie:
            self.stdout.write(f"  {a.codice}: {a.valore} — {a.messaggio}")
