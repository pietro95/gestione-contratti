"""Tipi di gruppo LDAP non forniti da django-auth-ldap."""

import ldap
from django_auth_ldap.config import LDAPGroupType

# LDAP_MATCHING_RULE_IN_CHAIN: Active Directory risolve l'appartenenza transitiva lato server.
MATCHING_RULE_IN_CHAIN = "1.2.840.113556.1.4.1941"


class ADMatchingRuleGroupType(LDAPGroupType):
    """Gruppi AD con annidamento risolto dal server in una sola query.

    ``(member:1.2.840.113556.1.4.1941:=<dn utente>)`` restituisce tutti i gruppi che
    contengono l'utente direttamente o tramite gruppi annidati, a qualsiasi profondità.
    OpenLDAP non supporta questa regola: sui server di test si usa ``recursive``.
    """

    def __init__(self, name_attr="cn", member_attr="member"):
        self.member_attr = member_attr
        super().__init__(name_attr)

    def __repr__(self):
        return f"<{type(self).__name__}: {self.member_attr}>"

    def _filter(self, user_dn):
        escaped = self.ldap.filter.escape_filter_chars(user_dn)
        return f"({self.member_attr}:{MATCHING_RULE_IN_CHAIN}:={escaped})"

    def user_groups(self, ldap_user, group_search):
        search = group_search.search_with_additional_term_string(self._filter(ldap_user.dn))
        return search.execute(ldap_user.connection)

    def is_member(self, ldap_user, group_dn):
        try:
            results = ldap_user.connection.search_s(
                group_dn, ldap.SCOPE_BASE, self._filter(ldap_user.dn), ["1.1"]
            )
        except ldap.NO_SUCH_OBJECT:
            return False
        return any(dn is not None for dn, _attrs in results)
