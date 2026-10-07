"""Tabelle SAP del processo d'acquisto da Excel (SPEC §7, Rev13): richiedenti, gruppi merci,
gruppi acquisti.

Un foglio per tabella (``Richiedenti``, ``Gruppi merci``, ``Gruppi acquisti``; almeno uno),
colonne ``codice``, ``descrizione`` (per i gruppi acquisti anche ``nome``), ``predefinito``
(sì/no) e, per i gruppi merci, ``categoria`` facoltativa (nome della categoria di fabbisogno).

- Tutto o niente; idempotente per codice; nessuna cancellazione: un codice assente dal file
  resta com'è (si disattiva dall'amministrazione).
- Un codice del file aggiorna descrizione e, se la colonna c'è, categoria.
- Un foglio con un predefinito lo rende l'unico predefinito della tabella; senza predefiniti
  nel foglio il predefinito registrato resta.
- Errori bloccanti: più predefiniti nello stesso foglio, codici doppi, categorie inesistenti,
  valori di «predefinito» illeggibili, codice mancante.
"""

from dataclasses import dataclass
from pathlib import Path

import openpyxl
from django.db import transaction

from contratti import models as m
from contratti.importer import tabelle
from contratti.importer.report import Report


@dataclass(frozen=True)
class Foglio:
    nome: str
    chiave: str  # prefisso dei conteggi
    modello: type
    alias_descrizione: tuple[str, ...] = ("descrizione",)
    con_categoria: bool = False


FOGLI = (
    Foglio("Richiedenti", "richiedenti", m.RichiedenteSAP),
    Foglio("Gruppi merci", "gruppi_merci", m.GruppoMerci, con_categoria=True),
    Foglio("Gruppi acquisti", "gruppi_acquisti", m.GruppoAcquisti, ("nome", "descrizione")),
)
SI = {"si", "sì", "s", "x", "1", "true", "vero", "yes", "y"}
NO = {"", "no", "n", "0", "false", "falso"}


class _Rollback(Exception):
    pass


def _fogli(percorso: Path) -> dict[str, list[dict]]:
    """Righe dei fogli riconosciuti (nome senza maiuscole e spazi ai lati)."""
    try:
        wb = openpyxl.load_workbook(percorso, read_only=True, data_only=True)
    except Exception as exc:
        raise tabelle.FileNonValido(f"Il file non è un Excel leggibile ({exc}).") from exc
    nomi = {ws.title.strip().lower(): ws for ws in wb.worksheets}
    risultato = {}
    for foglio in FOGLI:
        ws = nomi.get(foglio.nome.lower())
        if ws is None:
            continue
        tutte = list(ws.iter_rows(values_only=True))
        if not tutte:
            risultato[foglio.nome] = []
            continue
        intestazione = [str(c or "").strip().lower() for c in tutte[0]]
        risultato[foglio.nome] = [
            {"_riga": n, **dict(zip(intestazione, r, strict=False))}
            for n, r in enumerate(tutte[1:], start=2)
            if any(v not in (None, "") for v in r)
        ]
    if not risultato:
        attesi = ", ".join(f"«{f.nome}»" for f in FOGLI)
        raise tabelle.FileNonValido(f"Nessun foglio riconosciuto: servono {attesi}.")
    return risultato


def _si_no(valore, foglio: str, riga: int) -> bool:
    testo = str(valore if valore is not None else "").strip().lower()
    if isinstance(valore, bool):
        return valore
    if testo in SI:
        return True
    if testo in NO:
        return False
    raise tabelle.FileNonValido(f"{foglio}, riga {riga}: «predefinito» non leggibile ({valore}).")


def importa_tabelle_sap(percorso: str | Path, *, dry_run: bool = False) -> Report:
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    fogli = _fogli(percorso)
    for foglio in FOGLI:
        for esito in ("creati", "aggiornati", "invariati"):
            report.conteggi[f"{foglio.chiave}_{esito}"] = 0
    try:
        with transaction.atomic():
            for foglio in FOGLI:
                if foglio.nome in fogli:
                    _importa_foglio(report, foglio, fogli[foglio.nome])
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


def _leggi(foglio: Foglio, righe: list[dict]) -> list[dict]:
    """Controlli bloccanti sul foglio intero, prima di scrivere."""
    presenti = set(righe[0]) if righe else set()
    if righe and "codice" not in presenti:
        raise tabelle.FileNonValido(f"{foglio.nome}: colonna mancante: codice.")
    colonna_descrizione = next((a for a in foglio.alias_descrizione if a in presenti), None)
    lette, codici, predefiniti = [], set(), []
    for r in righe:
        n = r["_riga"]
        codice = tabelle.codice(r.get("codice"))
        if codice is None:
            raise tabelle.FileNonValido(f"{foglio.nome}, riga {n}: codice mancante.")
        if codice in codici:
            raise tabelle.FileNonValido(f"{foglio.nome}, riga {n}: codice ripetuto ({codice}).")
        codici.add(codice)
        predefinito = _si_no(r.get("predefinito"), foglio.nome, n)
        if predefinito:
            predefiniti.append(codice)
        letta = {
            "riga": n,
            "codice": codice,
            "descrizione": (
                str(r.get(colonna_descrizione) or "").strip()[:200] if colonna_descrizione else None
            ),
            "predefinito": predefinito,
        }
        if foglio.con_categoria and "categoria" in presenti:
            nome = str(r.get("categoria") or "").strip()
            categoria = None
            if nome:
                categoria = m.Categoria.objects.filter(nome__iexact=nome).first()
                if categoria is None:
                    raise tabelle.FileNonValido(
                        f"{foglio.nome}, riga {n}: categoria inesistente ({nome})."
                    )
            letta["categoria"] = categoria
        lette.append(letta)
    if len(predefiniti) > 1:
        raise tabelle.FileNonValido(
            f"{foglio.nome}: un solo predefinito per foglio (indicati: {', '.join(predefiniti)})."
        )
    return lette


def _importa_foglio(report: Report, foglio: Foglio, righe: list[dict]) -> None:
    lette = _leggi(foglio, righe)
    modello = foglio.modello
    nuovo_predefinito = next((r["codice"] for r in lette if r["predefinito"]), None)
    if nuovo_predefinito is not None:
        # Prima si toglie il vecchio predefinito: il vincolo ne ammette uno solo.
        for vecchio in modello.objects.filter(predefinito=True).exclude(codice=nuovo_predefinito):
            vecchio.predefinito = False
            vecchio.save(update_fields=["predefinito"])
    for r in lette:
        oggetto = modello.objects.filter(codice=r["codice"]).first()
        esito = "aggiornati"
        if oggetto is None:
            oggetto, esito = modello(codice=r["codice"]), "creati"
        prima = (oggetto.descrizione, getattr(oggetto, "categoria_id", None), oggetto.predefinito)
        if r["descrizione"] is not None:
            oggetto.descrizione = r["descrizione"]
        if "categoria" in r:
            oggetto.categoria = r["categoria"]
        if r["predefinito"]:
            oggetto.predefinito = True
        dopo = (oggetto.descrizione, getattr(oggetto, "categoria_id", None), oggetto.predefinito)
        if esito == "aggiornati" and prima == dopo:
            report.conteggi[f"{foglio.chiave}_invariati"] += 1
            continue
        oggetto.save()
        report.conteggi[f"{foglio.chiave}_{esito}"] += 1
