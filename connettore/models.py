"""Registro delle chiamate al connettore MCP (SPEC_MCP §6). Mai il contenuto dei risultati."""

from django.conf import settings
from django.db import models


class RegistroChiamata(models.Model):
    """Una richiesta a ``/mcp``: chi, quale metodo o tool, esito, durata."""

    class Esito(models.TextChoices):
        OK = "ok", "riuscita"
        ERRORE_TOOL = "errore_tool", "errore del tool"
        ERRORE_PROTOCOLLO = "errore_protocollo", "errore di protocollo"
        NON_AUTORIZZATA = "non_autorizzata", "non autorizzata"
        LIMITE = "limite", "limite di frequenza"

    timestamp = models.DateTimeField("data e ora", auto_now_add=True, db_index=True)
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    client_id = models.CharField("client OAuth", max_length=255, blank=True)
    # Hash dell'access token: serve al limite di frequenza per collegamento, mai il token.
    token_hash = models.CharField(max_length=64, blank=True, db_index=True)
    metodo = models.CharField("metodo JSON-RPC", max_length=60, blank=True)
    tool = models.CharField(max_length=60, blank=True)
    argomenti = models.JSONField(default=dict, blank=True)
    esito = models.CharField(max_length=20, choices=Esito.choices)
    messaggio = models.CharField(max_length=300, blank=True)
    durata_ms = models.PositiveIntegerField(default=0)
    elementi = models.PositiveIntegerField("elementi restituiti", null=True, blank=True)
    ip = models.GenericIPAddressField("indirizzo IP", null=True, blank=True)

    class Meta:
        verbose_name = "chiamata al connettore MCP"
        verbose_name_plural = "chiamate al connettore MCP"
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["token_hash", "timestamp"])]

    def __str__(self):
        cosa = self.tool or self.metodo or "-"
        return f"{self.timestamp:%d/%m/%Y %H:%M:%S} {self.utente or '-'} {cosa} {self.esito}"
