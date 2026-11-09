"""Ruoli applicativi (SPEC §8.1). Ogni ruolo corrisponde a un gruppo Django omonimo."""

ADMIN = "Admin"
EDITOR = "Editor"
READER = "Reader"

# Dal più alto al più basso: con più gruppi AD vale il ruolo più alto.
ROLES = (ADMIN, EDITOR, READER)

# Funzioni del processo d'acquisto (SPEC §8.1, Rev39): non sono ruoli e non danno permessi da
# sole, ma dal gruppo AD corrispondente derivano le funzioni dell'utente. Ogni funzione
# corrisponde a un gruppo Django omonimo, sincronizzato a ogni login LDAP.
ADDETTO_AMMINISTRATIVO = "Addetto amministrativo"
ADDETTO_RILASCIO = "Addetto al rilascio"
FUNZIONI = (ADDETTO_AMMINISTRATIVO, ADDETTO_RILASCIO)

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


def ha_funzione(user, funzione):
    """L'utente appartiene al gruppo Django della funzione (arrivato dal gruppo AD)?"""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    nomi = getattr(user, "_funzioni_gruppi_cache", None)
    if nomi is None:
        nomi = set(user.groups.filter(name__in=FUNZIONI).values_list("name", flat=True))
        user._funzioni_gruppi_cache = nomi
    return funzione in nomi
