"""Caricamento nel database delle righe normalizzate (SPEC §7, TC-08).

- Righe con stesso numero di contratto, CIG e periodo → un contratto con più voci.
- Stesso numero di contratto e CIG ma periodi diversi → contratti distinti e anomalia ODA_RIUSATO.
- Ogni contratto entra in un proprio fabbisogno provvisorio; raggruppamenti e catene
  dei rinnovi restano proposte da confermare (``proposte.py``).
- Incrementale: un contratto già registrato non si ricrea né si modifica, e la riga è
  scartata con un'anomalia GIA_PRESENTE. Si riconosce dalla chiave d'import e, se il file è
  cambiato (righe spostate o inserite, foglio rinominato, altro cluster) o il contratto è
  stato inserito a mano, da numero di contratto o CIG con la data di inizio; senza codici,
  da fornitore, descrizione, data di inizio e durata.
- ``dry_run``: stesso report, nessuna scrittura (rollback).
"""

import datetime
import hashlib
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.db import transaction

from contratti import models as m
from contratti.importer import proposte
from contratti.importer.lettura import Riga, leggi, normalizza_riga
from contratti.importer.normalizza import chiave_nome
from contratti.importer.report import Report

FORNITORE_NON_INDICATO = "(non indicato)"
DESCRIZIONE_ASSENTE = "(senza descrizione)"
WBS_DA_DEFINIRE = "WBS-DA-DEFINIRE"


def raggruppa(righe: list[Riga]) -> dict[tuple, list[Riga]]:
    """Stesso foglio, numero di contratto, CIG e periodo → un contratto (ordine delle righe)."""
    gruppi: dict[tuple, list[Riga]] = defaultdict(list)
    for r in righe:
        if r.numero_contratto or r.cig:
            chiave = (r.foglio, r.numero_contratto, r.cig, r.data_inizio, r.mesi)
        else:
            chiave = (r.foglio, None, None, r.numero)
        gruppi[chiave].append(r)
    return gruppi


def chiave_contratto(area: str, chiave_gruppo: tuple) -> str:
    return _hash(area, *chiave_gruppo)


def chiave_voce(chiave_del_contratto: str, indice: int) -> str:
    return _hash(f"{chiave_del_contratto}:{indice}")


class _Rollback(Exception):
    pass


def _hash(*parti) -> str:
    return hashlib.sha256("|".join(str(p) for p in parti).encode()).hexdigest()[:40]


def importa(
    percorso: str | Path,
    *,
    area: str,
    dry_run: bool = False,
    oggi: datetime.date | None = None,
) -> Report:
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    libro = leggi(percorso)
    righe = [normalizza_riga(g) for g in libro.righe]
    report.conteggi["righe_lette"] = len(righe)
    for r in righe:
        for a in r.anomalie:
            report.anomalia(r.foglio, r.numero, a.codice, a.campo, a.valore, a.messaggio)
        if r.conto_vecchio and r.conto and r.conto_vecchio != r.conto:
            report.mappature_conti[(r.conto_vecchio, r.conto)] += 1
    try:
        with transaction.atomic():
            _Caricamento(report, area, oggi or datetime.date.today()).esegui(righe, libro.fornitori)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


