"""Ruoli applicativi (SPEC §8.1). Ogni ruolo corrisponde a un gruppo Django omonimo."""

ADMIN = "Admin"
EDITOR = "Editor"
READER = "Reader"

# Dal più alto al più basso: con più gruppi AD vale il ruolo più alto.
ROLES = (ADMIN, EDITOR, READER)

# Chi può modificare i dati di dominio.
WRITE_ROLES = frozenset({ADMIN, EDITOR})


def highest_role(roles):
    """Il ruolo più alto tra quelli dati, oppure ``None``."""
    present = set(roles)
    for role in ROLES:
        if role in present:
            return role
    return None


def role_of(user):
    """Ruolo di un utente Django: superuser → Admin, altrimenti dal gruppo Django."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return None
    if user.is_superuser:
        return ADMIN
    names = getattr(user, "_ruolo_gruppi_cache", None)
    if names is None:
        names = set(user.groups.filter(name__in=ROLES).values_list("name", flat=True))
        user._ruolo_gruppi_cache = names
    return highest_role(names)


def can_write(user):
    return role_of(user) in WRITE_ROLES
