"""Struttura dal riepilogo del budget ICTDINN (Rev25): cluster, sottocluster, conti e WBS.

Legge il file «Clusterizzazione budget ICTDINN» così com'è: un foglio con le colonne
Cluster | SottoCluster | Owner | Tipo costo | CDC | conto COGE (codice, descrizione) | WBS
(tre livelli), celle unite comprese.

- Cluster: si riconosce per nome tra quelli del registro; se non c'è si crea, con il nome
  (in maiuscolo) come codice se è di al massimo 10 caratteri.
- Sottocluster: nome (la descrizione tra parentesi, se è più di una parola, va nelle note),
  owner (testo) e cluster. Si riconosce per nome nel cluster, senza badare a maiuscole.
- Conti: il conto è dei cluster in cui compare nel file (anche più d'uno). Conti già
  registrati: cambiano solo i cluster; nuovi: validi dal 1/1 dell'anno del file.
- WBS: si usa il codice del secondo livello (o del terzo, se il secondo «non è utile»).
  Le WBS a progetto già registrate non cambiano; le nuove sono di cluster.
- Tutto o niente, idempotente, nessuna cancellazione. Gli owner non diventano permessi:
  vanno assegnati (amministrazione o foglio Responsabili della struttura).
"""

import datetime
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from django.contrib.auth import get_user_model
from django.db import transaction

from contratti import models as m
from contratti.importer import tabelle
from contratti.importer.report import Report

FOGLIO = "Struttura budget"
NATURE = {"capex": m.Natura.CAPEX, "opex": m.Natura.OPEX}
CODICE_WBS = re.compile(r"\b[A-Z]{2}[./][0-9A-Z./]+")
CODICE_CONTO = re.compile(r"\b\d{5,10}\b")
ASSENTE = {"", "--", "(non utile)", "(da definire)", "da definire"}
CODICE_CLUSTER_MAX = 10
CONTEGGI = (
    "cluster_creati", "sottocluster_creati", "sottocluster_aggiornati",
    "conti_creati", "conti_aggiornati", "wbs_create", "wbs_aggiornate",
)  # fmt: skip


class _Rollback(Exception):
    pass


# --- Testi --------------------------------------------------------------------------------


def pulisci(valore) -> str:
    """Testo di una cella su una riga sola, senza spazi doppi."""
    if isinstance(valore, float) and valore.is_integer():
        valore = int(valore)
    return re.sub(r"\s+", " ", str(valore if valore is not None else "")).strip()


def chiave(testo: str) -> str:
    """Confronto dei nomi: senza accenti, spazi o maiuscole."""
    senza = unicodedata.normalize("NFKD", pulisci(testo)).encode("ascii", "ignore").decode()
    return senza.casefold()


def frase(testo: str) -> str:
    """«SICUREZZA FISICA» → «Sicurezza fisica»; le sigle brevi (IT, OT, ICT) restano."""
    testo = pulisci(testo)
    if len(testo) <= 3 or testo != testo.upper():
        return testo
    return testo[:1] + testo[1:].lower()


def nome_e_nota(testo: str) -> tuple[str, str]:
    """Nome del sottocluster e nota: «(...)» di più parole è una descrizione; di una sola
    parola («(Holding)») fa parte del nome."""
    testo = pulisci(testo)
    trovata = re.search(r"\(([^()]*)\)\s*$", testo)
    if trovata is None:
        return frase(testo), ""
    dentro = trovata.group(1).strip()
    base = testo[: trovata.start()].strip()
    if base and re.fullmatch(r"[\w.-]+", dentro):
        return f"{frase(base)} ({dentro})", ""
    return frase(base or dentro), dentro if base else ""


def _prima_riga(valore) -> str:
    """Prima riga non vuota di una cella (il resto è «prima era…», «DA EVITARE»)."""
    for riga in str(valore or "").splitlines():
        if riga.strip():
            return riga.strip()
    return ""


def _codice_wbs(valore) -> str:
    trovata = CODICE_WBS.search(str(valore or "").upper().replace("\n", " "))
    return trovata.group(0).rstrip(".") if trovata else ""


# --- Lettura ------------------------------------------------------------------------------


@dataclass
class RigaStruttura:
    numero: int
    cluster: str
    sottocluster: str
    owner: str
    natura: str
    conti: list[tuple[str, str]] = field(default_factory=list)  # (codice, descrizione)
    wbs: tuple[str, str] | None = None  # (codice, descrizione)
    da_evitare: bool = False


