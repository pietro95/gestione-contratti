"""Import settimanale delle fatture dall'estrazione SAP (SPEC §7, Rev15; TC-18).

Primo foglio; l'intestazione è la riga che contiene «Fornitore» e «Numero Documento» (sopra
può esserci la riga di revisione). Si leggono solo ``Fornitore``, ``Numero Documento``,
``Data`` e ``Importo SAP``: le altre colonne si ignorano, anche se compilate.

- Una riga senza numero, data e importo non è una fattura (righe vuote, legenda in fondo): si
  ignora. Compilata solo in parte va nel report (``RIGA_INCOMPLETA``).
- Fornitore riconosciuto per ragione sociale o nome breve (stessa normalizzazione dell'import
  dei contratti); se non c'è in anagrafica si crea sul momento, con la ragione sociale del file,
  e si segnala (``FORNITORE_CREATO``, da verificare). Un nome che corrisponde a più fornitori
  non si importa (``FORNITORE_NON_TROVATO``). Il fornitore si crea solo per righe valide.
- Numero conservato come scritto; con testo aggiunto si importa ed è segnalato
  (``NUMERO_DA_VERIFICARE``).
- La fattura entra da prendere in carico, senza referente e senza contratto: il contratto e il
  referente proposti si calcolano, non si salvano.
- Fornitore + numero già registrati: nessun duplicato; importo o data diversi si segnalano
  (``IMPORTO_DIVERSO``, ``DATA_DIVERSA``) senza sovrascrivere.
"""

import datetime
import re
from pathlib import Path

import openpyxl
from django.db import transaction
from django.utils import timezone

from contratti import models as m
from contratti.importer import normalizza
from contratti.importer.report import Report
from contratti.importer.tabelle import FileNonValido

COLONNE = {
    "fornitore": ("fornitore",),
    "numero": ("numero documento", "numero"),
    "data": ("data", "data documento"),
    "importo": ("importo sap", "importo"),
}
# Un numero con testo aggiunto (es. «76 In attesa di nota credito»).
RE_TESTO_AGGIUNTO = re.compile(r"\s[^\W\d_]{3,}")
FORMATI_DATA = ("%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d")
RIGHE_MASSIME_INTESTAZIONE = 20


class _Rollback(Exception):
    pass


def _norma(valore) -> str:
    return " ".join(str(valore or "").replace("?", " ").split()).casefold()


def _intestazione(righe: list[tuple]) -> tuple[int, dict[str, int]]:
    """Indice della riga d'intestazione e posizione delle colonne lette."""
    for i, riga in enumerate(righe[:RIGHE_MASSIME_INTESTAZIONE]):
        celle = [_norma(c) for c in riga]
        if "fornitore" in celle and "numero documento" in celle:
            posizioni = {}
            for campo, alias in COLONNE.items():
                trovata = next((celle.index(a) for a in alias if a in celle), None)
                if trovata is None:
                    raise FileNonValido(f"Colonna mancante: «{alias[0].title()}».")
                posizioni[campo] = trovata
            return i, posizioni
    raise FileNonValido(
        "Intestazione non trovata: serve una riga con «Fornitore» e «Numero Documento»."
    )


def data_documento(valore) -> datetime.date | None:
    if isinstance(valore, datetime.datetime):
        return valore.date()
    if isinstance(valore, datetime.date):
        return valore
    s = normalizza.testo(valore)
    if s is None:
        return None
    for formato in FORMATI_DATA:
        try:
            return datetime.datetime.strptime(s, formato).date()
        except ValueError:
            continue
    return None


def _fornitori() -> dict[str, list[m.Fornitore]]:
    indice: dict[str, list[m.Fornitore]] = {}
    for f in m.Fornitore.objects.filter(archiviato=False):
        for nome in {f.ragione_sociale, f.nome_breve}:
            k = normalizza.chiave_nome(nome)
            if k and f not in indice.setdefault(k, []):
                indice[k].append(f)
    return indice


def _leggi(percorso: Path) -> tuple[str, list[tuple]]:
    try:
        wb = openpyxl.load_workbook(percorso, read_only=True, data_only=True)
    except Exception as exc:
        raise FileNonValido(f"Il file non è un Excel leggibile ({exc}).") from exc
    ws = wb.worksheets[0]
    return ws.title, list(ws.iter_rows(values_only=True))


def _cella(riga: tuple, posizione: int):
    return riga[posizione] if posizione < len(riga) else None


def importa_fatture(
    percorso: str | Path, *, dry_run: bool = False, oggi: datetime.date | None = None
) -> Report:
    percorso = Path(percorso)
    oggi = oggi or timezone.localdate()
    report = Report(file=percorso.name, dry_run=dry_run)
    for chiave in ("righe_lette", "create", "gia_presenti", "non_importate",
                   "con_contratto_proposto", "fornitori_creati"):  # fmt: skip
        report.conteggi[chiave] = 0
    foglio, righe = _leggi(percorso)
    inizio, col = _intestazione(righe)
    try:
        with transaction.atomic():
            _importa(report, foglio, righe, inizio, col, oggi)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


