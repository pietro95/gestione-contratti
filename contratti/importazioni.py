"""Import dall'interfaccia (F9.1): caricamento, anteprima senza scritture, conferma.

Gli import sono gli stessi della riga di comando (stesso codice): Excel dei contratti, date
di emissione, piano dei conti, quadratura con l'Excel. Il file resta nel registro
(``Importazione``) con anteprima ed esito.
"""

import datetime
import hashlib
import io
import logging
import re
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from accounts.roles import ADMIN, WRITE_ROLES, role_of
from contratti import models as m
from contratti.importer.carica import importa as importa_excel
from contratti.importer.conti import importa_conti
from contratti.importer.date_emissione import importa_date
from contratti.importer.report import Report
from contratti.importer.tabelle import FileNonValido

log = logging.getLogger(__name__)

DIMENSIONE_MASSIMA = 10 * 1024 * 1024  # 10 MB: i file reali sono di poche centinaia di righe
# Un XLSX è uno zip: oltre questa dimensione decompressa (o questo rapporto) è sospetto, e
# leggerlo potrebbe esaurire la memoria del container (zip bomb).
DECOMPRESSO_MASSIMO = 200 * 1024 * 1024
RAPPORTO_MASSIMO = 200
VALIDITA_ANTEPRIMA = datetime.timedelta(hours=24)
S = m.Importazione.Stato


class ImportNonAmmesso(Exception):
    pass


@dataclass(frozen=True)
class Tipo:
    codice: str
    titolo: str
    descrizione: str
    estensioni: tuple[str, ...]
    esegui: Callable  # (percorso, dry_run, opzioni) -> dict serializzato
    etichette: dict[str, str]  # conteggi da mostrare, nell'ordine
    solo_admin: bool = False
    con_conferma: bool = True
    chiede_area: bool = False
    modello: Callable[[], Workbook] | None = None
    note: list[str] = field(default_factory=list)


def serializza(report: Report) -> dict:
    return {
        "conteggi": dict(report.conteggi),
        "anomalie": [
            [a.foglio, a.riga, a.codice, a.campo, a.valore, a.messaggio] for a in report.anomalie
        ],
        "mappature": [[v, n, k] for (v, n), k in sorted(report.mappature_conti.items())],
    }


# --- Esecuzione dei singoli tipi ------------------------------------------------------


def _contratti(percorso, dry_run, opzioni):
    return serializza(importa_excel(percorso, area=opzioni["area"], dry_run=dry_run)), None


def _date(percorso, dry_run, opzioni):
    return serializza(importa_date(percorso, dry_run=dry_run)), None


def _conti(percorso, dry_run, opzioni):
    return serializza(importa_conti(percorso, dry_run=dry_run)), None


def _quadratura(percorso, dry_run, opzioni):
    from reports import xlsx
    from reports.export import quadratura_xlsx
    from reports.quadratura import CAUSE, quadra

    q = quadra(percorso, area=opzioni["area"])
    dati = {
        "conteggi": {"righe_confrontate": len(q.righe), "righe_escluse": len(q.escluse)},
        "anomalie": [["Dashboard", n, "RIGA_ESCLUSA", "", "", motivo] for n, motivo in q.escluse]
        + [["", None, c, "", k, CAUSE[c]] for c, k in q.conteggio_cause().items()],
        "riepilogo": [
            {k: (str(v) if v is not None else None) for k, v in r.items()} for r in q.riepilogo()
        ],
    }
    return dati, xlsx.salva(quadratura_xlsx(q))


# --- Modelli da scaricare -------------------------------------------------------------

GIALLO = PatternFill("solid", fgColor="FFF2CC")


def _modello(fogli: list[tuple[str, list[str], set[str]]], istruzioni: list[str]) -> Workbook:
    """Fogli dati con l'intestazione (gialla = obbligatoria), poi il foglio Istruzioni."""
    wb = Workbook()
    wb.remove(wb.active)
    for titolo, colonne, obbligatorie in fogli:
        ws = wb.create_sheet(titolo)
        for j, nome in enumerate(colonne, start=1):
            c = ws.cell(1, j, nome)
            c.font = Font(name="Arial", bold=True)
            if nome in obbligatorie:
                c.fill = GIALLO
            ws.column_dimensions[c.column_letter].width = max(14, len(nome) + 4)
        ws.freeze_panes = "A2"
    ws = wb.create_sheet("Istruzioni")
    ws.column_dimensions["A"].width = 110
    for i, testo in enumerate(istruzioni, start=1):
        ws.cell(i, 1, testo).font = Font(name="Arial", bold=i == 1)
    return wb


