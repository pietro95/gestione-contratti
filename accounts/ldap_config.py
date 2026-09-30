"""Configurazione dell'autenticazione a partire dalle variabili d'ambiente.

``build_ldap_settings`` è pura: riceve una mappa di variabili (di solito ``os.environ``) e
restituisce i settings ``AUTH_LDAP_*`` da aggiungere a Django. Se ``LDAP_SERVER_URI`` è vuota
restituisce un dizionario vuoto e vale solo l'autenticazione locale.

Regole (SPEC §8.1):
- mai bind in chiaro: ``ldaps://`` oppure ``ldap://`` con StartTLS;
- account di servizio per la ricerca, login con ``sAMAccountName``;
- ruoli dai gruppi AD configurabili, gruppi annidati inclusi.
"""

from collections.abc import Mapping
from typing import Any

import ldap
from django.core.exceptions import ImproperlyConfigured
from django_auth_ldap.config import (
    ActiveDirectoryGroupType,
    LDAPSearch,
    NestedActiveDirectoryGroupType,
)

from accounts.ldap_groups import ADMatchingRuleGroupType
from accounts.roles import ADMIN, EDITOR, READER

LDAP_BACKEND = "accounts.backends.RoleLDAPBackend"
BREAKGLASS_BACKEND = "accounts.backends.BreakGlassBackend"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"

NESTED_STRATEGIES = {
    # AD: una sola query con LDAP_MATCHING_RULE_IN_CHAIN (1.2.840.113556.1.4.1941).
    "matching_rule": ADMatchingRuleGroupType,
    # Qualsiasi server: risale i gruppi con una query per livello.
    "recursive": NestedActiveDirectoryGroupType,
    # Solo appartenenza diretta.
    "none": ActiveDirectoryGroupType,
}

_TRUE = {"1", "true", "yes", "on", "si", "sì"}
_FALSE = {"0", "false", "no", "off"}


def _get(environ: Mapping[str, str], name: str, default: str = "") -> str:
    return (environ.get(name) or default).strip()


def _require(environ: Mapping[str, str], name: str) -> str:
    value = _get(environ, name)
    if not value:
        raise ImproperlyConfigured(f"{name} è obbligatoria quando LDAP_SERVER_URI è valorizzata.")
    return value


def _bool(environ: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = _get(environ, name).lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name} deve essere un booleano, trovato {raw!r}.")


def _int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = _get(environ, name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} deve essere un intero, trovato {raw!r}.") from exc
    if value <= 0:
        raise ImproperlyConfigured(f"{name} deve essere positivo.")
    return value


def build_ldap_settings(environ: Mapping[str, str]) -> dict[str, Any]:
    """Settings ``AUTH_LDAP_*`` e ``ACCOUNTS_LDAP_ROLE_GROUPS``; ``{}`` se LDAP è spento."""
    uri = _get(environ, "LDAP_SERVER_URI")
    if not uri:
        return {}

    start_tls = _bool(environ, "LDAP_START_TLS")
    scheme = uri.split("://", 1)[0].lower()
    if scheme == "ldap" and not start_tls:
        raise ImproperlyConfigured(
            "Bind in chiaro non ammesso: usare ldaps:// oppure ldap:// con LDAP_START_TLS=true."
        )
    if scheme == "ldaps" and start_tls:
        raise ImproperlyConfigured("LDAP_START_TLS non si usa con ldaps://.")
    if scheme not in {"ldap", "ldaps"}:
        raise ImproperlyConfigured(f"Schema LDAP non supportato: {scheme!r}.")

    nested = _get(environ, "LDAP_NESTED_GROUPS", "matching_rule").lower()
    if nested not in NESTED_STRATEGIES:
        raise ImproperlyConfigured(
            f"LDAP_NESTED_GROUPS deve essere uno tra {sorted(NESTED_STRATEGIES)}, "
            f"trovato {nested!r}."
        )

    role_groups = {
        ADMIN: _require(environ, "LDAP_GROUP_ADMIN"),
        EDITOR: _require(environ, "LDAP_GROUP_EDITOR"),
        READER: _require(environ, "LDAP_GROUP_READER"),
    }

    timeout = _int(environ, "LDAP_TIMEOUT", 5)
    # L'ordine conta: le opzioni TLS vanno impostate prima di OPT_X_TLS_NEWCTX.
    options: dict[int, Any] = {
        ldap.OPT_REFERRALS: 0,
        ldap.OPT_NETWORK_TIMEOUT: timeout,
        ldap.OPT_TIMEOUT: timeout,
        ldap.OPT_X_TLS_REQUIRE_CERT: ldap.OPT_X_TLS_DEMAND,
    }
    ca_cert_file = _get(environ, "LDAP_CA_CERT_FILE")
    if ca_cert_file:
        options[ldap.OPT_X_TLS_CACERTFILE] = ca_cert_file
    options[ldap.OPT_X_TLS_NEWCTX] = 0

    user_filter = _get(environ, "LDAP_USER_FILTER", "(sAMAccountName=%(user)s)")
    group_filter = _get(environ, "LDAP_GROUP_FILTER", "(objectClass=group)")

    return {
        "AUTH_LDAP_SERVER_URI": uri,
        "AUTH_LDAP_START_TLS": start_tls,
        "AUTH_LDAP_CONNECTION_OPTIONS": options,
        "AUTH_LDAP_BIND_DN": _require(environ, "LDAP_BIND_DN"),
        "AUTH_LDAP_BIND_PASSWORD": _get(environ, "LDAP_BIND_PASSWORD"),
        "AUTH_LDAP_USER_SEARCH": LDAPSearch(
            _require(environ, "LDAP_USER_SEARCH_BASE"), ldap.SCOPE_SUBTREE, user_filter
        ),
        "AUTH_LDAP_USER_ATTR_MAP": {
            "first_name": "givenName",
            "last_name": "sn",
            "email": "mail",
        },
        "AUTH_LDAP_ALWAYS_UPDATE_USER": True,
        "AUTH_LDAP_GROUP_SEARCH": LDAPSearch(
            _require(environ, "LDAP_GROUP_SEARCH_BASE"), ldap.SCOPE_SUBTREE, group_filter
        ),
        "AUTH_LDAP_GROUP_TYPE": NESTED_STRATEGIES[nested](),
        "AUTH_LDAP_CACHE_TIMEOUT": 0,
        "ACCOUNTS_LDAP_ROLE_GROUPS": role_groups,
    }


def authentication_backends(ldap_enabled: bool) -> list[str]:
    """Con LDAP: solo LDAP e break-glass. Senza: autenticazione locale (sviluppo)."""
    if ldap_enabled:
        return [LDAP_BACKEND, BREAKGLASS_BACKEND]
    return [MODEL_BACKEND]


def configure_authentication(environ: Mapping[str, str]) -> dict[str, Any]:
    """Tutto ciò che serve ai settings: backend e, se attivo, configurazione LDAP."""
    ldap_settings = build_ldap_settings(environ)
    return {
        **ldap_settings,
        "AUTHENTICATION_BACKENDS": authentication_backends(bool(ldap_settings)),
        "ACCOUNTS_LDAP_ENABLED": bool(ldap_settings),
    }
