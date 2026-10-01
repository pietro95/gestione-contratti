"""TC-09 — Autenticazione LDAP e ruoli (docs/TEST_CASES.md), contro slapd con StartTLS."""

import os

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import LoginAttempt
from accounts.roles import ADMIN, EDITOR, READER, role_of

from .conftest import apply_auth_settings

pytestmark = [pytest.mark.ldap, pytest.mark.django_db, pytest.mark.urls("tests.urls_ruoli")]

LOGIN = "accounts:login"
MESSAGGIO_GENERICO = "Accesso non riuscito"


def login(client, username, password):
    return client.post(reverse(LOGIN), {"username": username, "password": password})


def assert_logged_in(response):
    assert response.status_code == 302
    assert response.url == reverse("home")


def assert_rejected(response):
    assert response.status_code == 200
    assert MESSAGGIO_GENERICO in response.content.decode()
    assert "_auth_user_id" not in response.client.session


def test_editor_mrossi_login_e_modifica(client, ldap_auth):
    assert_logged_in(login(client, "mrossi", "password-mrossi"))

    user = get_user_model().objects.get(username="mrossi")
    assert role_of(user) == EDITOR
    assert (user.first_name, user.last_name) == ("Mario", "Rossi")
    assert user.email == "mrossi@esempio.test"
    assert not user.is_staff and not user.is_superuser
    assert not user.has_usable_password()
    assert client.get(reverse("prova-lettura")).status_code == 200
    assert client.get(reverse("prova-modifica")).status_code == 200
    assert client.post(reverse("prova-modifica-cbv")).status_code == 200
    assert client.get(reverse("prova-amministrazione")).status_code == 403


def test_reader_lbianchi_sola_lettura(client, ldap_auth):
    assert_logged_in(login(client, "lbianchi", "password-lbianchi"))

    user = get_user_model().objects.get(username="lbianchi")
    assert role_of(user) == READER
    assert client.get(reverse("prova-lettura")).status_code == 200
    assert client.get(reverse("prova-modifica")).status_code == 403
    assert client.post(reverse("prova-modifica-cbv")).status_code == 403
    assert client.get(reverse("prova-amministrazione")).status_code == 403
    assert client.get(reverse("admin:index")).status_code == 302  # admin: rimanda al login


def test_admin_gverdi_tramite_gruppo_annidato(client, ldap_auth):
    assert_logged_in(login(client, "gverdi", "password-gverdi"))

    user = get_user_model().objects.get(username="gverdi")
    assert role_of(user) == ADMIN
    assert user.is_staff and user.is_superuser
    assert client.get(reverse("prova-amministrazione")).status_code == 200
    assert client.get(reverse("admin:index")).status_code == 200


def test_gruppo_annidato_ignorato_senza_strategia_nested(client, settings, ldap_env):
    apply_auth_settings(settings, {**ldap_env, "LDAP_NESTED_GROUPS": "none"})

    assert_rejected(login(client, "gverdi", "password-gverdi"))
    assert LoginAttempt.objects.get().esito == LoginAttempt.Esito.NESSUN_GRUPPO


def test_nnessuno_rifiutato_e_utente_non_creato(client, ldap_auth):
    assert_rejected(login(client, "nnessuno", "password-nnessuno"))

    assert not get_user_model().objects.filter(username="nnessuno").exists()
    attempt = LoginAttempt.objects.get()
    assert (attempt.username, attempt.success, attempt.esito) == (
        "nnessuno",
        False,
        LoginAttempt.Esito.NESSUN_GRUPPO,
    )


def test_utente_uscito_dai_gruppi_perde_ruolo(client, ldap_auth, make_user):
    # Utente creato in passato con ruolo Admin; oggi in AD non è più in alcun gruppo.
    make_user("nnessuno", role=ADMIN, is_staff=True, is_superuser=True)

    assert_rejected(login(client, "nnessuno", "password-nnessuno"))

    user = get_user_model().objects.get(username="nnessuno")
    assert role_of(user) is None
    assert not user.is_staff and not user.is_superuser


def test_mrossi_password_errata_rifiutato_e_loggato(client, ldap_auth):
    assert_rejected(login(client, "mrossi", "sbagliata"))

    attempt = LoginAttempt.objects.get()
    assert (attempt.username, attempt.success, attempt.esito) == (
        "mrossi",
        False,
        LoginAttempt.Esito.CREDENZIALI_ERRATE,
    )
    assert attempt.ip_address == "127.0.0.1"
    assert not get_user_model().objects.filter(username="mrossi").exists()


