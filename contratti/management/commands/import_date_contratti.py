"""Date di emissione dei contratti già registrati, da un'estrazione SAP (F8).

python manage.py import_date_contratti /import/date_contratti.csv [--dry-run]

File CSV (separatore ; oppure ,) o XLSX (primo foglio), con intestazione: numero_contratto
(oppure contratto) e data_emissione (oppure data). Date gg/mm/aaaa, gg.mm.aaaa o aaaa-mm-gg.

Riempie solo le date vuote. Una data già presente e diversa non si tocca: va nel report
come discordanza, da correggere a mano. Rieseguire il comando non cambia nulla.
"""

import csv
import datetime
from collections import defaultdict
from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contratti.importer.normalizza import codice
from contratti.models import Contratto

COLONNE = {
    "numero_contratto": ("numero_contratto", "contratto", "numero contratto"),
    "data_emissione": ("data_emissione", "data", "data emissione"),
}
FORMATI = ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y")
MOTIVO = "Data di emissione da import_date_contratti"


class _Rollback(Exception):
    pass


def _data(valore) -> datetime.date | None:
    if isinstance(valore, datetime.datetime):
        return valore.date()
    if isinstance(valore, datetime.date):
        return valore
    testo = str(valore or "").strip()
    if not testo:
        return None
    for formato in FORMATI:
        try:
            return datetime.datetime.strptime(testo, formato).date()
        except ValueError:
            continue
    raise ValueError(testo)


def _numero(valore) -> str | None:
    if isinstance(valore, float) and valore.is_integer():
        valore = int(valore)  # celle numeriche di Excel: 5800001234.0
    return codice(valore)


def _righe(file: Path) -> list[dict]:
    """Righe del file come dizionari con le chiavi normalizzate (minuscole, senza spazi)."""
    if file.suffix.lower() in (".xlsx", ".xlsm"):
        foglio = openpyxl.load_workbook(file, read_only=True, data_only=True).worksheets[0]
        righe = list(foglio.iter_rows(values_only=True))
        if not righe:
            return []
        intestazione = [str(c or "").strip().lower() for c in righe[0]]
        return [dict(zip(intestazione, r, strict=False)) for r in righe[1:]]
    testo = file.read_text(encoding="utf-8-sig")
    if not testo.strip():
        return []
    prima = testo.splitlines()[0]
    lettore = csv.DictReader(
        testo.splitlines(), delimiter=";" if prima.count(";") >= prima.count(",") else ","
    )
    return [{(k or "").strip().lower(): v for k, v in r.items()} for r in lettore]


def _colonna(righe: list[dict], nome: str) -> str:
    presenti = set(righe[0]) if righe else set()
    for alias in COLONNE[nome]:
        if alias in presenti:
            return alias
    raise CommandError(f"Colonna mancante: {nome} (oppure {', '.join(COLONNE[nome][1:])}).")


class Command(BaseCommand):
    help = "Compila la data di emissione dei contratti da un file CSV o XLSX."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Nessuna scrittura.")

    def handle(self, *args, file: Path, dry_run, **options):
        if not file.is_file():
            raise CommandError(f"File non trovato: {file}")
        righe = _righe(file)
        if not righe:
            raise CommandError("Il file non contiene righe.")
        col_numero, col_data = (
            _colonna(righe, "numero_contratto"),
            _colonna(righe, "data_emissione"),
        )

        # Prima si legge tutto il file: righe illeggibili e date contrastanti per lo stesso
        # numero si segnalano senza applicare nulla di quel numero.
        date: dict[str, set[datetime.date]] = defaultdict(set)
        problemi: list[str] = []
        for n, r in enumerate(righe, start=2):
            numero = _numero(r.get(col_numero))
            if numero is None and not r.get(col_data):
                continue
            try:
                data = _data(r.get(col_data))
            except ValueError as exc:
                problemi.append(f"Riga {n}: data non valida ({exc}).")
                continue
            if numero is None or data is None:
                problemi.append(f"Riga {n}: numero di contratto o data mancante.")
                continue
            date[numero].add(data)
        for numero, insieme in sorted(date.items()):
            if len(insieme) > 1:
                elenco = ", ".join(f"{d:%d/%m/%Y}" for d in sorted(insieme))
                problemi.append(f"{numero}: date diverse nel file ({elenco}), non applicate.")

        conteggi = {"compilati": 0, "invariati": 0, "discordanti": 0, "non_trovati": 0}
        dettagli: list[str] = []
        try:
            with transaction.atomic():
                for numero, insieme in sorted(date.items()):
                    if len(insieme) > 1:
                        continue
                    (data,) = insieme
                    contratti = list(Contratto.objects.filter(numero_contratto=numero))
                    if not contratti:
                        conteggi["non_trovati"] += 1
                        dettagli.append(f"{numero}: nessun contratto con questo numero.")
                        continue
                    if len(contratti) > 1:
                        dettagli.append(
                            f"{numero}: {len(contratti)} contratti con lo stesso numero "
                            "(ordine pluriennale o da verificare)."
                        )
                    for c in contratti:
                        if c.data_emissione == data:
                            conteggi["invariati"] += 1
                        elif c.data_emissione is None:
                            c.data_emissione = data
                            c._change_reason = MOTIVO
                            c.save(update_fields=["data_emissione"])
                            conteggi["compilati"] += 1
                        else:
                            conteggi["discordanti"] += 1
                            dettagli.append(
                                f"{numero} (id {c.pk}): registrata {c.data_emissione:%d/%m/%Y}, "
                                f"nel file {data:%d/%m/%Y}. Non modificata."
                            )
                if dry_run:
                    raise _Rollback
        except _Rollback:
            pass

        prefisso = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefisso}Date compilate: {conteggi['compilati']}, già uguali: "
            f"{conteggi['invariati']}, discordanti: {conteggi['discordanti']}, numeri non "
            f"trovati: {conteggi['non_trovati']}, problemi nel file: {len(problemi)}."
        )
        for riga in problemi + dettagli:
            self.stdout.write(f"  - {riga}")