def _importa(report, foglio, righe, inizio, col, oggi) -> None:
    from contratti import fatture as servizi

    fornitori = _fornitori()
    create = []
    for n, riga in enumerate(righe[inizio + 1 :], start=inizio + 2):
        grezzi = {campo: _cella(riga, p) for campo, p in col.items()}
        nome = normalizza.testo(grezzi["fornitore"])
        numero = normalizza.testo(grezzi["numero"])
        if numero is None and all(normalizza.testo(grezzi[c]) is None for c in ("data", "importo")):
            continue  # riga vuota o legenda
        report.conteggi["righe_lette"] += 1

        def scarta(codice, campo, valore, messaggio, *, _n=n):
            report.anomalia(foglio, _n, codice, campo, valore or "", messaggio)
            report.conteggi["non_importate"] += 1

        mancanti = [c for c, v in (("fornitore", nome), ("numero", numero)) if v is None]
        mancanti += [c for c in ("data", "importo") if normalizza.testo(grezzi[c]) is None]
        if mancanti:
            scarta("RIGA_INCOMPLETA", ", ".join(mancanti), numero or nome,
                   "Riga compilata solo in parte: non importata.")  # fmt: skip
            continue
        data = data_documento(grezzi["data"])
        if data is None:
            scarta("DATA_NON_LEGGIBILE", "data", str(grezzi["data"]),
                   "Data non leggibile (gg.mm.aaaa, gg.mm.aa o gg/mm/aaaa).")  # fmt: skip
            continue
        importo, problemi = normalizza.importo(grezzi["importo"], "importo")
        if importo is None or problemi:
            scarta("IMPORTO_NON_LEGGIBILE", "importo", str(grezzi["importo"]),
                   "Importo non leggibile.")  # fmt: skip
            continue
        if importo < 0:
            scarta("IMPORTO_NEGATIVO", "importo", str(importo),
                   "Importo negativo (nota di credito?): si registra a mano.")  # fmt: skip
            continue
        chiave = normalizza.chiave_nome(nome)
        candidati = fornitori.get(chiave, [])
        if len(candidati) > 1:
            scarta("FORNITORE_NON_TROVATO", "fornitore", nome,
                   "Nome di più fornitori: si registra a mano.")  # fmt: skip
            continue
        if len(numero) > m.Fattura._meta.get_field("numero").max_length:
            scarta("NUMERO_TROPPO_LUNGO", "numero", numero, "Numero oltre 60 caratteri.")
            continue
        if candidati:
            fornitore = candidati[0]
        elif not chiave:
            scarta("FORNITORE_NON_TROVATO", "fornitore", nome, "Nome del fornitore non valido.")
            continue
        else:
            # Fornitore non in anagrafica: si crea sul momento (solo per righe valide).
            campo = m.Fornitore._meta.get_field("ragione_sociale")
            fornitore = m.Fornitore.objects.create(ragione_sociale=nome[: campo.max_length])
            fornitori[chiave] = [fornitore]
            report.conteggi["fornitori_creati"] += 1
            report.anomalia(foglio, n, "FORNITORE_CREATO", "fornitore", nome,
                            "Fornitore non in anagrafica: creato, da verificare.")  # fmt: skip
        esistente = m.Fattura.objects.filter(
            fornitore=fornitore, numero=numero, archiviato=False
        ).first()
        if esistente is not None:
            report.conteggi["gia_presenti"] += 1
            if esistente.importo_documento != importo:
                report.anomalia(
                    foglio, n, "IMPORTO_DIVERSO", "importo", str(importo),
                    f"Fattura {numero} già registrata con {esistente.importo_documento}: "
                    "non modificata.",
                )  # fmt: skip
            if esistente.data != data:
                report.anomalia(
                    foglio, n, "DATA_DIVERSA", "data", f"{data:%d/%m/%Y}",
                    f"Fattura {numero} già registrata con data {esistente.data:%d/%m/%Y}: "
                    "non modificata.",
                )  # fmt: skip
            continue
        if RE_TESTO_AGGIUNTO.search(numero):
            report.anomalia(
                foglio, n, "NUMERO_DA_VERIFICARE", "numero", numero,
                "Numero con testo aggiunto: importato com'è, da verificare.",
            )  # fmt: skip
        fattura = m.Fattura(
            fornitore=fornitore,
            numero=numero,
            data=data,
            importo_documento=importo,
            data_registrazione=oggi,
        )
        fattura._change_reason = "Import settimanale delle fatture"
        fattura.save()
        create.append(fattura)
        report.conteggi["create"] += 1
    proposti = servizi.contratti_proposti(create)
    report.conteggi["con_contratto_proposto"] = sum(1 for c in proposti.values() if c)
