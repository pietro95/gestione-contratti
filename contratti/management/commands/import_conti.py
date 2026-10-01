"""Caricamento del piano dei conti da CSV (SPEC §7.2: il piano dei conti precede l'import).

python manage.py import_conti /import/piano_conti.csv [--dry-run]

Colonne (intestazione obbligatoria, separatore ; oppure ,): codice, descrizione, valido_dal
e, facoltativa, valido_al. Date gg/mm/aaaa o aaaa-mm-gg. Idempotente: la coppia
(codice, valido_dal) identifica il conto; una riga già presente aggiorna descrizione e
fine validità, mai cancellazioni.
"""

import csv
import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contratti.models import ContoCoge

OBBLIGATORIE = ("codice", "descrizione", "valido_dal")


def _data(testo: str, riga: int, campo: str) -> datetime.date | None:
    testo = (testo or "").strip()
    if not testo:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(testo, formato).date()
        except ValueError:
            continue
    raise CommandError(f"Riga {riga}: {campo} non valida ({testo!r}).")


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Carica o aggiorna il piano dei conti da un file CSV."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")

    def handle(self, *args, file: Path, dry_run, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        testo = file.read_text(encoding="utf-8-sig")
        separatore = (
            ";" if testo.splitlines()[0].count(";") >= testo.splitlines()[0].count(",") else ","
        )
        lettore = csv.DictReader(testo.splitlines(), delimiter=separatore)
        colonne = [c.strip().lower() for c in lettore.fieldnames or []]
        mancanti = [c for c in OBBLIGATORIE if c not in colonne]
        if mancanti:
            raise CommandError(f"Colonne mancanti: {', '.join(mancanti)}.")
        conteggi = {"creati": 0, "aggiornati": 0, "invariati": 0}
        try:
            with transaction.atomic():
                for numero, grezza in enumerate(lettore, start=2):
                    r = {k.strip().lower(): (v or "").strip() for k, v in grezza.items() if k}
                    if not any(r.values()):
                        continue
                    if not r["codice"] or not r["descrizione"]:
                        raise CommandError(f"Riga {numero}: codice e descrizione obbligatori.")
                    dal = _data(r["valido_dal"], numero, "valido_dal")
                    if dal is None:
                        raise CommandError(f"Riga {numero}: valido_dal obbligatoria.")
                    al = _data(r.get("valido_al", ""), numero, "valido_al")
                    conto = ContoCoge.objects.filter(codice=r["codice"], valido_dal=dal).first()
                    if conto is None:
                        conto = ContoCoge(codice=r["codice"], valido_dal=dal)
                        esito = "creati"
                    elif (conto.descrizione, conto.valido_al) == (r["descrizione"], al):
                        conteggi["invariati"] += 1
                        continue
                    else:
                        esito = "aggiornati"
                    conto.descrizione, conto.valido_al = r["descrizione"], al
                    conto.full_clean()
                    conto.save()
                    conteggi[esito] += 1
                if dry_run:
                    raise _Rollback
        except _Rollback:
            pass
        prefisso = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefisso}Conti creati: {conteggi['creati']}, aggiornati: {conteggi['aggiornati']}, "
            f"invariati: {conteggi['invariati']}."
        )