def _celle(ws) -> dict[tuple[int, int], object]:
    """Valore di ogni cella, con le celle unite riempite dal valore della prima."""
    valori = {}
    for riga in ws.iter_rows():
        for cella in riga:
            if cella.value is not None:
                valori[(cella.row, cella.column)] = cella.value
    for area in ws.merged_cells.ranges:
        iniziale = valori.get((area.min_row, area.min_col))
        if iniziale is None:
            continue
        for r in range(area.min_row, area.max_row + 1):
            for c in range(area.min_col, area.max_col + 1):
                valori.setdefault((r, c), iniziale)
    return valori


def _colonne(valori, riga_intestazione: int) -> dict[str, int]:
    """Colonne per nome dalla riga dei titoli e da quella dei gruppi (sopra)."""
    titoli = {
        chiave(valori.get((riga_intestazione, c))): c
        for c in range(1, 30)
        if valori.get((riga_intestazione, c)) is not None
    }
    gruppi = {
        c: chiave(valori.get((riga_intestazione - 1, c)))
        for c in range(1, 30)
        if valori.get((riga_intestazione - 1, c)) is not None
    }
    col = {
        "cluster": titoli.get("cluster"),
        "sottocluster": titoli.get("sottocluster"),
        "owner": titoli.get("owner"),
        "natura": titoli.get("tipo costo"),
    }
    conto = next((c for c, g in gruppi.items() if "vdc" in g or "co.ge" in g), None)
    wbs = next((c for c, g in gruppi.items() if g == "wbs"), None)
    if conto is not None:
        col["conto"] = conto
    if wbs is not None:
        col["wbs"] = wbs
    mancanti = [k for k in ("cluster", "sottocluster", "owner", "natura", "conto", "wbs")
                if col.get(k) is None]  # fmt: skip
    if mancanti:
        raise tabelle.FileNonValido(
            f"Intestazioni non riconosciute: {', '.join(mancanti)}. "
            "Servono Cluster, SottoCluster, Owner, Tipo costo, VDC / Co.Ge. e WBS."
        )
    return col


def _anno(valori) -> int | None:
    for testo in valori.values():
        trovato = re.search(r"TOTALE BUDGET (\d{4})", str(testo).upper())
        if trovato:
            return int(trovato.group(1))
    return None


def _conti_della_riga(codice, descrizione) -> list[tuple[str, str]]:
    """Conti di una cella: uno, o più («Per Forniture/Acquisti: 611021 - DESCRIZIONE»)."""
    codici = list(dict.fromkeys(CODICE_CONTO.findall(str(codice or ""))))
    testo = str(descrizione or "")
    if len(codici) == 1:
        riga = next((r for r in testo.splitlines() if codici[0] in r), "")
        parte = riga.split(" - ", 1)[1] if " - " in riga else testo
        return [(codici[0], pulisci(parte))]
    trovati = []
    for c in codici:
        riga = next((r for r in testo.splitlines() if c in r), "")
        trovati.append((c, pulisci(riga.split(" - ", 1)[1]) if " - " in riga else ""))
    return trovati


def _wbs_della_riga(valori, riga: int, base: int) -> tuple[str, str] | None:
    """WBS del secondo livello; se «non è utile», del terzo; altrimenti del primo."""
    for livello in (1, 2, 0):
        codice = _codice_wbs(valori.get((riga, base + 2 * livello)))
        if not codice:
            continue
        for l2 in (livello, 0):
            descrizione = pulisci(_prima_riga(valori.get((riga, base + 2 * l2 + 1))))
            if descrizione.casefold() not in ASSENTE:
                return codice, descrizione
        return codice, codice
    return None


def leggi(percorso: Path) -> tuple[list[RigaStruttura], int | None]:
    """Righe della struttura e anno del budget (dal «TOTALE BUDGET 2026»)."""
    try:
        wb = openpyxl.load_workbook(percorso, data_only=True)
    except Exception as exc:
        raise tabelle.FileNonValido(f"Il file non è un Excel leggibile ({exc}).") from exc
    ws = wb.worksheets[0]
    valori = _celle(ws)
    intestazione = next(
        (
            r
            for (r, c), v in valori.items()
            if c == 1 and chiave(v) == "cluster" and chiave(valori.get((r, 2))) == "sottocluster"
        ),
        None,
    )
    if intestazione is None:
        raise tabelle.FileNonValido(
            "Riga delle intestazioni non trovata: servono le colonne «Cluster» e «SottoCluster»."
        )
    col = _colonne(valori, intestazione)
    righe = []
    for r in range(intestazione + 1, ws.max_row + 1):
        if any("TOTALE" in str(v).upper() for (rr, _), v in valori.items() if rr == r):
            break
        if not pulisci(valori.get((r, col["cluster"]))):
            continue
        sotto = pulisci(valori.get((r, col["sottocluster"])))
        if not sotto:
            continue
        natura = chiave(valori.get((r, col["natura"])))
        grezza = str(valori.get((r, col["wbs"]), ""))
        righe.append(
            RigaStruttura(
                numero=r,
                cluster=pulisci(valori.get((r, col["cluster"]))),
                sottocluster=str(valori.get((r, col["sottocluster"]))),
                owner=pulisci(valori.get((r, col["owner"]))),
                natura=NATURE.get(natura, natura),
                conti=_conti_della_riga(
                    valori.get((r, col["conto"])), valori.get((r, col["conto"] + 1))
                ),
                wbs=_wbs_della_riga(valori, r, col["wbs"]),
                da_evitare="DA EVITARE"
                in " ".join(str(valori.get((r, col["wbs"] + k), "")) for k in range(6)).upper()
                or "DA EVITARE" in grezza.upper(),
            )
        )
    return righe, _anno(valori)


