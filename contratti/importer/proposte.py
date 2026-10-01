"""Proposte di raggruppamento in fabbisogni e di catena dei rinnovi (SPEC §7.4).

Si generano dopo l'import e si confermano a mano (admin o interfaccia), mai in automatico.
"""

import hashlib
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction

from contratti import adapters
from contratti import models as m
from contratti.importer.normalizza import chiave_nome

S = m.StatoProposta


def _gruppi(area: str):
    """Contratti importati raggruppati per descrizione normalizzata + fornitore."""
    gruppi = defaultdict(list)
    contratti = (
        m.Contratto.objects.filter(chiave_import__isnull=False, archiviato=False)
        .filter(fabbisogno__area=area)
        .select_related("fornitore", "procedura")
    )
    for c in contratti:
        gruppi[(chiave_nome(c.descrizione), c.fornitore_id)].append(c)
    return [g for g in gruppi.values() if len(g) > 1]


def genera(area: str) -> dict[str, int]:
    nuove = {"raggruppamento": 0, "predecessore": 0}
    for gruppo in _gruppi(area):
        gruppo.sort(key=lambda c: (c.data_inizio is None, c.data_inizio, c.pk))
        chiave = hashlib.sha256(
            "|".join(sorted(c.chiave_import for c in gruppo)).encode()
        ).hexdigest()[:40]
        if len({c.fabbisogno_id for c in gruppo}) > 1:
            proposta, creata = m.PropostaRaggruppamento.objects.get_or_create(
                chiave=chiave,
                defaults={
                    "motivazione": (
                        f"Stessa descrizione e fornitore: {gruppo[0].descrizione} — "
                        f"{gruppo[0].fornitore} ({len(gruppo)} contratti)"
                    )[:300]
                },
            )
            if creata:
                proposta.contratti.set(gruppo)
                nuove["raggruppamento"] += 1
        datati = [c for c in gruppo if c.data_inizio]
        for prima, dopo in zip(datati, datati[1:], strict=False):
            if dopo.predecessore_id == prima.pk:
                continue
            fine = adapters.data_fine_effettiva(prima)
            scarto = (dopo.data_inizio - fine).days - 1
            _, creata = m.PropostaPredecessore.objects.get_or_create(
                predecessore=prima,
                successore=dopo,
                defaults={
                    "motivazione": (
                        f"{prima.descrizione}: fine {fine:%d/%m/%Y}, rinnovo dal "
                        f"{dopo.data_inizio:%d/%m/%Y}"
                        + (f" (scarto di {scarto} giorni)" if scarto else "")
                    )[:300]
                },
            )
            nuove["predecessore"] += int(creata)
    return nuove


class PropostaNonApplicabile(Exception):
    pass


@transaction.atomic
def conferma_raggruppamento(proposta: m.PropostaRaggruppamento) -> m.Fabbisogno:
    """Unisce i contratti nel fabbisogno del più recente; archivia i provvisori svuotati."""
    if proposta.stato != S.PROPOSTA:
        raise PropostaNonApplicabile("Proposta già confermata o scartata.")
    contratti = list(proposta.contratti.select_related("fabbisogno"))
    recente = max(contratti, key=lambda c: (c.data_inizio is not None, c.data_inizio, c.pk))
    destinazione = recente.fabbisogno
    vecchi = {c.fabbisogno for c in contratti} - {destinazione}
    for c in contratti:
        if c.fabbisogno_id != destinazione.pk:
            c.fabbisogno = destinazione
            c.save(update_fields=["fabbisogno"])
    for f in vecchi:
        if not f.contratti.exists():
            f.archiviato = True
            f.save(update_fields=["archiviato"])
    proposta.stato = S.CONFERMATA
    proposta.save(update_fields=["stato"])
    return destinazione


@transaction.atomic
def conferma_predecessore(proposta: m.PropostaPredecessore) -> m.Contratto:
    if proposta.stato != S.PROPOSTA:
        raise PropostaNonApplicabile("Proposta già confermata o scartata.")
    successore, predecessore = proposta.successore, proposta.predecessore
    if successore.fabbisogno_id != predecessore.fabbisogno_id:
        raise PropostaNonApplicabile(
            "I due contratti sono in fabbisogni diversi: conferma prima il raggruppamento."
        )
    if m.Contratto.objects.filter(predecessore=predecessore).exclude(pk=successore.pk).exists():
        raise PropostaNonApplicabile("Il predecessore ha già un altro successore.")
    successore.predecessore = predecessore
    try:
        successore.full_clean()
    except ValidationError as exc:
        raise PropostaNonApplicabile("; ".join(exc.messages)) from exc
    successore.save(update_fields=["predecessore"])
    proposta.stato = S.CONFERMATA
    proposta.save(update_fields=["stato"])
    return successore


def scarta(proposta) -> None:
    if proposta.stato != S.PROPOSTA:
        raise PropostaNonApplicabile("Proposta già confermata o scartata.")
    proposta.stato = S.SCARTATA
    proposta.save(update_fields=["stato"])
