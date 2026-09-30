"""ADMatchingRuleGroupType con connessione simulata: OpenLDAP non supporta la regola AD."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import ldap
from django_auth_ldap.config import LDAPSearch

from accounts.ldap_groups import MATCHING_RULE_IN_CHAIN, ADMatchingRuleGroupType

USER_DN = "cn=giulia verdi,ou=utenti,dc=esempio,dc=test"
GROUP_DN = "CN=GG_Contratti_Admin,OU=Gruppi,DC=esempio,DC=test"


def ldap_user(connection, dn=USER_DN):
    return SimpleNamespace(dn=dn, connection=connection)


def test_oid_matching_rule_in_chain():
    assert MATCHING_RULE_IN_CHAIN == "1.2.840.113556.1.4.1941"


def test_user_groups_una_sola_query_con_matching_rule():
    connection = MagicMock()
    connection.search_s.return_value = [
        (GROUP_DN, {"cn": [b"GG_Contratti_Admin"]}),
        (None, ["ldap://referral"]),  # i referral AD vanno scartati
    ]
    search = LDAPSearch("DC=esempio,DC=test", ldap.SCOPE_SUBTREE, "(objectClass=group)")

    groups = ADMatchingRuleGroupType().user_groups(ldap_user(connection), search)

    connection.search_s.assert_called_once_with(
        "DC=esempio,DC=test",
        ldap.SCOPE_SUBTREE,
        f"(&(objectClass=group)(member:1.2.840.113556.1.4.1941:={USER_DN}))",
        None,
    )
    assert groups == [(GROUP_DN.lower(), {"cn": ["GG_Contratti_Admin"]})]


def test_is_member_ricerca_base_sul_gruppo():
    connection = MagicMock()
    connection.search_s.return_value = [(GROUP_DN, {})]

    assert ADMatchingRuleGroupType().is_member(ldap_user(connection), GROUP_DN) is True
    connection.search_s.assert_called_once_with(
        GROUP_DN,
        ldap.SCOPE_BASE,
        f"(member:1.2.840.113556.1.4.1941:={USER_DN})",
        ["1.1"],
    )


def test_is_member_falso_se_nessun_risultato():
    connection = MagicMock()
    connection.search_s.return_value = []
    assert ADMatchingRuleGroupType().is_member(ldap_user(connection), GROUP_DN) is False


def test_is_member_falso_se_gruppo_inesistente():
    connection = MagicMock()
    connection.search_s.side_effect = ldap.NO_SUCH_OBJECT
    assert ADMatchingRuleGroupType().is_member(ldap_user(connection), GROUP_DN) is False


def test_dn_utente_escapato_nel_filtro():
    connection = MagicMock()
    connection.search_s.return_value = []
    dn = "cn=rossi (esterno)*,ou=utenti,dc=esempio,dc=test"

    ADMatchingRuleGroupType().is_member(ldap_user(connection, dn), GROUP_DN)

    filterstr = connection.search_s.call_args.args[2]
    assert filterstr == (
        r"(member:1.2.840.113556.1.4.1941:=cn=rossi \28esterno\29\2a,ou=utenti,dc=esempio,dc=test)"
    )
