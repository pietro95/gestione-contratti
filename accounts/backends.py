"""Backend di autenticazione: LDAP con ruoli dai gruppi AD e break-glass locale."""

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group
from django_auth_ldap.backend import LDAPBackend

from accounts.models import LoginAttempt
from accounts.roles import ADMIN, ROLES, highest_role

# Attributo della request in cui i backend lasciano il motivo di un rifiuto,
# letto dal gestore di ``user_login_failed`` per il log.
FAILURE_REASON_ATTR = "_accounts_login_failure"


def set_failure_reason(request, esito):
    if request is not None:
        setattr(request, FAILURE_REASON_ATTR, esito)


def get_failure_reason(request):
    return getattr(request, FAILURE_REASON_ATTR, LoginAttempt.Esito.CREDENZIALI_ERRATE)


class RoleLDAPBackend(LDAPBackend):
    """LDAP con mappatura dei gruppi AD sui ruoli Admin/Editor/Reader.

    Chi non appartiene ad alcuno dei tre gruppi (anche tramite gruppi annidati) non entra
    e il suo utente Django, se esiste, perde ruolo e privilegi. Con più gruppi vale il più alto.
    """

    def ldap_to_django_username(self, username):
        return username.lower()

    def resolve_role(self, ldap_user):
        groups = ldap_user._get_groups()
        role_groups = settings.ACCOUNTS_LDAP_ROLE_GROUPS
        return highest_role(role for role in ROLES if groups.is_member_of(role_groups[role]))

    def get_or_build_user(self, username, ldap_user):
        # Qui le credenziali sono già verificate e l'utente non è ancora creato.
        role = self.resolve_role(ldap_user)
        if role is None:
            set_failure_reason(ldap_user._request, LoginAttempt.Esito.NESSUN_GRUPPO)
            _revoke_role(username)
            raise ldap_user.AuthenticationFailed("nessun gruppo applicativo")
        user, built = super().get_or_build_user(username, ldap_user)
        if user.is_breakglass:
            # L'account di emergenza è solo locale: un omonimo in AD non lo tocca.
            raise ldap_user.AuthenticationFailed("omonimo dell'account break-glass")
        ldap_user.accounts_role = role
        return user, built

    def authenticate_ldap_user(self, ldap_user, password):
        user = super().authenticate_ldap_user(ldap_user, password)
        if user is not None:
            _apply_role(user, ldap_user.accounts_role)
        return user


def _apply_role(user, role):
    is_admin = role == ADMIN
    if user.is_staff != is_admin or user.is_superuser != is_admin:
        user.is_staff = is_admin
        user.is_superuser = is_admin
        user.save(update_fields=["is_staff", "is_superuser"])
    role_groups = Group.objects.filter(name__in=ROLES)
    user.groups.remove(*role_groups.exclude(name=role))
    user.groups.add(Group.objects.get(name=role))


def _revoke_role(username):
    model = LDAPBackend().get_user_model()
    user = model.objects.filter(username__iexact=username, is_breakglass=False).first()
    if user is None:
        return
    user.groups.remove(*Group.objects.filter(name__in=ROLES))
    if user.is_staff or user.is_superuser:
        user.is_staff = user.is_superuser = False
        user.save(update_fields=["is_staff", "is_superuser"])


class BreakGlassBackend(ModelBackend):
    """Login locale riservato all'unico account di emergenza (SPEC §8.1)."""

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and getattr(user, "is_breakglass", False)
