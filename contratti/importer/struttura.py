"""Struttura dell'ufficio ICTDINN (F9.2): cluster, responsabili, piano dei conti e WBS.

Modello ``GestioneContratti_ModelloImport_Struttura`` (fogli Cluster,
Responsabili, Conti, WBS; il foglio Istruzioni e la colonna «Controllo» si ignorano).

- Tutto o niente: un errore su una riga blocca il file, nulla è scritto.
- Rieseguire l'import con lo stesso file non cambia nulla.
- Nessuna cancellazione di conti e WBS: tolti dal file restano; si dismettono con
  «valido_al» (conti) o «attiva» = No (WBS, archiviata).
- Responsabili: il foglio, se compilato, è l'elenco completo; le assegnazioni che non vi
  compaiono si archiviano (non valgono più). Foglio vuoto: assegnazioni invariate.
- Le voci con una WBS importata come testo (prima della F9.2) si collegano alla WBS con lo
  stesso codice; quelle senza corrispondenza vanno nel report.
"""

from collections import Counter
from pathlib import Path

import openpyxl
from django.db import transaction

from contratti import models as m
from contratti.importer import tabelle
from contratti.importer.report import Report

FOGLI = ("Cluster", "Responsabili", "Conti", "WBS")
TUTTI = "TUTTI"
SI = {"", "si", "sì", "s", "x", "1", "true", "vero"}
NO = {"no", "n", "0", "false", "falso"}
TIPI_WBS = {"cluster": m.WBS.Tipo.CLUSTER, "progetto": m.WBS.Tipo.PROGETTO}


class _Rollback(Exception):
    pass


def _errore(foglio: str, numero: int, testo: str):
    return tabelle.FileNonValido(f"{foglio}, riga {numero}: {testo}")


def _testo(r: dict, campo: str) -> str:
    valore = r.get(campo)
    if isinstance(valore, float) and valore.is_integer():
        valore = int(valore)
    return str(valore if valore is not None else "").strip()


def _tabella(percorso: Path, foglio: str) -> list[tuple[int, dict]]:
    """Righe non vuote del foglio, con il numero di riga Excel; «Controllo» esclusa."""
    righe = tabelle.righe(percorso, foglio=foglio)
    return [
        (n, r)
        for n, r in enumerate(righe, start=2)
        if any(str(v or "").strip() for k, v in r.items() if k != "controllo")
    ]


def importa_struttura(percorso: str | Path, *, dry_run: bool = False) -> Report:
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    try:
        nomi = openpyxl.load_workbook(percorso, read_only=True).sheetnames
    except Exception as exc:
        raise tabelle.FileNonValido(f"Il file non è un Excel leggibile ({exc}).") from exc
    mancanti = [f for f in FOGLI if f not in nomi]
    if mancanti:
        raise tabelle.FileNonValido(
            f"Fogli mancanti: {', '.join(mancanti)}. Usa il modello della struttura."
        )
    for chiave in (
        "cluster_creati", "cluster_aggiornati",
        "assegnazioni_create", "assegnazioni_tolte",
        "conti_creati", "conti_aggiornati",
        "wbs_create", "wbs_aggiornate",
        "voci_collegate",
    ):  # fmt: skip
        report.conteggi[chiave] = 0
    try:
        with transaction.atomic():
            _Struttura(report, percorso).esegui()
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


