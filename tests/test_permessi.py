"""Controlli di ruolo con utenti locali: il Reader riceve 403 sulle viste di modifica."""

import pytest
from django.urls import reverse

from accounts.roles import ADMIN, EDITOR, READER, can_write, highest_role, role_of

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.urls_ruoli")]

PASSWORD = "password-locale-di-prova"


@pytest.fixture
def as_role(client, make_user):
    def _login(role, **fields):
        make_user(f"u_{role or 'nessuno'}".lower(), role=role, **fields)
        client.login(username=f"u_{role or 'nessuno'}".lower(), password=PASSWORD)
        return client

    return _login


@pytest.mark.parametrize(
    ("role", "lettura", "modifica", "amministrazione"),
    [
        (READER, 200, 403, 403),
        (EDITOR, 200, 200, 403),
        (ADMIN, 200, 200, 200),
        (None, 200, 403, 403),
    ],
)
def test_matrice_permessi(as_role, role, lettura, modifica, amministrazione):
    client = as_role(role)
    assert client.get(reverse("prova-lettura")).status_code == lettura
    assert client.get(reverse("prova-modifica")).status_code == modifica
    assert client.get(reverse("prova-amministrazione")).status_code == amministrazione


def test_reader_403_su_post_di_modifica(as_role):
    assert as_role(READER).post(reverse("prova-modifica-cbv")).status_code == 403


def test_editor_post_di_modifica(as_role):
    assert as_role(EDITOR).post(reverse("prova-modifica-cbv")).status_code == 200


@pytest.mark.parametrize("name", ["prova-modifica", "prova-amministrazione"])
def test_anonimo_rimandato_al_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_anonimo_rimandato_al_login_cbv(client):
    response = client.post(reverse("prova-modifica-cbv"))
    assert response.status_code == 302


def test_superuser_e_admin(make_user):
    assert role_of(make_user("root", is_superuser=True)) == ADMIN


def test_utente_disattivato_senza_ruolo(make_user):
    assert role_of(make_user("spento", role=EDITOR, is_active=False)) is None


def test_ruolo_piu_alto_vince(make_user):
    user = make_user("doppio", role=READER)
    user.groups.add(*user.groups.model.objects.filter(name=EDITOR))
    assert role_of(user) == EDITOR
    assert can_write(user)


def test_highest_role():
    assert highest_role([READER, ADMIN, EDITOR]) == ADMIN
    assert highest_role(["Altro"]) is None
    assert highest_role([]) is None


def test_gruppi_ruolo_creati_dalla_migration(django_user_model):
    from django.contrib.auth.models import Group

    assert set(Group.objects.values_list("name", flat=True)) >= {ADMIN, EDITOR, READER}
