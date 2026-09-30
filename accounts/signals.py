"""Log dei login (SPEC §8.2): riga in ``LoginAttempt`` e messaggio sul logger ``accounts.auth``."""

import logging

import ldap
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django_auth_ldap.backend import ldap_error

from accounts.backends import get_failure_reason, set_failure_reason
from accounts.models import LoginAttempt

logger = logging.getLogger("accounts.auth")


def _client_ip(request):
    # Dietro il reverse proxy REMOTE_ADDR è il proxy; X-Forwarded-For si valuterà in F6.
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


@receiver(ldap_error)
def on_ldap_error(sender, context, user, request, exception, **kwargs):
    if isinstance(exception, ldap.SERVER_DOWN | ldap.TIMEOUT | ldap.CONNECT_ERROR):
        esito = LoginAttempt.Esito.LDAP_NON_DISPONIBILE
    else:
        esito = LoginAttempt.Esito.ERRORE_LDAP
    set_failure_reason(request, esito)
    # Il dettaglio tecnico va solo nel log applicativo, mai all'utente.
    logger.error("errore LDAP (%s): %s", context, type(exception).__name__)


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    backend = getattr(user, "backend", "") or ""
    LoginAttempt.objects.create(
        username=user.get_username(),
        success=True,
        esito=LoginAttempt.Esito.OK,
        backend=backend,
        ip_address=_client_ip(request),
    )
    logger.info("login riuscito utente=%s backend=%s", user.get_username(), backend)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials.get("username") or "")[:150]
    esito = get_failure_reason(request)
    LoginAttempt.objects.create(
        username=username,
        success=False,
        esito=esito,
        ip_address=_client_ip(request),
    )
    logger.warning("login fallito utente=%s esito=%s", username, esito)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        logger.info("logout utente=%s", user.get_username())
