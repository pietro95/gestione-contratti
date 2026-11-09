"""Funzioni dell'addetto dai gruppi AD (SPEC §8.1, Rev39), contro slapd con StartTLS."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.ldap_config import build_ldap_settings
from accounts.roles import (
    ADDETTO_AMMINISTRATIVO,
    ADDETTO_RILASCIO,
    EDITOR,
    ha_funzione,
    role_of,
)
from contratti import fatture, permessi

from .conftest import GROUPS_BASE, apply_auth_settings, ldap_env_for

pytestmark = [pytest.mark.ldap, pytest.mark.django_db, pytest.mark.urls("tests.urls_ruoli")]

GRUPPO_AMM = f"cn=GG_Contratti_Addetto_Amm,{GROUPS_BASE}"
GRUPPO_RIL = f"cn=GG_Contratti_Addetto_Rilascio,{GROUPS_BASE}"


@pytest.fixture
def ldap_funzioni(settings, slapd_server, db):
    env = ldap_env_for(
        slapd_server.ldap_uri,
        slapd_server.cafile,
        LDAP_GROUP_ADDETTO_AMMINISTRATIVO=GRUPPO_AMM,
        LDAP_GROUP_ADDETTO_RILASCIO=GRUPPO_RIL,
    )
    apply_auth_settings(settings, env)
    return env


def accedi(client, username):
    return client.post(
        reverse("accounts:login"), {"username": username, "password": f"password-{username}"}
    )


def test_il_solo_gruppo_dell_addetto_amministrativo_basta_per_entrare(client, ldap_funzioni):
    risposta = accedi(client, "aamm")
    assert risposta.status_code == 302
    utente = get_user_model().objects.get(username="aamm")
    assert role_of(utente) == EDITOR
    assert ha_funzione(utente, ADDETTO_AMMINISTRATIVO)
    assert not ha_funzione(utente, ADDETTO_RILASCIO)
    assert permessi.e_addetto(utente) and fatture.gestisce(utente)
    # La funzione vale come assegnazione a tutti i cluster.
    assert permessi.cluster_assegnati(utente) is None
    assert not permessi.puo_rilasciare(utente)
    assert utente.email == "aamm@esempio.test"


def test_la_funzione_di_rilascio_alza_il_reader_a_editor(client, ldap_funzioni):
    assert accedi(client, "rril").status_code == 302
    utente = get_user_model().objects.get(username="rril")
    # Era nel gruppo Reader: con la funzione scrive, altrimenti non potrebbe rilasciare.
    assert role_of(utente) == EDITOR
    assert permessi.puo_rilasciare(utente)
    assert not permessi.e_addetto(utente)


def test_senza_gruppo_la_funzione_si_perde_al_login_successivo(
    client, ldap_funzioni, settings, slapd_server
):
    accedi(client, "aamm")
    utente = get_user_model().objects.get(username="aamm")
    assert ha_funzione(utente, ADDETTO_AMMINISTRATIVO)
    # Il gruppo non è più configurato: l'utente non ha più né funzione né ruolo.
    env = ldap_env_for(slapd_server.ldap_uri, slapd_server.cafile)
    apply_auth_settings(settings, env)
    client.logout()
    assert accedi(client, "aamm").status_code == 200
    utente = get_user_model().objects.get(username="aamm")
    assert not utente.groups.exists()


def test_gruppi_delle_funzioni_facoltativi_in_configurazione():
    base = {
        "LDAP_SERVER_URI": "ldaps://dc.esempio.test:636",
        "LDAP_BIND_DN": "CN=svc,DC=esempio,DC=test",
        "LDAP_USER_SEARCH_BASE": "DC=esempio,DC=test",
        "LDAP_GROUP_SEARCH_BASE": "DC=esempio,DC=test",
        "LDAP_GROUP_ADMIN": "CN=A,DC=esempio,DC=test",
        "LDAP_GROUP_EDITOR": "CN=E,DC=esempio,DC=test",
        "LDAP_GROUP_READER": "CN=R,DC=esempio,DC=test",
    }
    assert build_ldap_settings(base)["ACCOUNTS_LDAP_FUNCTION_GROUPS"] == {}
    con = {
        **base,
        "LDAP_GROUP_ADDETTO_AMMINISTRATIVO": "CN=Amm,DC=esempio,DC=test",
        "LDAP_GROUP_ADDETTO_RILASCIO": "CN=Ril,DC=esempio,DC=test",
    }
    assert build_ldap_settings(con)["ACCOUNTS_LDAP_FUNCTION_GROUPS"] == {
        ADDETTO_AMMINISTRATIVO: "CN=Amm,DC=esempio,DC=test",
        ADDETTO_RILASCIO: "CN=Ril,DC=esempio,DC=test",
    }
