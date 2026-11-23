"""Richieste di annullamento del rilascio su SAP (SPEC §5.9, Rev56).

Il referente (chi modifica nel cluster dell'elemento) o l'addetto amministrativo chiede di
annullare il rilascio di una RDA, una RdC (ODA/RDC) o un MAP, con una motivazione obbligatoria.
L'addetto al rilascio riceve l'email e trova la richiesta nella maschera «Rilasci SAP»: annulla il
rilascio (con i servizi esistenti, che chiudono la richiesta come ``eseguita``) o la respinge con
una nota. In entrambi i casi chi ha chiesto riceve l'esito per email.
"""

import datetime

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from accounts.roles import WRITE_ROLES, role_of
from contratti import acquisti, notifiche, permessi
from contratti import models as m
from contratti.acquisti import OperazioneNonAmmessa
from contratti.engine import acquisti as motore

Stato = m.RichiestaAnnullamentoRilascio.Stato


def _filtro(oggetto) -> dict:
    if isinstance(oggetto, m.RichiestaAcquisto):
        return {"rda": oggetto}
    if isinstance(oggetto, m.DocumentoEsecuzione):
        return {"documento": oggetto}
    raise TypeError(f"Elemento senza rilascio: {type(oggetto).__name__}")


def aperta(oggetto) -> m.RichiestaAnnullamentoRilascio | None:
    """La richiesta in attesa per l'elemento, se c'è."""
    return (
        m.RichiestaAnnullamentoRilascio.objects.select_related("richiesta_da")
        .filter(stato=Stato.APERTA, **_filtro(oggetto))
        .first()
    )


def aperte():
    """Richieste in attesa, per la maschera dei rilasci: le più vecchie in cima."""
    return (
        m.RichiestaAnnullamentoRilascio.objects.filter(stato=Stato.APERTA)
        .select_related(
            "richiesta_da", "documento__fattura__fornitore", "documento__contratto", "rda"
        )
        .order_by("richiesta_il", "pk")
    )


def puo_chiedere(utente, oggetto) -> bool:
    """Chiede l'annullamento chi modifica l'elemento nel suo cluster (il referente) e l'addetto
    amministrativo. L'addetto al rilascio non chiede: annulla direttamente."""
    if role_of(utente) not in WRITE_ROLES:
        return False
    if permessi.e_addetto(utente):
        return True
    if isinstance(oggetto, m.RichiestaAcquisto):
        return permessi.puo_modificare_oggetto(utente, oggetto)
    from contratti import fatture  # fatture importa questo modulo

    return oggetto.fattura_id is not None and fatture.puo_lavorare(utente, oggetto.fattura)


def motivo_non_annullabile(oggetto) -> str:
    """Perché il rilascio dell'elemento non si può annullare ora ("" se si può)."""
    if oggetto.archiviato:
        return "l'elemento è archiviato"
    if isinstance(oggetto, m.RichiestaAcquisto):
        if acquisti.fase(oggetto) != motore.Fase.RILASCIATA:
            return "il rilascio si annulla solo per una RDA rilasciata, senza contratto"
        return ""
    if oggetto.data_rilascio is None:
        return "il documento non è rilasciato"
    if oggetto.fattura_id and oggetto.fattura.data_trasferimento is not None:
        return "la fattura è trasferita: prima si annulla il trasferimento"
    return ""


def chiedi(
    oggetto, motivazione: str, utente, data: datetime.date | None = None
) -> m.RichiestaAnnullamentoRilascio:
    """Registra la richiesta e avvisa gli addetti al rilascio (dopo il commit)."""
    if not puo_chiedere(utente, oggetto):
        raise PermissionDenied("Non puoi chiedere l'annullamento di questo rilascio.")
    motivazione = (motivazione or "").strip()
    if not motivazione:
        raise OperazioneNonAmmessa("Scrivi la motivazione: l'addetto al rilascio la legge.")
    motivo = motivo_non_annullabile(oggetto)
    if motivo:
        raise OperazioneNonAmmessa(motivo[0].upper() + motivo[1:] + ".")
    with transaction.atomic():
        # Blocca l'elemento: due richieste contemporanee non passano entrambe.
        type(oggetto).objects.select_for_update().filter(pk=oggetto.pk).first()
        if aperta(oggetto):
            raise OperazioneNonAmmessa("C'è già una richiesta di annullamento in attesa.")
        richiesta = m.RichiestaAnnullamentoRilascio(
            motivazione=motivazione,
            richiesta_il=data or timezone.localdate(),
            richiesta_da=utente,
            **_filtro(oggetto),
        )
        richiesta._change_reason = "Annullamento del rilascio richiesto"
        richiesta.save()
        notifiche.dopo_commit(lambda: notifiche.annullamento_richiesto(richiesta))
    return richiesta


def chiudi_dopo_annullamento(oggetto, utente, data: datetime.date | None = None) -> str:
    """Chiamata dai servizi che annullano il rilascio: la richiesta aperta diventa ``eseguita``
    e chi l'ha fatta riceve l'esito. Restituisce la motivazione ("" senza richiesta), da
    riportare nel motivo della modifica dell'elemento."""
    richiesta = aperta(oggetto)
    if richiesta is None:
        return ""
    richiesta.stato = Stato.ESEGUITA
    richiesta.chiusa_il = data or timezone.localdate()
    richiesta.chiusa_da = utente
    richiesta._change_reason = "Rilascio annullato"
    richiesta.save(update_fields=["stato", "chiusa_il", "chiusa_da"])
    notifiche.dopo_commit(lambda: notifiche.annullamento_deciso(richiesta, utente))
    return richiesta.motivazione


def respingi(
    richiesta: m.RichiestaAnnullamentoRilascio,
    nota: str,
    utente,
    data: datetime.date | None = None,
) -> None:
    """L'addetto al rilascio respinge la richiesta, con una nota: il rilascio resta."""
    if not permessi.puo_rilasciare(utente):
        raise PermissionDenied("Non sei addetto al rilascio.")
    nota = (nota or "").strip()
    if not nota:
        raise OperazioneNonAmmessa(
            "Scrivi la nota: spiega a chi ha chiesto perché il rilascio resta."
        )
    with transaction.atomic():
        richiesta = m.RichiestaAnnullamentoRilascio.objects.select_for_update().get(pk=richiesta.pk)
        if richiesta.stato != Stato.APERTA:
            raise OperazioneNonAmmessa("La richiesta è già stata decisa.")
        richiesta.stato = Stato.RESPINTA
        richiesta.chiusa_il = data or timezone.localdate()
        richiesta.chiusa_da = utente
        richiesta.nota_esito = nota
        richiesta._change_reason = "Richiesta di annullamento respinta"
        richiesta.save(update_fields=["stato", "chiusa_il", "chiusa_da", "nota_esito"])
        notifiche.dopo_commit(lambda: notifiche.annullamento_deciso(richiesta, utente))
