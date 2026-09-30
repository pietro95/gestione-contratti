"""Controlli di ruolo per le viste. Chi non ha il ruolo riceve 403."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from accounts.roles import ADMIN, WRITE_ROLES, role_of


def role_required(*roles):
    allowed = frozenset(roles)

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if role_of(request.user) not in allowed:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


editor_required = role_required(*WRITE_ROLES)
admin_required = role_required(ADMIN)


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = WRITE_ROLES

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and role_of(request.user) not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
