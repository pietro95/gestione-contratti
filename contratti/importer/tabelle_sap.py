"""Tabelle SAP del processo d'acquisto da Excel (SPEC §7, Rev13): richiedenti, gruppi merci,
gruppi acquisti, centri di costo.

Il modello ha un foglio per tabella (``Richiedenti``, ``Gruppi merci``, ``Gruppi acquisti``,
``Centri di costo``; almeno uno), colonne ``codice``, ``descrizione`` (per i gruppi acquisti
anche ``nome``), ``predefinito`` (sì/no). Una colonna ``categoria`` dei vecchi modelli si ignora.

Si leggono anche i due elenchi di SAP così come arrivano, riconosciuti dall'intestazione (in
una delle prime righe, in qualsiasi foglio):
- **gruppi merci**: «Gruppo Merci», «Definizione» (breve), «Definizione» (lunga): descrizione
  lunga, o la breve se manca;
- **codici di rilascio**: «Unità», «Richiedente», «Gr Acquisti …», «Responsabile»: per ogni
  unità il richiedente e il gruppo acquisti, con l'unità come descrizione, legati fra loro (il
  gruppo si propone con il richiedente). Il responsabile non si importa. La riga dell'unità
  ICTDINN diventa predefinita se la tabella non ha già un predefinito.

- Tutto o niente; idempotente per codice; nessuna cancellazione: un codice assente dal file
  resta com'è (si disattiva dall'amministrazione).
- Un codice del file aggiorna la descrizione.
- Un foglio con un predefinito lo rende l'unico predefinito della tabella; senza predefiniti
  nel foglio il predefinito registrato resta.
- Errori bloccanti: più predefiniti nello stesso foglio, codici doppi,
  valori di «predefinito» illeggibili, codice mancante.
"""

import unicodedata
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


FOGLI = (
    Foglio("Richiedenti", "richiedenti", m.RichiedenteSAP),
    Foglio("Gruppi merci", "gruppi_merci", m.GruppoMerci),
    Foglio("Gruppi acquisti", "gruppi_acquisti", m.GruppoAcquisti, ("nome", "descrizione")),
    Foglio("Centri di costo", "centri_costo", m.CentroCosto),
)
PER_NOME = {f.nome: f for f in FOGLI}
UNITA_PREDEFINITA = "ictdinn"  # l'ufficio del registro: la sua riga è il predefinito proposto
RIGHE_INTESTAZIONE = 10  # l'intestazione degli elenchi SAP sta in una delle prime righe
SI = {"si", "sì", "s", "x", "1", "true", "vero", "yes", "y"}
NO = {"", "no", "n", "0", "false", "falso"}


class _Rollback(Exception):
    pass


def _normale(valore) -> str:
    """Intestazione confrontabile: minuscole, senza accenti e spazi doppi."""
    testo = unicodedata.normalize("NFKD", str(valore or "")).encode("ascii", "ignore").decode()
    return " ".join(testo.lower().split())


def _righe(tutte: list[tuple], dopo: int, colonne: dict[str, int]) -> list[dict]:
    """Righe non vuote dopo l'intestazione, con le colonne indicate (nome → indice)."""
    righe = []
    for n, r in enumerate(tutte[dopo + 1 :], start=dopo + 2):
        valori = {k: (r[i] if i < len(r) else None) for k, i in colonne.items()}
        if any(v not in (None, "") for v in valori.values()):
            righe.append({"_riga": n, **valori})
    return righe


def _elenco_sap(tutte: list[tuple]) -> tuple[str, list[dict]] | None:
    """Gruppi merci o codici di rilascio di SAP, riconosciuti dall'intestazione."""
    for i, riga in enumerate(tutte[:RIGHE_INTESTAZIONE]):
        celle = [_normale(c) for c in riga]
        if "gruppo merci" in celle and "definizione" in celle:
            definizioni = [j for j, c in enumerate(celle) if c == "definizione"]
            colonne = {"codice": celle.index("gruppo merci"), "breve": definizioni[0],
                       "lunga": definizioni[-1]}  # fmt: skip
            return "gruppi_merci", _righe(tutte, i, colonne)
        acquisti = [j for j, c in enumerate(celle) if c.startswith("gr") and "acquist" in c]
        if "unita" in celle and "richiedente" in celle and acquisti:
            colonne = {"unita": celle.index("unita"), "richiedente": celle.index("richiedente"),
                       "gruppo": acquisti[0]}  # fmt: skip
            return "rilascio", _righe(tutte, i, colonne)
    return None


