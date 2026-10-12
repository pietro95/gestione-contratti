import pytest
from django.contrib.auth import get_user_model


@pytest.mark.django_db
def test_utente_mostra_nome_completo_da_ldap():
    u = get_user_model().objects.create_user("m.rossi", first_name="Mario", last_name="Rossi")
    assert str(u) == "Mario Rossi"


@pytest.mark.django_db
def test_utente_senza_nome_ricade_sullo_username():
    u = get_user_model().objects.create_user("breakglass")
    assert str(u) == "breakglass"


@pytest.mark.django_db
def test_testata_mostra_nome_completo(client):
    u = get_user_model().objects.create_user("m.rossi", first_name="Mario", last_name="Rossi")
    client.force_login(u)
    assert "Mario Rossi" in client.get("/", follow=True).content.decode()
