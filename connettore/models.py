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


class OperazioneMCP(models.Model):
    """Scrittura proposta dal connettore: anteprima, poi conferma (SPEC_MCP §8.1).

    Legata a utente, tool, argomenti e versione degli oggetti toccati; vale pochi minuti e si
    conferma una volta sola. Le operazioni non si cancellano: scadono.
    """

    class Stato(models.TextChoices):
        IN_ATTESA = "in_attesa", "in attesa di conferma"
        CONFERMATA = "confermata", "confermata"
        RIFIUTATA = "rifiutata", "rifiutata alla conferma"

    codice = models.CharField(max_length=40, unique=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    client_id = models.CharField("client OAuth", max_length=255, blank=True)
    tool = models.CharField(max_length=60)
    argomenti = models.JSONField(default=dict)
    versioni = models.JSONField("versioni degli oggetti", default=dict)
    anteprima = models.JSONField(default=dict)
    creata_il = models.DateTimeField(auto_now_add=True)
    scade_il = models.DateTimeField()
    stato = models.CharField(max_length=12, choices=Stato.choices, default=Stato.IN_ATTESA)
    confermata_il = models.DateTimeField(null=True, blank=True)
    esito = models.JSONField(default=dict, blank=True)
    messaggio = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "operazione del connettore MCP"
        verbose_name_plural = "operazioni del connettore MCP"
        ordering = ["-creata_il"]

    def __str__(self):
        return f"{self.creata_il:%d/%m/%Y %H:%M} {self.utente} {self.tool} {self.stato}"
