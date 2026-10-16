"""Fatturato pregresso dei contratti, da un foglio con il totale per anno (SPEC §4, Rev20).

File CSV o XLSX (primo foglio) con le colonne ``numero_contratto`` (oppure ``id_contratto``,
l'identificativo che compare nell'indirizzo della pagina del contratto), ``anno``,
``fatturato`` (imponibile, IVA esclusa) e, facoltativa, ``nota``.

Una riga per contratto e anno. Idempotente: lo stesso anno già registrato con lo stesso importo
non cambia; con un importo diverso si corregge (storia tracciata). Le righe che non si possono
applicare (contratto non trovato o ambiguo, anno o importo illeggibili, anno ripetuto nel
file) vanno nel report e non scrivono nulla; le altre si importano.
"""

from pathlib import Path

from django.db import transaction

from contratti.importer import normalizza, tabelle
from contratti.importer.report import Report
from contratti.models import Contratto, FatturatoPregresso

ALIAS_NUMERO = ("numero_contratto", "contratto", "numero contratto")
ALIAS_ID = ("id_contratto", "id")
ALIAS_ANNO = ("anno",)
ALIAS_IMPORTO = ("fatturato", "importo", "fatturato totale")
ALIAS_NOTA = ("nota", "note")
MOTIVO = "Fatturato pregresso da import"
FOGLIO = "Fatturato"


class _Rollback(Exception):
    pass


def _anno(valore) -> int | None:
    try:
        anno = int(float(str(valore).strip().replace(",", ".")))
    except ValueError:
        return None
    return anno if 2000 <= anno <= 2100 else None


def importa_pregresso(percorso: str | Path, *, dry_run: bool = False, contratti=None) -> Report:
    """``contratti``: queryset dei contratti che l'utente può modificare (default: tutti)."""
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    tabella = tabelle.righe(percorso, foglio=FOGLIO)
    if not tabella:
        raise tabelle.FileNonValido("Il file non contiene righe.")
    presenti = set(tabella[0])
    col_numero = next((a for a in ALIAS_NUMERO if a in presenti), None)
    col_id = next((a for a in ALIAS_ID if a in presenti), None)
    if col_numero is None and col_id is None:
        raise tabelle.FileNonValido("Colonna mancante: numero_contratto (oppure id_contratto).")
    col_anno = tabelle.colonna(tabella, "anno", ALIAS_ANNO)
    col_importo = tabelle.colonna(tabella, "fatturato", ALIAS_IMPORTO)
    col_nota = next((a for a in ALIAS_NOTA if a in presenti), None)
    for chiave in ("creati", "corretti", "invariati", "scartati"):
        report.conteggi[chiave] = 0

    ammessi = Contratto.objects.all() if contratti is None else contratti
    visti: dict[tuple[int, int], int] = {}
    da_scrivere = []
    for n, r in enumerate(tabella, start=2):
        riferimento = _riferimento(r, col_numero, col_id)
        anno = _anno(r.get(col_anno))
        importo, problemi = normalizza.importo(r.get(col_importo), "fatturato")
        if riferimento is None and anno is None and importo is None:
            continue

        def scarta(codice, campo, valore, messaggio, n=n):
            report.conteggi["scartati"] += 1
            report.anomalia(FOGLIO, n, codice, campo, valore, f"Riga {n}: {messaggio}")

        if anno is None:
            scarta("ANNO_NON_VALIDO", "anno", r.get(col_anno) or "", "anno non valido.")
        elif importo is None or problemi or importo < 0:
            scarta("IMPORTO_NON_VALIDO", "fatturato", r.get(col_importo) or "",
                   "fatturato mancante o non valido.")  # fmt: skip
        elif riferimento is None:
            scarta("CONTRATTO_MANCANTE", "numero_contratto", "", "contratto non indicato.")
        else:
            contratto, motivo = _trova(riferimento, ammessi)
            if contratto is None:
                scarta(*motivo)
            elif (contratto.pk, anno) in visti:
                scarta("ANNO_RIPETUTO", "anno", anno,
                       f"anno {anno} già nella riga {visti[(contratto.pk, anno)]} per lo "
                       "stesso contratto.")  # fmt: skip
            else:
                visti[(contratto.pk, anno)] = n
                nota = str(r.get(col_nota) or "").strip() if col_nota else ""
                da_scrivere.append((contratto, anno, importo, nota))

    try:
        with transaction.atomic():
            for contratto, anno, importo, nota in da_scrivere:
                _applica(report, contratto, anno, importo, nota)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


def _riferimento(r: dict, col_numero, col_id) -> tuple[str, str] | None:
    if col_id and (valore := tabelle.codice(r.get(col_id))):
        return ("id", valore)
    if col_numero and (valore := tabelle.codice(r.get(col_numero))):
        return ("numero", valore)
    return None


def _trova(riferimento: tuple[str, str], ammessi):
    tipo, valore = riferimento
    if tipo == "id":
        if not valore.isdigit():
            return None, ("CONTRATTO_NON_TROVATO", "id_contratto", valore,
                          f"{valore}: id non valido.")  # fmt: skip
        trovati = list(ammessi.filter(pk=int(valore), archiviato=False))
        esiste = Contratto.objects.filter(pk=int(valore), archiviato=False).exists()
    else:
        trovati = list(ammessi.filter(numero_contratto=valore, archiviato=False))
        esiste = Contratto.objects.filter(numero_contratto=valore, archiviato=False).exists()
    if not trovati and esiste:
        return None, ("FUORI_CLUSTER", "numero_contratto", valore,
                      f"{valore}: contratto di un cluster non tuo, non modificato.")  # fmt: skip
    if not trovati:
        return None, ("CONTRATTO_NON_TROVATO", "numero_contratto", valore,
                      f"{valore}: nessun contratto con questo numero.")  # fmt: skip
    if len(trovati) > 1:
        return None, ("NUMERO_SU_PIU_CONTRATTI", "numero_contratto", valore,
                      f"{valore}: {len(trovati)} contratti con lo stesso numero; "
                      "usa la colonna id_contratto.")  # fmt: skip
    return trovati[0], None


def _applica(report: Report, contratto, anno: int, importo, nota: str) -> None:
    esistente = FatturatoPregresso.objects.filter(
        contratto=contratto, anno=anno, archiviato=False
    ).first()
    if esistente is None:
        riga = FatturatoPregresso(contratto=contratto, anno=anno, importo=importo, note=nota)
        riga._change_reason = MOTIVO
        riga.save()
        report.conteggi["creati"] += 1
    elif esistente.importo == importo and (not nota or esistente.note == nota):
        report.conteggi["invariati"] += 1
    else:
        esistente.importo = importo
        if nota:
            esistente.note = nota
        esistente._change_reason = MOTIVO
        esistente.save()
        report.conteggi["corretti"] += 1
