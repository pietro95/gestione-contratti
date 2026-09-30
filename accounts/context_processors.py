from accounts.roles import can_write, role_of


def ruolo(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"ruolo": role_of(user), "puo_modificare": can_write(user)}
