"""Configurazione LDAP da variabili d'ambiente: funzione pura, niente server."""

import ldap
import pytest
from django.core.exceptions import ImproperlyConfigured
from django_auth_ldap.config import ActiveDirectoryGroupType, NestedActiveDirectoryGroupType

from accounts.ldap_config import (
    BREAKGLASS_BACKEND,
    LDAP_BACKEND,
    MODEL_BACKEND,
    authentication_backends,
    build_ldap_settings,
    configure_authentication,
)
from accounts.ldap_groups import ADMatchingRuleGroupType

BASE_ENV = {
    "LDAP_SERVER_URI": "ldaps://dc01.esempio.test:636",
    "LDAP_CA_CERT_FILE": "/etc/ssl/certs/ca-interna.pem",
    "LDAP_BIND_DN": "CN=svc,OU=Servizio,DC=esempio,DC=test",
    "LDAP_BIND_PASSWORD": "non-un-segreto",
    "LDAP_USER_SEARCH_BASE": "DC=esempio,DC=test",
    "LDAP_GROUP_SEARCH_BASE": "DC=esempio,DC=test",
    "LDAP_GROUP_ADMIN": "CN=GG_Contratti_Admin,OU=Gruppi,DC=esempio,DC=test",
    "LDAP_GROUP_EDITOR": "CN=GG_Contratti_Editor,OU=Gruppi,DC=esempio,DC=test",
    "LDAP_GROUP_READER": "CN=GG_Contratti_Reader,OU=Gruppi,DC=esempio,DC=test",
}


@pytest.mark.parametrize("uri", [None, "", "   "])
def test_senza_uri_ldap_spento(uri):
    env = {**BASE_ENV, "LDAP_SERVER_URI": uri} if uri is not None else {}
    assert build_ldap_settings(env) == {}
    assert configure_authentication(env) == {
        "AUTHENTICATION_BACKENDS": [MODEL_BACKEND],
        "ACCOUNTS_LDAP_ENABLED": False,
    }


def test_ldaps_configurazione_completa():
    conf = build_ldap_settings(BASE_ENV)

    assert conf["AUTH_LDAP_SERVER_URI"] == "ldaps://dc01.esempio.test:636"
    assert conf["AUTH_LDAP_START_TLS"] is False
    assert conf["AUTH_LDAP_BIND_DN"] == BASE_ENV["LDAP_BIND_DN"]
    assert conf["AUTH_LDAP_USER_SEARCH"].filterstr == "(sAMAccountName=%(user)s)"
    assert conf["AUTH_LDAP_USER_SEARCH"].scope == ldap.SCOPE_SUBTREE
    assert conf["AUTH_LDAP_GROUP_SEARCH"].filterstr == "(objectClass=group)"
    assert isinstance(conf["AUTH_LDAP_GROUP_TYPE"], ADMatchingRuleGroupType)
    assert conf["ACCOUNTS_LDAP_ROLE_GROUPS"] == {
        "Admin": BASE_ENV["LDAP_GROUP_ADMIN"],
        "Editor": BASE_ENV["LDAP_GROUP_EDITOR"],
        "Reader": BASE_ENV["LDAP_GROUP_READER"],
    }


def test_opzioni_tls_con_newctx_per_ultima():
    options = build_ldap_settings(BASE_ENV)["AUTH_LDAP_CONNECTION_OPTIONS"]

    assert options[ldap.OPT_X_TLS_REQUIRE_CERT] == ldap.OPT_X_TLS_DEMAND
    assert options[ldap.OPT_X_TLS_CACERTFILE] == BASE_ENV["LDAP_CA_CERT_FILE"]
    assert options[ldap.OPT_REFERRALS] == 0
    assert options[ldap.OPT_NETWORK_TIMEOUT] == 5
    assert list(options)[-1] == ldap.OPT_X_TLS_NEWCTX


def test_con_ldap_solo_backend_ldap_e_breakglass():
    assert configure_authentication(BASE_ENV)["AUTHENTICATION_BACKENDS"] == [
        LDAP_BACKEND,
        BREAKGLASS_BACKEND,
    ]
    assert authentication_backends(False) == [MODEL_BACKEND]