# --- Import -------------------------------------------------------------------------------


def importa_struttura_budget(
    percorso: str | Path,
    *,
    dry_run: bool = False,
    valido_dal: datetime.date | None = None,
    oggi: datetime.date | None = None,
) -> Report:
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    for chiave_conteggio in CONTEGGI:
        report.conteggi[chiave_conteggio] = 0
    righe, anno = leggi(percorso)
    if not righe:
        raise tabelle.FileNonValido("Nessuna riga di struttura trovata nel file.")
    oggi = oggi or datetime.date.today()
    valido_dal = valido_dal or datetime.date(anno or oggi.year, 1, 1)
    try:
        with transaction.atomic():
            _Importatore(report, righe, valido_dal, oggi).esegui()
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


class _Importatore:
    def __init__(self, report, righe, valido_dal, oggi):
        self.report, self.righe, self.valido_dal, self.oggi = report, righe, valido_dal, oggi
        self.cluster: dict[str, m.Cluster] = {}  # per chiave del nome nel file
        self.sottocluster: dict[tuple[str, str], m.Sottocluster] = {}

    def conta(self, nome):
        self.report.conteggi[nome] += 1

    def anomalia(self, riga, codice, campo, valore, messaggio):
        self.report.anomalia(
            FOGLIO, riga.numero if riga else None, codice, campo, valore, messaggio
        )

    def esegui(self):
        for riga in self.righe:
            self.cluster_di(riga)
            self.sottocluster_di(riga)
        self.conti()
        self.wbs()
        self.owner()

    # --- Cluster e sottocluster ---------------------------------------------------------

    def cluster_di(self, riga) -> m.Cluster:
        k = chiave(riga.cluster)
        if k in self.cluster:
            return self.cluster[k]
        esistenti = [c for c in m.Cluster.objects.all() if k in (chiave(c.nome), chiave(c.codice))]
        if esistenti:
            cluster = esistenti[0]
        else:
            codice = pulisci(riga.cluster).upper()
            if len(codice) > CODICE_CLUSTER_MAX or m.Cluster.objects.filter(codice=codice).exists():
                raise tabelle.FileNonValido(
                    f"Riga {riga.numero}: il cluster «{riga.cluster}» non è nel registro e il "
                    f"codice «{codice}» non è utilizzabile (massimo {CODICE_CLUSTER_MAX} "
                    "caratteri). Crealo prima in amministrazione."
                )
            cluster = m.Cluster(codice=codice, nome=frase(riga.cluster))
            cluster._change_reason = "Import struttura budget"
            cluster.save()
            self.conta("cluster_creati")
        self.cluster[k] = cluster
        return cluster

    def sottocluster_di(self, riga) -> m.Sottocluster:
        cluster = self.cluster_di(riga)
        nome, nota = nome_e_nota(riga.sottocluster)
        k = (chiave(riga.cluster), chiave(nome))
        if k in self.sottocluster:
            return self.sottocluster[k]
        sottocluster = next(
            (s for s in cluster.sottocluster.all() if chiave(s.nome) == chiave(nome)), None
        )
        if sottocluster is None:
            sottocluster = m.Sottocluster(
                cluster=cluster, nome=nome, note=nota, owner=riga.owner[:150]
            )
            sottocluster._change_reason = "Import struttura budget"
            sottocluster.save()
            self.conta("sottocluster_creati")
        else:
            nuovi = {"owner": riga.owner[:150], "archiviato": False}
            if nota and not sottocluster.note:
                nuovi["note"] = nota
            if any(getattr(sottocluster, a) != v for a, v in nuovi.items()):
                for a, v in nuovi.items():
                    setattr(sottocluster, a, v)
                sottocluster._change_reason = "Import struttura budget"
                sottocluster.save()
                self.conta("sottocluster_aggiornati")
        self.sottocluster[k] = sottocluster
        return sottocluster

    # --- Conti --------------------------------------------------------------------------

    def conti(self):
        per_conto: dict[str, dict] = {}
        for riga in self.righe:
            if riga.natura not in (m.Natura.CAPEX, m.Natura.OPEX) and riga.conti:
                self.anomalia(riga, "NATURA_NON_GESTITA", "tipo costo", riga.natura,
                              "Tipo di costo diverso da CAPEX e OPEX: conti ignorati.")  # fmt: skip
                continue
            for codice, descrizione in riga.conti:
                voce = per_conto.setdefault(codice, {"descrizione": "", "cluster": {}})
                voce["descrizione"] = voce["descrizione"] or descrizione
                voce["cluster"][self.cluster_di(riga).pk] = self.cluster_di(riga)
            if not riga.conti and riga.natura in (m.Natura.CAPEX, m.Natura.OPEX):
                self.segnala_conto_mancante(riga)
        for codice, dati in per_conto.items():
            cluster = list(dati["cluster"].values())
            conto = m.ContoCoge.objects.filter(codice=codice).order_by("-valido_dal").first()
            if conto is None:
                conto = m.ContoCoge(
                    codice=codice,
                    descrizione=dati["descrizione"] or f"Conto {codice}",
                    valido_dal=self.valido_dal,
                )
                conto._change_reason = "Import struttura budget"
                conto.save()
                conto.clusters.set(cluster)
                self.conta("conti_creati")
            elif set(conto.clusters.all()) != set(cluster):
                conto.clusters.set(cluster)
                self.conta("conti_aggiornati")

    def segnala_conto_mancante(self, riga):
        # «(da definire)» o nessun conto: il sottocluster non ha ancora un conto per la natura.
        if riga.conti or riga.wbs:
            return
        self.anomalia(
            riga,
            "CONTO_DA_DEFINIRE",
            "conto",
            riga.sottocluster,
            f"Nessun conto {riga.natura.upper()} per «{pulisci(riga.sottocluster)}».",
        )

    # --- WBS ----------------------------------------------------------------------------

    def wbs(self):
        viste: dict[str, m.Cluster] = {}
        for riga in self.righe:
            if riga.wbs is None:
                continue
            codice, descrizione = riga.wbs
            cluster = self.cluster_di(riga)
            if codice in viste and viste[codice] != cluster:
                self.anomalia(riga, "WBS_IN_PIU_CLUSTER", "wbs", codice,
                              f"La WBS compare nei cluster {viste[codice].codice} e "
                              f"{cluster.codice}: vale il primo.")  # fmt: skip
                continue
            if codice in viste:
                continue
            viste[codice] = cluster
            if riga.da_evitare:
                self.anomalia(
                    riga,
                    "WBS_DA_EVITARE",
                    "wbs",
                    codice,
                    "Segnata «DA EVITARE» nel file: registrata, ma da non usare.",
                )
            wbs = m.WBS.objects.filter(codice_wbs=codice).first()
            if wbs is None:
                wbs = m.WBS(
                    codice_wbs=codice,
                    descrizione=descrizione[:200],
                    tipo=m.WBS.Tipo.CLUSTER,
                    cluster=cluster,
                )
                wbs._change_reason = "Import struttura budget"
                wbs.save()
                self.conta("wbs_create")
            elif wbs.tipo == m.WBS.Tipo.PROGETTO:
                self.anomalia(riga, "WBS_A_PROGETTO", "wbs", codice,
                              "WBS a progetto già registrata: non cambia. Se è di cluster, "
                              "cambiala in amministrazione.")  # fmt: skip
            elif wbs.cluster_id != cluster.pk:
                wbs.cluster = cluster
                wbs._change_reason = "Import struttura budget"
                wbs.save()
                self.conta("wbs_aggiornate")

    # --- Owner --------------------------------------------------------------------------

    def owner(self):
        utenti = get_user_model().objects.filter(is_active=True)
        visti = set()
        for riga in self.righe:
            sotto = self.sottocluster_di(riga)
            if not riga.owner or (sotto.pk, riga.owner) in visti:
                continue
            visti.add((sotto.pk, riga.owner))
            nomi = [chiave(riga.owner), chiave(" ".join(reversed(riga.owner.split())))]
            trovati = [
                u.username
                for u in utenti
                if chiave(f"{u.first_name} {u.last_name}") in nomi
                or chiave(f"{u.last_name} {u.first_name}") in nomi
            ]
            suggerimento = (
                f"Utente: {trovati[0]}." if len(trovati) == 1 else "Utente non riconosciuto."
            )
            self.anomalia(riga, "OWNER_DA_ASSEGNARE", "owner", riga.owner,
                          f"«{sotto.nome}»: assegna il sottocluster al responsabile "
                          f"(amministrazione). {suggerimento}")  # fmt: skip