class _Struttura:
    def __init__(self, report: Report, percorso: Path):
        self.report = report
        self.percorso = percorso

    def esegui(self):
        self.cluster = {c.codice: c for c in m.Cluster.objects.all()}
        self.fogli_cluster()
        self.fogli_responsabili()
        self.foglio_conti()
        self.foglio_wbs()
        self.collega_voci()

    def _cluster(self, foglio, numero, codice) -> m.Cluster:
        c = self.cluster.get(codice)
        if c is None:
            raise _errore(foglio, numero, f"cluster inesistente: {codice}.")
        return c

    # --- Cluster -----------------------------------------------------------------

    def fogli_cluster(self):
        visti = set()
        for numero, r in _tabella(self.percorso, "Cluster"):
            codice, nome = _testo(r, "codice"), _testo(r, "nome")
            if not codice or not nome:
                raise _errore("Cluster", numero, "codice e nome obbligatori.")
            if codice.upper() == TUTTI:
                raise _errore("Cluster", numero, "TUTTI è riservato ai responsabili.")
            if codice in visti:
                raise _errore("Cluster", numero, f"codice ripetuto: {codice}.")
            visti.add(codice)
            note = _testo(r, "note")
            c = self.cluster.get(codice)
            if c is None:
                c = m.Cluster.objects.create(codice=codice, nome=nome, note=note)
                self.cluster[codice] = c
                self.report.conteggi["cluster_creati"] += 1
            elif (c.nome, c.note) != (nome, note):
                c.nome, c.note = nome, note
                c._change_reason = "Import struttura"
                c.save()
                self.report.conteggi["cluster_aggiornati"] += 1

    # --- Responsabili ------------------------------------------------------------

    def fogli_responsabili(self):
        righe = _tabella(self.percorso, "Responsabili")
        if not righe:
            return
        nel_file: set[tuple[str, int | None]] = set()
        for numero, r in righe:
            utente, codice = _testo(r, "utente").lower(), _testo(r, "cluster")
            if not utente or not codice:
                raise _errore("Responsabili", numero, "utente e cluster obbligatori.")
            cluster = (
                None if codice.upper() == TUTTI else self._cluster("Responsabili", numero, codice)
            )
            chiave = (utente, cluster.pk if cluster else None)
            if chiave in nel_file:
                raise _errore("Responsabili", numero, f"riga ripetuta: {utente} → {codice}.")
            nel_file.add(chiave)
            a, creata = m.AssegnazioneCluster.objects.get_or_create(
                username=utente, cluster=cluster, defaults={"note": _testo(r, "note")[:200]}
            )
            if a.archiviato:  # tolta in passato, di nuovo nel file
                a.archiviato = False
                a._change_reason = "Import struttura: di nuovo nel file"
                a.save(update_fields=["archiviato"])
                creata = True
            if creata:
                self.report.conteggi["assegnazioni_create"] += 1
        for a in m.AssegnazioneCluster.objects.filter(archiviato=False):
            if (a.username, a.cluster_id) not in nel_file:
                a.archiviato = True
                a._change_reason = "Import struttura: non più nel file"
                a.save(update_fields=["archiviato"])
                self.report.conteggi["assegnazioni_tolte"] += 1

    # --- Conti -------------------------------------------------------------------

    def foglio_conti(self):
        sostituzioni = []
        visti = set()
        for numero, r in _tabella(self.percorso, "Conti"):
            codice = tabelle.codice(r.get("codice"))
            descrizione = _testo(r, "descrizione")
            if codice is None or not descrizione:
                raise _errore("Conti", numero, "codice e descrizione obbligatori.")
            cluster = _testo(r, "cluster")
            if not cluster:
                raise _errore("Conti", numero, "ogni conto appartiene a un cluster.")
            cluster = self._cluster("Conti", numero, cluster)
            dal, al = self._data(r, "valido_dal", numero), self._data(r, "valido_al", numero)
            if dal is None:
                raise _errore("Conti", numero, "valido_dal obbligatoria.")
            if al is not None and al < dal:
                raise _errore("Conti", numero, "valido_al prima di valido_dal.")
            if (codice, dal) in visti:
                raise _errore("Conti", numero, f"conto ripetuto: {codice} dal {dal:%d/%m/%Y}.")
            visti.add((codice, dal))
            conto = m.ContoCoge.objects.filter(codice=codice, valido_dal=dal).first()
            nuovo = (descrizione, al, cluster.pk)
            if conto is None:
                conto = m.ContoCoge(codice=codice, valido_dal=dal)
                esito = "conti_creati"
            elif (conto.descrizione, conto.valido_al, conto.cluster_id) == nuovo:
                esito = None
            else:
                esito = "conti_aggiornati"
            if esito:
                conto.descrizione, conto.valido_al, conto.cluster = descrizione, al, cluster
                conto._change_reason = "Import struttura"
                conto.save()
                self.report.conteggi[esito] += 1
            if sostituto := tabelle.codice(r.get("sostituito_da")):
                if sostituto == codice:
                    raise _errore("Conti", numero, "un conto non sostituisce se stesso.")
                sostituzioni.append((numero, conto, sostituto))
        for numero, conto, sostituto in sostituzioni:
            nuovo = m.ContoCoge.objects.filter(codice=sostituto).order_by("-valido_dal").first()
            if nuovo is None:
                raise _errore("Conti", numero, f"sostituito_da: conto {sostituto} inesistente.")
            if conto.sostituito_da_id != nuovo.pk:
                conto.sostituito_da = nuovo
                conto._change_reason = "Import struttura"
                conto.save(update_fields=["sostituito_da"])

    def _data(self, r, campo, numero):
        try:
            return tabelle.data(r.get(campo))
        except ValueError as exc:
            raise _errore("Conti", numero, f"{campo} non valida ({exc}).") from exc

    # --- WBS ---------------------------------------------------------------------

    def foglio_wbs(self):
        visti = set()
        for numero, r in _tabella(self.percorso, "WBS"):
            codice, descrizione = _testo(r, "codice_wbs"), _testo(r, "descrizione")
            if not codice or not descrizione:
                raise _errore("WBS", numero, "codice WBS e descrizione obbligatori.")
            if codice in visti:
                raise _errore("WBS", numero, f"codice WBS ripetuto: {codice}.")
            visti.add(codice)
            tipo = TIPI_WBS.get(_testo(r, "tipo").lower())
            if tipo is None:
                raise _errore("WBS", numero, "tipo: «Cluster» o «Progetto».")
            cluster = _testo(r, "cluster")
            if tipo == m.WBS.Tipo.CLUSTER and not cluster:
                raise _errore("WBS", numero, "una WBS di cluster ha il cluster.")
            cluster = self._cluster("WBS", numero, cluster) if cluster else None
            attiva = _testo(r, "attiva").lower()
            if attiva not in SI | NO:
                raise _errore("WBS", numero, "attiva: «Sì» o «No».")
            valori = {
                "descrizione": descrizione,
                "tipo": tipo,
                "cluster": cluster,
                "note": _testo(r, "note"),
                "archiviato": attiva in NO,
            }
            wbs = m.WBS.objects.filter(codice_wbs=codice).first()
            if wbs is None:
                wbs = m.WBS(codice_wbs=codice)
                esito = "wbs_create"
            elif all(getattr(wbs, k) == v for k, v in valori.items()):
                continue
            else:
                esito = "wbs_aggiornate"
            for k, v in valori.items():
                setattr(wbs, k, v)
            wbs._change_reason = "Import struttura"
            wbs.save()
            self.report.conteggi[esito] += 1

    # --- Voci con la WBS importata come testo -----------------------------------------

    def collega_voci(self):
        wbs = {w.codice_wbs: w for w in m.WBS.objects.all()}
        restanti: Counter = Counter()
        voci = m.VoceContratto.objects.filter(wbs__isnull=True).exclude(codice_wbs_importato="")
        for voce in voci.select_related("contratto__fabbisogno"):
            trovata = wbs.get(voce.codice_wbs_importato)
            if trovata is None:
                restanti[voce.codice_wbs_importato] += 1
                continue
            if voce.natura != m.Natura.CAPEX:
                self.report.anomalia(
                    "WBS", None, "WBS_SU_OPEX", "voce", voce.codice_wbs_importato,
                    f"Voce #{voce.pk} ({voce.contratto.fabbisogno.descrizione}) è OPEX: "
                    "collegala a mano se è CAPEX.",
                )  # fmt: skip
                continue
            voce.wbs = trovata
            voce._change_reason = "Import struttura: WBS collegata"
            voce.save(update_fields=["wbs"])
            self.report.conteggi["voci_collegate"] += 1
        for codice, n in sorted(restanti.items()):
            self.report.anomalia(
                "WBS", None, "WBS_NON_IN_STRUTTURA", "codice_wbs", codice,
                f"{n} voci hanno questa WBS (testo importato) che non è nel foglio WBS.",
            )  # fmt: skip
        senza = m.ContoCoge.objects.filter(cluster__isnull=True).count()
        if senza:
            self.report.anomalia(
                "Conti", None, "CONTO_SENZA_CLUSTER", "cluster", str(senza),
                f"{senza} conti del registro non sono nel foglio Conti e non hanno un cluster.",
            )  # fmt: skip
