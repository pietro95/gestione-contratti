"""Contesto di un'operazione di scrittura del connettore (SPEC_MCP §8.1, punto 8).

Durante l'esecuzione di un tool di scrittura ogni record di ``django-simple-history`` porta
l'utente reale e il motivo ``MCP <tool> <operazione>`` (in testa al motivo del servizio, se
c'è), e viene raccolto: l'anteprima ne ricava le modifiche campo per campo.
"""

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass, field

from django.dispatch import receiver
from simple_history.signals import post_create_historical_record, pre_create_historical_record

MOTIVO_MAX = 100  # history_change_reason di simple-history


@dataclass
class Esecuzione:
    utente: object
    motivo: str
    registrati: list = field(default_factory=list)


_corrente: ContextVar[Esecuzione | None] = ContextVar("esecuzione_mcp", default=None)


@contextlib.contextmanager
def esecuzione(utente, motivo: str):
    stato = Esecuzione(utente, motivo)
    token = _corrente.set(stato)
    try:
        yield stato
    finally:
        _corrente.reset(token)


@receiver(pre_create_historical_record)
def _utente_e_motivo(sender, history_instance, **kwargs):
    stato = _corrente.get()
    if stato is None:
        return
    history_instance.history_user = stato.utente
    motivo = stato.motivo
    if history_instance.history_change_reason:
        motivo = f"{motivo}: {history_instance.history_change_reason}"
    if len(motivo) > MOTIVO_MAX:
        motivo = motivo[: MOTIVO_MAX - 1] + "…"
    history_instance.history_change_reason = motivo


@receiver(post_create_historical_record)
def _raccogli(sender, history_instance, **kwargs):
    stato = _corrente.get()
    if stato is not None:
        stato.registrati.append(history_instance)