def modello_date() -> Workbook:
    return _modello(
        [("Date", ["numero_contratto", "data_emissione"], {"numero_contratto", "data_emissione"})],
        [
            "Date di emissione dei contratti (estrazione SAP)",
            "Una riga per contratto: numero di contratto SAP e data di emissione (gg/mm/aaaa).",
            "Si compilano solo le date vuote; le date già registrate e diverse vanno nel report.",
            "Esempio (fittizio): 5800000000 | 15/12/2025",
        ],
    )


def modello_conti() -> Workbook:
    return _modello(
        [
            (
                "Conti",
                ["codice", "descrizione", "valido_dal", "valido_al"],
                {"codice", "descrizione", "valido_dal"},
            )
        ],
        [
            "Piano dei conti",
            "La coppia codice + valido_dal identifica il conto; una riga già presente aggiorna "
            "descrizione e fine validità. Nessuna cancellazione.",
            "Date gg/mm/aaaa. Un errore su una riga annulla tutto il file.",
            "Esempio (fittizio): 60000000 | Canoni software | 01/01/2026 |",
        ],
    )


def modello_contratti() -> Workbook:
    return _modello(
        [
            (
                "Contratti",
                [
                    "Contratto",
                    "Cig",
                    "Nuovo codice conto da 01/01/26",
                    "Codice conto",
                    "Descrizione",
                    "Fornitore",
                    "Codice fornitore",
                    "Corrispettivo Minimo",
                    "Corrispettivo Extra",
                    "Corrispettivo Massimo",
                    "Data di attivazione",
                    "Mesi contratto",
                    "Data di scadenza",
                    "Stato",
                    "Note",
                ],  # fmt: skip
                {"Contratto", "Descrizione", "Fornitore", "Corrispettivo Minimo"},
            ),
            ("Fornitori", ["Fornitore", "Codice"], {"Fornitore"}),
        ],
        [
            "Excel dei contratti (stessa struttura dei file Contratti_IT / Contratti_TLC)",
            "Si leggono i fogli il cui nome inizia con «Contratti» (i fogli «Contratti_Finanziati» "
            "e «Contratti Dissalatori» sono spese su WBS: colonna «Codice WBS»).",
            "Ogni riga entra in un fabbisogno provvisorio; raggruppamenti e catene dei rinnovi "
            "diventano proposte da confermare in «Proposte import».",
            "Rieseguire l'import con lo stesso file non crea duplicati e non sovrascrive le "
            "modifiche fatte dopo.",
        ],
    )


TIPI: dict[str, Tipo] = {
    t.codice: t
    for t in (
        Tipo(
            "contratti",
            "Excel dei contratti",
            "Contratti, voci e fornitori da un Excel con la struttura dei file di partenza.",
            (".xlsx", ".xlsm"),
            _contratti,
            {
                "righe_lette": "Righe lette",
                "contratti_creati": "Contratti creati",
                "contratti_gia_presenti": "Già presenti (scartati)",
                "voci_create": "Voci create",
                "fornitori_creati": "Fornitori creati",
                "proposte_raggruppamento": "Proposte di raggruppamento",
                "proposte_predecessore": "Proposte di catena",
            },
            chiede_area=True,
            modello=modello_contratti,
        ),
        Tipo(
            "date_emissione",
            "Date di emissione",
            "Data di emissione dei contratti già registrati, da un'estrazione SAP.",
            (".xlsx", ".csv"),
            _date,
            {
                "compilati": "Date compilate",
                "invariati": "Già uguali",
                "discordanti": "Discordanti (non modificate)",
                "non_trovati": "Numeri non trovati",
            },
            modello=modello_date,
        ),
        Tipo(
            "conti",
            "Piano dei conti",
            "Conti COGE con validità temporale. Tabella di configurazione: solo Admin.",
            (".xlsx", ".csv"),
            _conti,
            {"creati": "Conti creati", "aggiornati": "Aggiornati", "invariati": "Invariati"},
            solo_admin=True,
            modello=modello_conti,
        ),
        Tipo(
            "quadratura",
            "Quadratura con l'Excel",
            "Confronta la competenza del registro con il Dashboard dell'Excel. Non scrive nulla.",
            (".xlsx", ".xlsm"),
            _quadratura,
            {"righe_confrontate": "Righe confrontate", "righe_escluse": "Righe escluse"},
            con_conferma=False,
            chiede_area=True,
        ),
    )
}