class _Caricamento:
    def __init__(self, report: Report, area: str, oggi: datetime.date):
        self.report = report
        self.area = area
        try:
            self.cluster = m.Cluster.objects.get(codice=area)
        except m.Cluster.DoesNotExist as exc:
            raise ValueError(f"Cluster inesistente: {area}.") from exc
        self.oggi = oggi
        self.procedura = m.Procedura.objects.get(codice="da_verificare")
        self.categoria = m.Categoria.objects.get(nome="Da classificare")
        self.conti = {c.codice: c for c in m.ContoCoge.objects.order_by("valido_dal")}
        self.fornitori = {chiave_nome(f.ragione_sociale): f for f in m.Fornitore.objects.all()}
        self.creati_ora: set[str] = set()

    # --- Fornitori ---------------------------------------------------------------

    def carica_anagrafica_fornitori(self, elenco):
        """Foglio Fornitori: codici SAP, duplicati e codici condivisi segnalati."""
        visti: dict[str, str | None] = {}
        per_codice: dict[str, set[str]] = defaultdict(set)
        for nome, codice in elenco:
            k = chiave_nome(nome)
            if k in visti:
                self.report.anomalia(
                    "Fornitori", None, "FORNITORE_DUPLICATO", "fornitore", nome,
                    f"Compare più volte nell'anagrafica (codici: {visti[k]}, {codice}).",
                )  # fmt: skip
            visti[k] = visti.get(k) or codice
            if codice:
                per_codice[codice].add(nome)
            self._fornitore(nome, codice, da_anagrafica=True)
        for codice, nomi in sorted(per_codice.items()):
            if len(nomi) > 1:
                self.report.anomalia(
                    "Fornitori", None, "CODICE_SAP_CONDIVISO", "codice_sap", codice,
                    f"Codice assegnato a {len(nomi)} fornitori: {', '.join(sorted(nomi))}.",
                )  # fmt: skip

    def _fornitore(
        self, nome: str, codice: str | None = None, *, da_anagrafica: bool = False
    ) -> m.Fornitore:
        k = chiave_nome(nome)
        f = self.fornitori.get(k)
        if f is None:
            f = m.Fornitore.objects.create(ragione_sociale=nome, codice_sap=codice or "")
            self.fornitori[k] = f
            self.creati_ora.add(k)
            self.report.conteggi["fornitori_creati"] += 1
        elif codice and not f.codice_sap:
            f.codice_sap = codice
            f.save(update_fields=["codice_sap"])
        elif da_anagrafica and not codice and f.codice_sap and k not in self.creati_ora:
            self.report.anomalia(
                "Fornitori", None, "CODICE_SAP_MANCANTE_NEL_FILE", "codice_sap", nome,
                f"In archivio ha il codice {f.codice_sap}, in questo file no.",
            )  # fmt: skip
        elif codice and f.codice_sap != codice:
            self.report.anomalia(
                "Fornitori", None, "CODICE_SAP_DIVERGENTE", "codice_sap", codice,
                f"{f.ragione_sociale}: in archivio {f.codice_sap}, nel file {codice}.",
            )  # fmt: skip
        return f

    # --- Contratti ---------------------------------------------------------------

    def esegui(self, righe: list[Riga], anagrafica):
        self.carica_anagrafica_fornitori(anagrafica)
        for r in righe:
            if r.conto and r.conto not in self.conti:
                self.report.anomalia(
                    r.foglio, r.numero, "CONTO_SCONOSCIUTO", "conto", r.conto,
                    "Conto non presente nel piano dei conti.",
                )  # fmt: skip
        gruppi = raggruppa(righe)

        periodi_per_oda = defaultdict(set)
        for (_foglio, oda, cig, *resto), _ in gruppi.items():
            if oda or cig:
                periodi_per_oda[(oda, cig)].add(tuple(resto))
        for chiave, gruppo in gruppi.items():
            oda, cig = chiave[1], chiave[2]
            if (oda or cig) and len(periodi_per_oda[(oda, cig)]) > 1:
                for r in gruppo:
                    self.report.anomalia(
                        r.foglio, r.numero, "ODA_RIUSATO", "numero_contratto", oda or cig,
                        "Stesso numero e CIG, periodi diversi: contratti distinti, da verificare.",
                    )  # fmt: skip
            self._contratto(chiave, gruppo)

        nuove = proposte.genera(self.area)
        self.report.conteggi["proposte_raggruppamento"] += nuove["raggruppamento"]
        self.report.conteggi["proposte_predecessore"] += nuove["predecessore"]

    def gia_presente(self, chiave: str, primo: Riga) -> m.Contratto | None:
        """Il contratto registrato che corrisponde alla riga, se c'è (archiviati compresi)."""
        trovato = m.Contratto.objects.filter(chiave_import=chiave).first()
        if trovato is not None:
            return trovato
        candidati = m.Contratto.objects.filter(data_inizio=primo.data_inizio)
        if primo.numero_contratto:
            return candidati.filter(numero_contratto=primo.numero_contratto).first()
        if primo.cig:
            return candidati.filter(numero_contratto__isnull=True, cig=primo.cig).first()
        fornitore = chiave_nome(primo.fornitore or FORNITORE_NON_INDICATO)
        descrizione = chiave_nome(primo.descrizione or DESCRIZIONE_ASSENTE)
        for c in candidati.filter(
            numero_contratto__isnull=True, cig__isnull=True, durata_mesi=primo.mesi
        ).select_related("fornitore"):
            if (
                chiave_nome(c.fornitore.ragione_sociale) == fornitore
                and chiave_nome(c.descrizione) == descrizione
            ):
                return c
        return None

    def _contratto(self, chiave_gruppo: tuple, gruppo: list[Riga]):
        primo = gruppo[0]
        chiave = chiave_contratto(self.area, chiave_gruppo)
        esistente = self.gia_presente(chiave, primo)
        if esistente is not None:
            self.report.conteggi["contratti_gia_presenti"] += 1
            if esistente.chiave_import != chiave:
                righe = ", ".join(str(r.numero) for r in gruppo)
                self.report.anomalia(
                    primo.foglio, primo.numero, "GIA_PRESENTE", "contratto",
                    primo.numero_contratto or primo.cig or primo.descrizione or "",
                    f"Riga {righe}: contratto già registrato (id {esistente.pk}, "
                    f"{esistente.fabbisogno.descrizione}). Scartata, nessuna modifica.",
                )  # fmt: skip
            return
        fornitore = self._fornitore(primo.fornitore or FORNITORE_NON_INDICATO)
        descrizione = primo.descrizione or DESCRIZIONE_ASSENTE
        fabbisogno = m.Fabbisogno.objects.create(
            descrizione=descrizione,
            cluster=self.cluster,
            categoria=self.categoria,
            decisione=primo.decisione,
            note="Fabbisogno provvisorio creato dall'import Excel.",
        )
        progetto = None
        if primo.finanziato:
            codice = primo.wbs or WBS_DA_DEFINIRE
            progetto, _ = m.Progetto.objects.get_or_create(
                codice_wbs=codice,
                defaults={"descrizione": "Da definire" if not primo.wbs else codice},
            )
        note = [f"Import Excel: {primo.foglio}, riga {', '.join(str(r.numero) for r in gruppo)}."]
        note += [r.note for r in gruppo if r.note]
        contratto = m.Contratto.objects.create(
            fabbisogno=fabbisogno,
            fornitore=fornitore,
            descrizione=descrizione,
            numero_contratto=primo.numero_contratto,
            cig=primo.cig,
            numero_rda=next((r.numero_rda for r in gruppo if r.numero_rda), None),
            procedura=self.procedura,
            data_inizio=primo.data_inizio,
            durata_mesi=primo.mesi,
            finanziamento="finanziato" if progetto else "ordinario",
            progetto=progetto,
            note="\n".join(note),
            chiave_import=chiave,
        )
        self.report.conteggi["contratti_creati"] += 1
        if primo.stato_pratica:
            m.StatoPratica.objects.create(
                contratto=contratto,
                stato=primo.stato_pratica,
                data=self.oggi,
                note="Stato importato dall'Excel.",
            )
        for i, r in enumerate(gruppo):
            self._voce(contratto, r, chiave_voce(chiave, i))

    def _voce(self, contratto: m.Contratto, r: Riga, chiave: str):
        conto = self.conti.get(r.conto) if r.conto else None
        voce = m.VoceContratto.objects.create(
            contratto=contratto,
            descrizione=r.descrizione or DESCRIZIONE_ASSENTE,
            conto=conto,
            codice_conto_importato=r.conto or "",
            importo_fisso=r.minimo or Decimal("0.00"),
            massimale_variabile=r.extra or Decimal("0.00"),
            chiave_import=chiave,
        )
        m.PianoFatturazione.objects.create(voce=voce, modalita="da_verificare", periodicita="")
        self.report.conteggi["voci_create"] += 1
