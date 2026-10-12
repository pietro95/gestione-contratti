from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q


class User(AbstractUser):
    """Utente dell'applicazione. Gli utenti AD si creano al primo login LDAP."""

    is_breakglass = models.BooleanField(
        "account di emergenza",
        default=False,
        help_text="Account locale di emergenza (break-glass). Ne esiste al massimo uno.",
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "utente"
        verbose_name_plural = "utenti"
        constraints = [
            models.UniqueConstraint(
                fields=["is_breakglass"],
                condition=Q(is_breakglass=True),
                name="accounts_user_un_solo_breakglass",
            ),
        ]

    def __str__(self):
        """Nome completo da Active Directory (givenName + sn); username se manca."""
        return self.get_full_name() or self.get_username()


class LoginAttempt(models.Model):
    """Log dei login riusciti e falliti (SPEC §8.2). Mai la password."""

    class Esito(models.TextChoices):
        OK = "ok", "riuscito"
        CREDENZIALI_ERRATE = "credenziali_errate", "credenziali errate o utente sconosciuto"
        NESSUN_GRUPPO = "nessun_gruppo", "nessun gruppo applicativo"
        LDAP_NON_DISPONIBILE = "ldap_non_disponibile", "server LDAP non disponibile"
        ERRORE_LDAP = "errore_ldap", "errore LDAP"

    timestamp = models.DateTimeField("data e ora", auto_now_add=True, db_index=True)
    username = models.CharField("nome utente", max_length=150, db_index=True)
    success = models.BooleanField("riuscito")
    esito = models.CharField(max_length=32, choices=Esito.choices)
    backend = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField("indirizzo IP", null=True, blank=True)

    class Meta:
        verbose_name = "tentativo di accesso"
        verbose_name_plural = "tentativi di accesso"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%d/%m/%Y %H:%M:%S} {self.username} {self.esito}"