# --- Permessi e operazioni --------------------------------------------------------------


def tipi_per(utente) -> list[Tipo]:
    ruolo = role_of(utente)
    if ruolo not in WRITE_ROLES:
        return []
    return [t for t in TIPI.values() if ruolo == ADMIN or not t.solo_admin]


def puo_usare(utente, tipo: Tipo) -> bool:
    return tipo in tipi_per(utente)


def puo_confermare(utente, imp: m.Importazione) -> bool:
    tipo = TIPI.get(imp.tipo)
    if tipo is None or not puo_usare(utente, tipo):
        return False
    return role_of(utente) == ADMIN or imp.utente_id == utente.pk


def _nome_sicuro(nome: str) -> str:
    base = Path(nome).name
    return re.sub(r"[^\w.\- ]", "_", base)[:120] or "file"


def _esegui(imp: m.Importazione, *, dry_run: bool):
    """Scrive il file in una cartella temporanea con il suo nome e lancia l'import."""
    tipo = TIPI[imp.tipo]
    with tempfile.TemporaryDirectory(prefix="import-") as cartella:
        percorso = Path(cartella) / _nome_sicuro(imp.nome_file)
        percorso.write_bytes(bytes(imp.contenuto))
        return tipo.esegui(percorso, dry_run, imp.opzioni)


def controlla_xlsx(contenuto: bytes) -> None:
    """Rifiuta gli XLSX che non sono zip validi o che si espandono troppo."""
    try:
        with zipfile.ZipFile(io.BytesIO(contenuto)) as z:
            decompresso = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile as exc:
        raise ImportNonAmmesso("Il file non è un Excel valido (.xlsx).") from exc
    if decompresso > DECOMPRESSO_MASSIMO or decompresso > RAPPORTO_MASSIMO * max(len(contenuto), 1):
        raise ImportNonAmmesso("Il file Excel è troppo grande una volta decompresso.")


def carica(tipo: Tipo, file, opzioni: dict, utente) -> m.Importazione:
    """Registra il file e ne calcola l'anteprima (o il report, per i tipi senza conferma)."""
    if not puo_usare(utente, tipo):
        raise ImportNonAmmesso("Questo import non è disponibile per il tuo ruolo.")
    nome = file.name or "file"
    if Path(nome).suffix.lower() not in tipo.estensioni:
        raise ImportNonAmmesso(f"Formato non ammesso: servono file {', '.join(tipo.estensioni)}.")
    if file.size > DIMENSIONE_MASSIMA:
        raise ImportNonAmmesso("Il file supera i 10 MB.")
    contenuto = file.read()
    if Path(nome).suffix.lower() in (".xlsx", ".xlsm"):
        controlla_xlsx(contenuto)
    imp = m.Importazione.objects.create(
        tipo=tipo.codice,
        nome_file=nome[:255],
        contenuto=contenuto,
        sha256=hashlib.sha256(contenuto).hexdigest(),
        dimensione=len(contenuto),
        opzioni=opzioni,
        utente=utente,
    )
    try:
        dati, risultato = _esegui(imp, dry_run=True)
    except FileNonValido as exc:
        imp.stato, imp.messaggio = S.ERRORE, str(exc)
    except Exception as exc:  # file inatteso: si registra, non si interrompe la pagina
        log.exception("Anteprima dell'import %s non riuscita", imp.pk)
        imp.stato, imp.messaggio = S.ERRORE, f"Il file non si può leggere: {exc}"
    else:
        imp.anteprima, imp.risultato = dati, risultato
        if not tipo.con_conferma:
            imp.stato = S.COMPLETATA
    imp.save()
    return imp


