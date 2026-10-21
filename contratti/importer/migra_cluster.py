"""Dai cluster piatti ai cluster con sottocluster (Rev25): sposta i dati esistenti.

Dopo l'import della struttura dal budget, i vecchi cluster (IT, TLC, OT, ...) sono diventati
sottocluster dei nuovi (ICT, DIGITALIZZAZIONE, ...). Per ogni vecchio cluster si cerca il
sottocluster con lo stesso nome (o la stessa sigla) e si porta lì ciò che era del vecchio
cluster: fabbisogni, richieste d'acquisto, WBS di cluster, autorizzazioni extra budget, conti
e assegnazioni dei responsabili (che diventano assegnazioni del sottocluster). Il vecchio
cluster, rimasto vuoto, si archivia.

- Il sottocluster nello stesso cluster (es. INN → Innovazione): i fabbisogni senza
  sottocluster lo ricevono, niente si sposta.
- Fabbisogni che hanno già un sottocluster del vecchio cluster: non si toccano, segnalati.
- Tutto o niente, idempotente (a regime non c'è più nulla da spostare), mai cancellazioni;
  le modifiche hanno la storia. ``mappa`` forza le corrispondenze: {codice vecchio:
  (codice nuovo cluster, nome sottocluster)}.
"""

import re

from django.db import transaction

from contratti import models as m
from contratti.importer.report import Report
from contratti.importer.struttura_budget import chiave

FOGLIO = "Migrazione cluster"
MOTIVO = "Migrazione cluster/sottocluster"
CONTEGGI = (
    "fabbisogni_spostati", "fabbisogni_classificati", "richieste_spostate", "wbs_spostate",
    "autorizzazioni_spostate", "conti_aggiornati", "assegnazioni_convertite", "cluster_archiviati",
)  # fmt: skip


class _Rollback(Exception):
    pass


