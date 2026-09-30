from pathlib import Path

import ldap
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security)
def ldap_ca_leggibile(app_configs, **kwargs):
    """Una CA mancante farebbe fallire ogni login LDAP con un errore 500."""
    options = getattr(settings, "AUTH_LDAP_CONNECTION_OPTIONS", None) or {}
    ca_file = options.get(ldap.OPT_X_TLS_CACERTFILE)
    if not getattr(settings, "ACCOUNTS_LDAP_ENABLED", False) or not ca_file:
        return []
    if Path(ca_file).is_file():
        return []
    return [
        Error(
            f"LDAP_CA_CERT_FILE non trovato: {ca_file}",
            hint="Montare il certificato della CA interna o correggere il percorso.",
            id="accounts.E001",
        )
    ]


@register(Tags.security, deploy=True)
def ldap_attivo_in_produzione(app_configs, **kwargs):
    if getattr(settings, "ACCOUNTS_LDAP_ENABLED", False):
        return []
    return [
        Warning(
            "LDAP_SERVER_URI non valorizzata: vale solo il login locale.",
            hint="In produzione configurare LDAP (SPEC §8.1).",
            id="accounts.W001",
        )
    ]
