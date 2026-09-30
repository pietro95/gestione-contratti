"""Account locale di emergenza: comando di creazione e vincolo di unicità."""

from unittest.mock import patch

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError

from accounts.ldap_config import BREAKGLASS_BACKEND

pytestmark = pytest.mark.django_db

LUNGA = "cavallo-batteria-graffetta-corretta-2026"


def crea(*passwords, **options):
    with patch("accounts.management.commands.crea_breakglass.getpass", side_effect=list(passwords)):
        call_command("crea_breakglass", **options)


def test_crea_breakglass():
    crea(LUNGA, LUNGA)

    user = get_user_model().objects.get(username="breakglass")
    assert user.is_breakglass and user.is_superuser and user.is_staff and user.is_active
    assert user.check_password(LUNGA)


def test_un_solo_breakglass():
    crea(LUNGA, LUNGA)
    with pytest.raises(CommandError, match="Esiste già"):
        crea(LUNGA, LUNGA, username="altro")


def test_vincolo_db_un_solo_breakglass(make_user):
    make_user("bg1", is_breakglass=True)
    with pytest.raises(IntegrityError):
        make_user("bg2", is_breakglass=True)


def test_reset_password():
    crea(LUNGA, LUNGA)
    nuova = LUNGA + "-nuova"
    crea(nuova, nuova, reset_password=True)
    assert get_user_model().objects.get(is_breakglass=True).check_password(nuova)


def test_reset_senza_breakglass():
    with pytest.raises(CommandError, match="Nessun account"):
        crea(LUNGA, LUNGA, reset_password=True)


def test_password_corta_rifiutata():
    with pytest.raises(CommandError, match="troppo corta"):
        crea("corta-ma-non-abbastanza", "corta-ma-non-abbastanza")
    assert not get_user_model().objects.exists()


def test_password_diverse_rifiutate():
    with pytest.raises(CommandError, match="non coincidono"):
        crea(LUNGA, LUNGA + "x")


def test_username_occupato(make_user):
    make_user("breakglass")
    with pytest.raises(CommandError, match="già in uso"):
        crea(LUNGA, LUNGA)


def test_backend_breakglass_accetta_solo_il_breakglass(settings, make_user):
    settings.AUTHENTICATION_BACKENDS = [BREAKGLASS_BACKEND]
    make_user("normale", password=LUNGA)
    make_user("emergenza", password=LUNGA, is_breakglass=True)

    assert authenticate(username="normale", password=LUNGA) is None
    assert authenticate(username="emergenza", password=LUNGA).username == "emergenza"
