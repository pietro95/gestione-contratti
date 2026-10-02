"""Date di emissione dei contratti già registrati, da un'estrazione SAP (F8).

File CSV o XLSX (primo foglio) con le colonne numero_contratto (oppure contratto) e
data_emissione (oppure data). Riempie solo le date vuote: una data già presente e diversa
non si tocca e va nel report come discordanza. Rieseguire l'import non cambia nulla.
"""

import datetime
from collections import defaultdict
from pathlib import Path

from django.db import transaction

from contratti.importer import tabelle
from contratti.importer.report import Report
from contratti.models import Contratto

ALIAS_NUMERO = ("numero_contratto", "contratto", "numero contratto")
ALIAS_DATA = ("data_emissione", "data", "data emissione")
MOTIVO = "Data di emissione da import"
FOGLIO = "Date"
# Codici delle anomalie che riguardano il file, non i contratti registrati.
PROBLEMI_FILE = ("DATA_NON_VALIDA", "DATI_MANCANTI", "DATE_CONTRASTANTI")


class _Rollback(Exception):
    pass


def importa_date(percorso: str | Path, *, dry_run: bool = False, contratti=None) -> Report:
    """``contratti``: queryset dei contratti che l'utente può modificare (default: tutti)."""
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    tabella = tabelle.righe(percorso, foglio=FOGLIO)
    if not tabella:
        raise tabelle.FileNonValido("Il file non contiene righe.")
    col_numero = tabelle.colonna(tabella, "numero_contratto", ALIAS_NUMERO)
    col_data = tabelle.colonna(tabella, "data_emissione", ALIAS_DATA)
    for chiave in ("compilati", "invariati", "discordanti", "non_trovati", "fuori_cluster"):
        report.conteggi[chiave] = 0

    # Prima si legge tutto il file: righe illeggibili e date contrastanti per lo stesso
    # numero si segnalano senza applicare nulla di quel numero.
    date: dict[str, set[datetime.date]] = defaultdict(set)
    for n, r in enumerate(tabella, start=2):
        numero = tabelle.codice(r.get(col_numero))
        if numero is None and not r.get(col_data):
            continue
        try:
            data = tabelle.data(r.get(col_data))
        except ValueError as exc:
            report.anomalia(FOGLIO, n, "DATA_NON_VALIDA", "data_emissione", exc,
                            f"Riga {n}: data non valida ({exc}).")  # fmt: skip
            continue
        if numero is None or data is None:
            report.anomalia(FOGLIO, n, "DATI_MANCANTI", "", "",
                            f"Riga {n}: numero di contratto o data mancante.")  # fmt: skip
            continue
        date[numero].add(data)
    for numero, insieme in sorted(date.items()):
        if len(insieme) > 1:
            elenco = ", ".join(f"{d:%d/%m/%Y}" for d in sorted(insieme))
            messaggio = f"{numero}: date diverse nel file ({elenco}), non applicate."
            report.anomalia(
                FOGLIO, None, "DATE_CONTRASTANTI", "numero_contratto", numero, messaggio
            )

    ammessi = Contratto.objects.all() if contratti is None else contratti
    try:
        with transaction.atomic():
            for numero, insieme in sorted(date.items()):
                if len(insieme) == 1:
                    _applica(report, numero, next(iter(insieme)), ammessi)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


def _applica(report: Report, numero: str, data: datetime.date, ammessi) -> None:
    trovati = list(ammessi.filter(numero_contratto=numero))
    if not trovati and Contratto.objects.filter(numero_contratto=numero).exists():
        report.conteggi["fuori_cluster"] += 1
        report.anomalia(FOGLIO, None, "FUORI_CLUSTER", "numero_contratto", numero,
                        f"{numero}: contratto di un cluster non tuo, non modificato.")  # fmt: skip
        return
    if not trovati:
        report.conteggi["non_trovati"] += 1
        report.anomalia(FOGLIO, None, "NUMERO_NON_TROVATO", "numero_contratto", numero,
                        f"{numero}: nessun contratto con questo numero.")  # fmt: skip
        return
    if len(trovati) > 1:
        report.anomalia(
            FOGLIO, None, "NUMERO_SU_PIU_CONTRATTI", "numero_contratto", numero,
            f"{numero}: {len(trovati)} contratti con lo stesso numero "
            "(ordine pluriennale o da verificare).",
        )  # fmt: skip
    for c in trovati:
        if c.data_emissione == data:
            report.conteggi["invariati"] += 1
        elif c.data_emissione is None:
            c.data_emissione = data
            c._change_reason = MOTIVO
            c.save(update_fields=["data_emissione"])
            report.conteggi["compilati"] += 1
        else:
            report.conteggi["discordanti"] += 1
            report.anomalia(
                FOGLIO, None, "DATA_DISCORDANTE", "data_emissione", f"{data:%d/%m/%Y}",
                f"{numero} (id {c.pk}): registrata {c.data_emissione:%d/%m/%Y}, "
                f"nel file {data:%d/%m/%Y}. Non modificata.",
            )  # fmt: skip
