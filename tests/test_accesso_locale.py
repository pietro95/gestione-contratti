"""Login locale (LDAP spento), home protetta, logout e log dei login."""

import logging

import pytest
from django.urls import reverse

from accounts.models import LoginAttempt
from accounts.roles import EDITOR

pytestmark = pytest.mark.django_db


def test_home_richiede_login(client):
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_pagina_di_login_in_italiano_con_asset_locali(client):
    body = client.get(reverse("accounts:login")).content.decode()
    assert '<html lang="it">' in body
    assert "/static/vendor/bootstrap-5.3.8/bootstrap.min.css" in body
    assert "/static/vendor/htmx-2.0.11/htmx.min.js" in body
    assert "http://" not in body and "https://" not in body  # nessuna CDN


def test_login_locale_e_home(client, make_user):
    make_user("utente", role=EDITOR, first_name="Anna")

    response = client.post(
        reverse("accounts:login"), {"username": "utente", "password": "password-locale-di-prova"}
    )
    assert response.status_code == 302
    home = client.get(reverse("home"))
    assert home.status_code == 200
    assert "Editor" in home.content.decode()

    attempt = LoginAttempt.objects.get()
    assert attempt.success and attempt.esito == LoginAttempt.Esito.OK
    assert attempt.backend == "django.contrib.auth.backends.ModelBackend"


def test_login_fallito_loggato_senza_password(client, make_user, caplog):
    make_user("utente")
    auth_logger = logging.getLogger("accounts.auth")  # propagate=False: handler esplicito
    auth_logger.addHandler(caplog.handler)
    try:
        response = client.post(
            reverse("accounts:login"), {"username": "utente", "password": "segreto-sbagliato"}
        )
    finally:
        auth_logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    assert "Accesso non riuscito" in response.content.decode()
    attempt = LoginAttempt.objects.get()
    assert (attempt.username, attempt.success) == ("utente", False)
    assert attempt.esito == LoginAttempt.Esito.CREDENZIALI_ERRATE
    assert "login fallito utente=utente" in caplog.text
    assert "segreto-sbagliato" not in caplog.text


def test_utente_sconosciuto_stesso_messaggio(client):
    response = client.post(
        reverse("accounts:login"), {"username": "fantasma", "password": "qualsiasi"}
    )
    assert "Accesso non riuscito" in response.content.decode()
    assert LoginAttempt.objects.get().username == "fantasma"


def test_logout_solo_post(client, make_user):
    make_user("utente")
    client.login(username="utente", password="password-locale-di-prova")

    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert client.get(reverse("home")).status_code == 302


def test_login_log_admin_in_sola_lettura(admin_client):
    LoginAttempt.objects.create(username="x", success=False, esito="credenziali_errate")
    assert admin_client.get(reverse("admin:accounts_loginattempt_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:accounts_loginattempt_add")).status_code == 403