def _fogli(percorso: Path) -> tuple[dict[str, list[dict]], list[tuple[str, str, list[dict]]]]:
    """Righe dei fogli del modello (per nome) e degli elenchi SAP (per intestazione)."""
    try:
        wb = openpyxl.load_workbook(percorso, read_only=True, data_only=True)
    except Exception as exc:
        raise tabelle.FileNonValido(f"Il file non è un Excel leggibile ({exc}).") from exc
    del_modello = {f.nome.lower() for f in FOGLI}
    risultato, elenchi = {}, []
    for ws in wb.worksheets:
        nome = ws.title.strip().lower()
        tutte = list(ws.iter_rows(values_only=True))
        if nome in del_modello:
            foglio = next(f for f in FOGLI if f.nome.lower() == nome)
            if not tutte:
                risultato[foglio.nome] = []
                continue
            intestazione = [str(c or "").strip().lower() for c in tutte[0]]
            risultato[foglio.nome] = [
                {"_riga": n, **dict(zip(intestazione, r, strict=False))}
                for n, r in enumerate(tutte[1:], start=2)
                if any(v not in (None, "") for v in r)
            ]
        elif (elenco := _elenco_sap(tutte)) is not None:
            elenchi.append((elenco[0], ws.title, elenco[1]))
    if not risultato and not elenchi:
        attesi = ", ".join(f"«{f.nome}»" for f in FOGLI)
        raise tabelle.FileNonValido(
            f"Nessun foglio riconosciuto: servono {attesi}, oppure l'elenco SAP dei gruppi "
            "merci («Gruppo Merci», «Definizione») o dei codici di rilascio («Unità», "
            "«Richiedente», «Gr Acquisti»)."
        )
    return risultato, elenchi


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
    fogli, elenchi = _fogli(percorso)
    for foglio in FOGLI:
        for esito in ("creati", "aggiornati", "invariati"):
            report.conteggi[f"{foglio.chiave}_{esito}"] = 0
    report.conteggi["richiedenti_collegati"] = 0
    try:
        with transaction.atomic():
            for foglio in FOGLI:
                if foglio.nome in fogli:
                    _importa_foglio(report, foglio, fogli[foglio.nome])
            if "Centri di costo" in fogli:
                _centri_non_in_tabella(report)
            for tipo, titolo, righe in elenchi:
                if tipo == "gruppi_merci":
                    _importa_gruppi_merci(report, righe)
                else:
                    _importa_rilascio(report, titolo, righe)
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
        prima = (oggetto.descrizione, oggetto.predefinito)
        if r["descrizione"] is not None:
            oggetto.descrizione = r["descrizione"]
        if r["predefinito"]:
            oggetto.predefinito = True
        dopo = (oggetto.descrizione, oggetto.predefinito)
        if esito == "aggiornati" and prima == dopo:
            report.conteggi[f"{foglio.chiave}_invariati"] += 1
            continue
        oggetto.save()
        report.conteggi[f"{foglio.chiave}_{esito}"] += 1


# --- Elenchi di SAP così come arrivano ------------------------------------------------------


def _importa_gruppi_merci(report: Report, righe: list[dict]) -> None:
    """Elenco SAP dei gruppi merci: la definizione lunga come descrizione (o la breve)."""
    foglio = PER_NOME["Gruppi merci"]
    convertite = [
        {
            "_riga": r["_riga"],
            "codice": r["codice"],
            "descrizione": str(r.get("lunga") or "").strip() or r.get("breve"),
        }
        for r in righe
    ]
    _importa_foglio(report, foglio, convertite)