def test_login_riuscito_loggato(client, ldap_auth):
    assert_logged_in(login(client, "mrossi", "password-mrossi"))

    attempt = LoginAttempt.objects.get()
    assert attempt.success
    assert attempt.esito == LoginAttempt.Esito.OK
    assert attempt.backend == "accounts.backends.RoleLDAPBackend"


def test_username_case_insensitive(client, ldap_auth):
    assert_logged_in(login(client, "MRossi", "password-mrossi"))
    client.logout()
    assert_logged_in(login(client, "mrossi", "password-mrossi"))

    assert list(get_user_model().objects.values_list("username", flat=True)) == ["mrossi"]


def test_cambio_gruppo_aggiorna_il_ruolo(client, ldap_auth, make_user):
    # Ruolo precedente (Reader) sostituito da quello attuale in AD (Editor).
    make_user("mrossi", role=READER)

    assert_logged_in(login(client, "mrossi", "password-mrossi"))

    user = get_user_model().objects.get(username="mrossi")
    assert list(user.groups.values_list("name", flat=True)) == [EDITOR]


def test_omonimo_del_breakglass_non_entra_da_ldap(client, ldap_auth, make_user):
    breakglass = make_user("mrossi", password="x" * 30, is_breakglass=True, is_superuser=True)

    assert_rejected(login(client, "mrossi", "password-mrossi"))

    breakglass.refresh_from_db()
    assert breakglass.is_breakglass and breakglass.has_usable_password()


def test_utente_locale_non_breakglass_non_entra_con_ldap_attivo(client, ldap_auth, make_user):
    make_user("locale", password="password-locale-di-prova", role=EDITOR)

    assert_rejected(login(client, "locale", "password-locale-di-prova"))


def test_ldap_non_raggiungibile_messaggio_generico_e_breakglass(client, ldap_down, make_user):
    make_user("breakglass", password="b" * 30, is_breakglass=True, is_superuser=True)

    response = login(client, "mrossi", "password-mrossi")
    assert_rejected(response)
    body = response.content.decode().lower()
    for dettaglio in ("ldap", "server_down", "can't contact", "127.0.0.1", "traceback"):
        assert dettaglio not in body
    attempt = LoginAttempt.objects.get()
    assert attempt.esito == LoginAttempt.Esito.LDAP_NON_DISPONIBILE

    assert_logged_in(login(client, "breakglass", "b" * 30))
    assert client.get(reverse("prova-amministrazione")).status_code == 200
    assert LoginAttempt.objects.filter(success=True).get().backend == (
        "accounts.backends.BreakGlassBackend"
    )


def test_certificato_non_fidato_rifiuta_il_login(client, settings, ldap_env):
    # Nessun ripiego in chiaro: con una CA che non ha firmato il server, StartTLS fallisce.
    system_bundle = "/etc/ssl/certs/ca-certificates.crt"
    if not os.path.isfile(system_bundle):
        pytest.skip("bundle CA di sistema assente")
    apply_auth_settings(settings, {**ldap_env, "LDAP_CA_CERT_FILE": system_bundle})

    assert_rejected(login(client, "mrossi", "password-mrossi"))
    assert LoginAttempt.objects.get().esito == LoginAttempt.Esito.LDAP_NON_DISPONIBILE


def test_utente_locale_omonimo_passa_ad_ad(client, ldap_auth, make_user):
    """Avvio senza AD con account locali (RUNBOOK §6.0): attivando LDAP, l'utente locale con
    lo stesso nome di dominio è lo stesso utente; il ruolo viene da AD, la password locale
    non vale più."""
    locale = make_user("mrossi", password="password-locale-temporanea", role=READER)

    assert_rejected(login(client, "mrossi", "password-locale-temporanea"))
    assert_logged_in(login(client, "mrossi", "password-mrossi"))

    utente = get_user_model().objects.get(username="mrossi")
    assert utente.pk == locale.pk  # stesso utente: lo storico delle modifiche resta suo
    assert role_of(utente) == EDITOR  # il ruolo di AD sostituisce quello assegnato a mano
    assert list(utente.groups.values_list("name", flat=True)) == [EDITOR]