def _senza_parentesi(nome: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", nome)


def _salva(oggetto, **campi):
    for k, v in campi.items():
        setattr(oggetto, k, v)
    oggetto._change_reason = MOTIVO
    oggetto.save()


def trova_corrispondenze(
    mappa: dict[str, tuple[str, str]] | None, report: Report
) -> dict[int, m.Sottocluster]:
    """{pk del vecchio cluster: sottocluster di destinazione}."""
    mappa = mappa or {}
    attivi = list(m.Sottocluster.objects.filter(archiviato=False).select_related("cluster"))
    trovate: dict[int, m.Sottocluster] = {}
    for vecchio in m.Cluster.objects.filter(archiviato=False).order_by("codice"):
        if vecchio.codice in mappa:
            codice, nome = mappa[vecchio.codice]
            candidati = [
                s for s in attivi if s.cluster.codice == codice and chiave(s.nome) == chiave(nome)
            ]
        else:
            nomi = {chiave(vecchio.nome), chiave(vecchio.codice)}
            candidati = [
                s
                for s in attivi
                if chiave(s.nome) in nomi or chiave(_senza_parentesi(s.nome)) in nomi
            ]
        if len(candidati) == 1:
            trovate[vecchio.pk] = candidati[0]
        elif len(candidati) > 1:
            elenco = ", ".join(f"{s.cluster.codice}/{s.nome}" for s in candidati)
            report.anomalia(
                FOGLIO,
                None,
                "SOTTOCLUSTER_AMBIGUO",
                "cluster",
                vecchio.codice,
                f"Più sottocluster possibili: {elenco}. Indica la corrispondenza.",
            )
        elif vecchio.sottocluster.exists():  # è un cluster nuovo, con i suoi sottocluster
            continue
        else:
            report.anomalia(
                FOGLIO,
                None,
                "CLUSTER_SENZA_CORRISPONDENZA",
                "cluster",
                vecchio.codice,
                "Nessun sottocluster con lo stesso nome: non tocco.",
            )
    return trovate


def migra_cluster(
    *, dry_run: bool = False, mappa: dict[str, tuple[str, str]] | None = None
) -> Report:
    report = Report(file="migra_cluster", dry_run=dry_run)
    for chiave_conteggio in CONTEGGI:
        report.conteggi[chiave_conteggio] = 0
    try:
        with transaction.atomic():
            _esegui(report, mappa)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


def _esegui(report: Report, mappa):
    corrispondenze = trova_corrispondenze(mappa, report)
    for pk, sotto in corrispondenze.items():
        vecchio = m.Cluster.objects.get(pk=pk)
        if sotto.cluster_id == vecchio.pk:
            _classifica(report, vecchio, sotto)
        else:
            _sposta(report, vecchio, sotto)


def _classifica(report: Report, cluster: m.Cluster, sotto: m.Sottocluster):
    for fab in m.Fabbisogno.objects.filter(cluster=cluster, sottocluster__isnull=True):
        _salva(fab, sottocluster=sotto)
        report.conteggi["fabbisogni_classificati"] += 1


def _sposta(report: Report, vecchio: m.Cluster, sotto: m.Sottocluster):
    nuovo = sotto.cluster
    for fab in m.Fabbisogno.objects.filter(cluster=vecchio):
        if fab.sottocluster_id and fab.sottocluster.cluster_id == vecchio.pk:
            report.anomalia(
                FOGLIO,
                fab.pk,
                "FABBISOGNO_CON_SOTTOCLUSTER_VECCHIO",
                "fabbisogno",
                fab.descrizione,
                f"Ha già il sottocluster «{fab.sottocluster.nome}» di {vecchio.codice}: "
                "spostalo a mano.",
            )
            continue
        _salva(fab, cluster=nuovo, sottocluster=fab.sottocluster or sotto)
        report.conteggi["fabbisogni_spostati"] += 1
    for rda in m.RichiestaAcquisto.objects.filter(cluster=vecchio):
        _salva(rda, cluster=nuovo)
        report.conteggi["richieste_spostate"] += 1
    for wbs in m.WBS.objects.filter(cluster=vecchio):
        _salva(wbs, cluster=nuovo)
        report.conteggi["wbs_spostate"] += 1
    for aut in m.AutorizzazioneExtraBudget.objects.filter(cluster=vecchio):
        _salva(aut, cluster=nuovo)
        report.conteggi["autorizzazioni_spostate"] += 1
    for conto in m.ContoCoge.objects.filter(clusters=vecchio):
        conto.clusters.remove(vecchio)
        conto.clusters.add(nuovo)
        report.conteggi["conti_aggiornati"] += 1
    for a in m.AssegnazioneCluster.objects.filter(cluster=vecchio, sottocluster__isnull=True):
        doppia = m.AssegnazioneCluster.objects.filter(
            username=a.username, cluster=nuovo, sottocluster=sotto
        ).first()
        if doppia is None:
            _salva(a, cluster=nuovo, sottocluster=sotto)
        else:  # già assegnato: l'assegnazione vecchia si archivia, quella nuova vale
            era_attiva = not a.archiviato
            _salva(a, archiviato=True)
            if doppia.archiviato and era_attiva:
                _salva(doppia, archiviato=False)
        report.conteggi["assegnazioni_convertite"] += 1
    if not _riferito(vecchio):
        _salva(vecchio, archiviato=True)
        report.conteggi["cluster_archiviati"] += 1


def _riferito(cluster: m.Cluster) -> bool:
    """Il vecchio cluster ha ancora qualcosa che lo usa?"""
    return any(
        (
            cluster.fabbisogni.exists(),
            cluster.richieste_acquisto.exists(),
            cluster.wbs.exists(),
            cluster.autorizzazioni_extra_budget.exists(),
            cluster.conti.exists(),
            cluster.sottocluster.exists(),
            cluster.assegnazioni.filter(archiviato=False).exists(),
        )
    )
