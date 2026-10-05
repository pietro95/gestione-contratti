"""Piano dei conti da CSV o XLSX (SPEC §7.2: il piano dei conti precede l'import).

Colonne: codice, descrizione, valido_dal e, facoltative, valido_al e cluster (codice del
cluster, F9.2); altre colonne si ignorano. La coppia (codice, valido_dal) identifica
il conto: una riga già presente aggiorna descrizione e fine validità, mai cancellazioni.
Tutto o niente: un errore su una riga annulla il file.
"""

from pathlib import Path

from django.db import transaction

from contratti.importer import tabelle
from contratti.importer.report import Report
from contratti.models import Cluster, ContoCoge

OBBLIGATORIE = ("codice", "descrizione", "valido_dal")


class _Rollback(Exception):
    pass


def importa_conti(percorso: str | Path, *, dry_run: bool = False) -> Report:
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    tabella = tabelle.righe(percorso, foglio="Conti")
    mancanti = [c for c in OBBLIGATORIE if not tabella or c not in tabella[0]]
    if mancanti:
        raise tabelle.FileNonValido(f"Colonne mancanti: {', '.join(mancanti)}.")
    for chiave in ("creati", "aggiornati", "invariati"):
        report.conteggi[chiave] = 0
    try:
        with transaction.atomic():
            for numero, r in enumerate(tabella, start=2):
                _riga(report, numero, r)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


def _data(valore, numero, campo):
    try:
        return tabelle.data(valore)
    except ValueError as exc:
        raise tabelle.FileNonValido(f"Riga {numero}: {campo} non valida ({exc}).") from exc


def _riga(report: Report, numero: int, r: dict) -> None:
    codice = tabelle.codice(r.get("codice"))
    descrizione = str(r.get("descrizione") or "").strip()
    if codice is None and not descrizione and not r.get("valido_dal"):
        return
    if codice is None or not descrizione:
        raise tabelle.FileNonValido(f"Riga {numero}: codice e descrizione obbligatori.")
    dal = _data(r.get("valido_dal"), numero, "valido_dal")
    if dal is None:
        raise tabelle.FileNonValido(f"Riga {numero}: valido_dal obbligatoria.")
    al = _data(r.get("valido_al"), numero, "valido_al")
    codice_cluster = str(r.get("cluster") or "").strip()
    cluster = None
    if codice_cluster:
        cluster = Cluster.objects.filter(codice=codice_cluster).first()
        if cluster is None:
            raise tabelle.FileNonValido(f"Riga {numero}: cluster inesistente: {codice_cluster}.")
    conto = ContoCoge.objects.filter(codice=codice, valido_dal=dal).first()
    if conto is None:
        conto = ContoCoge(codice=codice, valido_dal=dal)
        esito = "creati"
    elif (conto.descrizione, conto.valido_al) == (descrizione, al) and (
        cluster is None or conto.cluster_id == cluster.pk
    ):
        report.conteggi["invariati"] += 1
        return
    else:
        esito = "aggiornati"
    conto.descrizione, conto.valido_al = descrizione, al
    if cluster is not None:  # colonna vuota: il cluster già registrato resta
        conto.cluster = cluster
    try:
        conto.full_clean()
    except Exception as exc:
        raise tabelle.FileNonValido(f"Riga {numero}: {exc}") from exc
    conto.save()
    report.conteggi[esito] += 1