def _codice_testo(report: Report, titolo: str, r: dict, campo: str) -> str | None:
    """Un codice SAP letto come numero può aver perso gli zeri iniziali: si segnala."""
    valore = r.get(campo)
    if isinstance(valore, int | float) and not isinstance(valore, bool):
        report.anomalia(
            titolo, r["_riga"], "CODICE_NUMERICO", campo, valore,
            "Codice letto come numero: verificare gli zeri iniziali (in SAP è un testo).",
        )  # fmt: skip
    return tabelle.codice(valore)


def _importa_rilascio(report: Report, titolo: str, righe: list[dict]) -> None:
    """Codici di rilascio: per ogni unità richiedente e gruppo acquisti, legati fra loro."""
    richiedenti, gruppi, coppie, ictdinn = [], [], [], None
    visti_gruppi: set[str] = set()
    for r in righe:
        unita = " ".join(str(r.get("unita") or "").split())
        richiedente = _codice_testo(report, titolo, r, "richiedente")
        gruppo = _codice_testo(report, titolo, r, "gruppo")
        if richiedente is None:
            raise tabelle.FileNonValido(
                f"{titolo}, riga {r['_riga']}: richiedente mancante ({unita or 'senza unità'})."
            )
        if UNITA_PREDEFINITA in unita.lower():
            ictdinn = (richiedente, gruppo)
        richiedenti.append({"_riga": r["_riga"], "codice": richiedente, "descrizione": unita})
        if gruppo is not None and gruppo not in visti_gruppi:
            visti_gruppi.add(gruppo)
            gruppi.append({"_riga": r["_riga"], "codice": gruppo, "nome": unita})
        coppie.append((richiedente, gruppo))
    # Il predefinito dalla riga ICTDINN, solo se la tabella non ne ha già uno.
    if ictdinn is not None:
        for righe_tabella, modello, codice in (
            (richiedenti, m.RichiedenteSAP, ictdinn[0]),
            (gruppi, m.GruppoAcquisti, ictdinn[1]),
        ):
            if codice is not None and not modello.objects.filter(predefinito=True).exists():
                for x in righe_tabella:
                    x["predefinito"] = x["codice"] == codice
    _importa_foglio(report, PER_NOME["Gruppi acquisti"], gruppi)
    _importa_foglio(report, PER_NOME["Richiedenti"], richiedenti)
    for richiedente, gruppo in coppie:
        oggetto = m.RichiedenteSAP.objects.get(codice=richiedente)
        nuovo = m.GruppoAcquisti.objects.get(codice=gruppo) if gruppo else None
        if oggetto.gruppo_acquisti_id != (nuovo.pk if nuovo else None):
            oggetto.gruppo_acquisti = nuovo
            oggetto.save(update_fields=["gruppo_acquisti"])
            report.conteggi["richiedenti_collegati"] += 1


# --- Centri di costo già registrati e assenti dalla tabella ---------------------------------


def centri_costo_usati() -> dict[str, int]:
    """Codice → numero di voci e posizioni che lo usano (non archiviate)."""
    from collections import Counter

    usati = Counter(
        m.VoceContratto.objects.filter(archiviato=False)
        .exclude(centro_costo="")
        .values_list("centro_costo", flat=True)
    )
    usati.update(
        m.PosizioneRDA.objects.filter(rda__archiviato=False)
        .exclude(centro_costo="")
        .values_list("centro_costo", flat=True)
    )
    return dict(usati)


def _centri_non_in_tabella(report: Report) -> None:
    """Dopo il caricamento: i codici usati da voci e posizioni che la tabella non ha. Restano
    sulle voci e si sistemano scegliendo dalla tendina (SPEC §7)."""
    noti = set(m.CentroCosto.objects.values_list("codice", flat=True))
    mancanti = {c: n for c, n in centri_costo_usati().items() if c not in noti}
    report.conteggi["centri_costo_non_in_tabella"] = len(mancanti)
    for codice, n in sorted(mancanti.items()):
        report.anomalia(
            "Centri di costo", None, "CENTRO_COSTO_NON_IN_TABELLA", "centro_costo", codice,
            f"Usato da {n} voci o posizioni: aggiungerlo alla tabella o sceglierne un altro.",
        )  # fmt: skip