def gia_importato(imp: m.Importazione) -> m.Importazione | None:
    """Lo stesso file (stesso contenuto) già confermato per lo stesso tipo."""
    return (
        m.Importazione.objects.filter(tipo=imp.tipo, sha256=imp.sha256, stato=S.CONFERMATA)
        .exclude(pk=imp.pk)
        .first()
    )


def scaduta(imp: m.Importazione, adesso=None) -> bool:
    adesso = adesso or timezone.now()
    return imp.stato == S.ANTEPRIMA and adesso - imp.caricata_il > VALIDITA_ANTEPRIMA


def conferma(pk: int, utente) -> m.Importazione:
    """Applica il file dell'anteprima. Una sola volta: la riga è bloccata durante l'import.

    Gli esiti negativi (scaduta, errore) si salvano e solo dopo, fuori dalla transazione,
    si segnalano: un'eccezione dentro la transazione annullerebbe anche lo stato.
    """
    errore = None
    with transaction.atomic():
        imp = m.Importazione.objects.select_for_update().get(pk=pk)
        if not puo_confermare(utente, imp):
            raise ImportNonAmmesso("Può confermare solo chi ha caricato il file, o un Admin.")
        if imp.stato != S.ANTEPRIMA:
            raise ImportNonAmmesso("Questo import non è più in anteprima.")
        if scaduta(imp):
            imp.stato = S.SCADUTA
            imp.save(update_fields=["stato"])
            errore = "Anteprima scaduta (oltre 24 ore): carica di nuovo il file."
        elif hashlib.sha256(bytes(imp.contenuto)).hexdigest() != imp.sha256:
            errore = "Il file registrato non corrisponde: carica di nuovo il file."
        else:
            try:
                # L'import ha la sua transazione: se fallisce si annulla solo quella.
                dati, risultato = _esegui(imp, dry_run=False)
            except FileNonValido as exc:
                errore = str(exc)
            except Exception as exc:
                log.exception("Import %s non riuscito", imp.pk)
                errore = f"Import non riuscito, nessun dato scritto: {exc}"
            if errore:
                imp.stato, imp.messaggio = S.ERRORE, errore
            else:
                imp.esito, imp.risultato = dati, risultato or imp.risultato
                imp.stato = S.CONFERMATA
            imp.confermata_il = timezone.now()
            imp.confermata_da = utente
            imp.save()
    if errore:
        raise ImportNonAmmesso(errore)
    return imp


def annulla(pk: int, utente) -> m.Importazione:
    with transaction.atomic():
        imp = m.Importazione.objects.select_for_update().get(pk=pk)
        if not puo_confermare(utente, imp):
            raise ImportNonAmmesso("Può annullare solo chi ha caricato il file, o un Admin.")
        if imp.stato != S.ANTEPRIMA:
            raise ImportNonAmmesso("Questo import non è più in anteprima.")
        imp.stato = S.ANNULLATA
        imp.save(update_fields=["stato"])
    return imp


def report_xlsx(imp: m.Importazione, dati: dict) -> Workbook:
    """Conteggi e anomalie in XLSX, per l'anteprima o per l'esito."""
    from reports import xlsx

    tipo = TIPI[imp.tipo]
    wb = xlsx.nuovo_libro()
    intestazione = [
        f"{tipo.titolo} — {imp.nome_file}",
        f"Caricato da {imp.utente} il {timezone.localtime(imp.caricata_il):%d/%m/%Y %H:%M}",
    ]
    conteggi = dati.get("conteggi", {})
    righe = [[tipo.etichette.get(k, k), v] for k, v in conteggi.items()]
    xlsx.foglio(wb, "Riepilogo", intestazione, ["Voce", "Numero"], righe)
    colonne = ["Foglio", "Riga", "Codice", "Campo", "Valore", "Messaggio"]
    xlsx.foglio(wb, "Anomalie", intestazione, colonne, dati.get("anomalie", []))
    if dati.get("mappature"):
        xlsx.foglio(
            wb, "Mappature conti", intestazione, ["Conto vecchio", "Conto nuovo", "Righe"],
            dati["mappature"],
        )  # fmt: skip
    return wb