def test_bind_in_chiaro_rifiutato():
    with pytest.raises(ImproperlyConfigured, match="chiaro"):
        build_ldap_settings({**BASE_ENV, "LDAP_SERVER_URI": "ldap://dc01.esempio.test"})


def test_starttls_ammesso_su_ldap():
    conf = build_ldap_settings(
        {**BASE_ENV, "LDAP_SERVER_URI": "ldap://dc01.esempio.test", "LDAP_START_TLS": "true"}
    )
    assert conf["AUTH_LDAP_START_TLS"] is True


def test_starttls_su_ldaps_rifiutato():
    with pytest.raises(ImproperlyConfigured):
        build_ldap_settings({**BASE_ENV, "LDAP_START_TLS": "true"})


def test_schema_sconosciuto_rifiutato():
    with pytest.raises(ImproperlyConfigured, match="Schema"):
        build_ldap_settings({**BASE_ENV, "LDAP_SERVER_URI": "http://dc01"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("matching_rule", ADMatchingRuleGroupType),
        ("recursive", NestedActiveDirectoryGroupType),
        ("none", ActiveDirectoryGroupType),
        ("RECURSIVE", NestedActiveDirectoryGroupType),
    ],
)
def test_strategia_gruppi_annidati(value, expected):
    conf = build_ldap_settings({**BASE_ENV, "LDAP_NESTED_GROUPS": value})
    assert type(conf["AUTH_LDAP_GROUP_TYPE"]) is expected


def test_strategia_sconosciuta_rifiutata():
    with pytest.raises(ImproperlyConfigured, match="LDAP_NESTED_GROUPS"):
        build_ldap_settings({**BASE_ENV, "LDAP_NESTED_GROUPS": "profonda"})


@pytest.mark.parametrize(
    "name",
    [
        "LDAP_BIND_DN",
        "LDAP_USER_SEARCH_BASE",
        "LDAP_GROUP_SEARCH_BASE",
        "LDAP_GROUP_ADMIN",
        "LDAP_GROUP_EDITOR",
        "LDAP_GROUP_READER",
    ],
)
def test_variabili_obbligatorie(name):
    env = {k: v for k, v in BASE_ENV.items() if k != name}
    with pytest.raises(ImproperlyConfigured, match=name):
        build_ldap_settings(env)


def test_filtri_e_timeout_configurabili():
    conf = build_ldap_settings(
        {
            **BASE_ENV,
            "LDAP_USER_FILTER": "(&(objectClass=user)(sAMAccountName=%(user)s))",
            "LDAP_GROUP_FILTER": "(objectCategory=group)",
            "LDAP_TIMEOUT": "10",
        }
    )
    assert conf["AUTH_LDAP_USER_SEARCH"].filterstr.startswith("(&(objectClass=user)")
    assert conf["AUTH_LDAP_GROUP_SEARCH"].filterstr == "(objectCategory=group)"
    assert conf["AUTH_LDAP_CONNECTION_OPTIONS"][ldap.OPT_TIMEOUT] == 10


@pytest.mark.parametrize(("name", "value"), [("LDAP_TIMEOUT", "0"), ("LDAP_TIMEOUT", "x")])
def test_timeout_non_valido(name, value):
    with pytest.raises(ImproperlyConfigured, match=name):
        build_ldap_settings({**BASE_ENV, name: value})


def test_booleano_non_valido():
    with pytest.raises(ImproperlyConfigured, match="LDAP_START_TLS"):
        build_ldap_settings({**BASE_ENV, "LDAP_START_TLS": "forse"})


def test_senza_ca_nessuna_opzione_cacertfile():
    env = {k: v for k, v in BASE_ENV.items() if k != "LDAP_CA_CERT_FILE"}
    options = build_ldap_settings(env)["AUTH_LDAP_CONNECTION_OPTIONS"]
    assert ldap.OPT_X_TLS_CACERTFILE not in options
    assert options[ldap.OPT_X_TLS_REQUIRE_CERT] == ldap.OPT_X_TLS_DEMAND
