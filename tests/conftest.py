"""Fixture comuni. Il server LDAP di test è slapd avviato da ``slapdtest`` (python-ldap).

Mai l'AD reale. Se slapd manca i test LDAP si saltano in locale, ma con ``CI=true``
falliscono: in CI TC-09 deve girare davvero.
"""

import os
import shutil
import socket
from pathlib import Path

import pytest
from django.contrib.auth.models import Group

from accounts.ldap_config import configure_authentication

LDAP_DIR = Path(__file__).parent / "ldap"
SUFFIX = "dc=esempio,dc=test"
GROUPS_BASE = f"ou=Gruppi,{SUFFIX}"


def _in_ci():
    return os.environ.get("CI", "").lower() in {"1", "true", "yes"}


def _slapd_available():
    return any(
        shutil.which("slapd", path=p) for p in (os.environ.get("PATH", ""), "/usr/sbin:/sbin")
    )


@pytest.fixture(scope="session")
def slapd_server(tmp_path_factory):
    if not _slapd_available():
        message = "slapd non installato: test LDAP non eseguibili"
        if _in_ci():
            pytest.fail(message)
        pytest.skip(message)

    from slapdtest import SlapdObject

    class SlapdStileAD(SlapdObject):
        suffix = SUFFIX
        root_cn = "Manager"
        openldap_schema_files = (
            "core.ldif",
            "cosine.ldif",
            "inetorgperson.ldif",
            str(LDAP_DIR / "schema_ad_minimale.ldif"),
        )
        # Directory temporanea di pytest, non la cartella corrente.
        TMPDIR = str(tmp_path_factory.mktemp("slapd"))

    server = SlapdStileAD()
    server.start()
    try:
        server.ldapadd((LDAP_DIR / "dati_tc09.ldif").read_text(encoding="utf-8"))
        yield server
    finally:
        server.stop()


def ldap_env_for(uri, cafile, **overrides):
    env = {
        "LDAP_SERVER_URI": uri,
        "LDAP_START_TLS": "true",
        "LDAP_CA_CERT_FILE": cafile,
        "LDAP_BIND_DN": f"cn=svc_contratti,ou=Servizio,{SUFFIX}",
        "LDAP_BIND_PASSWORD": "servizio-di-prova",
        "LDAP_USER_SEARCH_BASE": f"ou=Utenti,{SUFFIX}",
        "LDAP_USER_FILTER": "(&(objectClass=user)(sAMAccountName=%(user)s))",
        "LDAP_GROUP_SEARCH_BASE": GROUPS_BASE,
        "LDAP_GROUP_FILTER": "(objectClass=group)",
        "LDAP_GROUP_ADMIN": f"cn=GG_Contratti_Admin,{GROUPS_BASE}",
        "LDAP_GROUP_EDITOR": f"cn=GG_Contratti_Editor,{GROUPS_BASE}",
        "LDAP_GROUP_READER": f"cn=GG_Contratti_Reader,{GROUPS_BASE}",
        # OpenLDAP non supporta la matching rule AD 1.2.840.113556.1.4.1941.
        "LDAP_NESTED_GROUPS": "recursive",
        "LDAP_TIMEOUT": "3",
    }
    env.update(overrides)
    return env


def apply_auth_settings(settings, env):
    for name, value in configure_authentication(env).items():
        setattr(settings, name, value)


@pytest.fixture
def ldap_env(slapd_server):
    return ldap_env_for(slapd_server.ldap_uri, slapd_server.cafile)


@pytest.fixture
def ldap_auth(settings, ldap_env, db):
    """Attiva LDAP (StartTLS verso slapd) con i backend di produzione."""
    apply_auth_settings(settings, ldap_env)
    return ldap_env


@pytest.fixture
def closed_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def ldap_down(settings, closed_port, db):
    """LDAP configurato correttamente ma non raggiungibile: porta locale chiusa."""
    import slapdtest

    cafile = str(Path(slapdtest.__file__).parent / "certs" / "ca.pem")
    env = ldap_env_for(f"ldap://127.0.0.1:{closed_port}", cafile)
    apply_auth_settings(settings, env)
    return env


@pytest.fixture
def make_user(db, django_user_model):
    def _make(username, password="password-locale-di-prova", role=None, **fields):
        user = django_user_model.objects.create_user(username, password=password, **fields)
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    return _make
