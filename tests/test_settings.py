"""Settings: test isolati da .env e LDAP spento di default; check di sistema."""

import pytest
from django.conf import settings
from django.core.checks import run_checks

from accounts.checks import ldap_attivo_in_produzione, ldap_ca_leggibile

from .conftest import apply_auth_settings, ldap_env_for


def test_test_usano_postgresql_e_ldap_spento():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert settings.AUTHENTICATION_BACKENDS == ["django.contrib.auth.backends.ModelBackend"]
    assert not hasattr(settings, "AUTH_LDAP_SERVER_URI")


def test_localizzazione():
    assert settings.LANGUAGE_CODE == "it"
    assert settings.TIME_ZONE == "Europe/Rome"
    assert settings.USE_TZ


def test_check_ca_mancante(settings):
    env = ldap_env_for("ldaps://dc01:636", "/percorso/inesistente.pem", LDAP_START_TLS="")
    apply_auth_settings(settings, env)
    errors = ldap_ca_leggibile(None)
    assert [e.id for e in errors] == ["accounts.E001"]


def test_check_ca_presente(settings, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("finto")
    apply_auth_settings(settings, ldap_env_for("ldaps://dc01:636", str(ca), LDAP_START_TLS=""))
    assert ldap_ca_leggibile(None) == []


def test_warning_deploy_senza_ldap():
    assert [w.id for w in ldap_attivo_in_produzione(None)] == ["accounts.W001"]


@pytest.mark.django_db
def test_nessun_errore_di_sistema():
    errors = [m for m in run_checks() if m.is_serious()]
    assert errors == []


def test_file_statici_serviti_dall_app():
    """Dietro Nginx Proxy Manager il proxy inoltra anche /static/: li serve WhiteNoise."""
    from django.conf import settings

    middleware = settings.MIDDLEWARE
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in middleware
    assert middleware.index("whitenoise.middleware.WhiteNoiseMiddleware") == (
        middleware.index("django.middleware.security.SecurityMiddleware") + 1
    )
    assert settings.STORAGES["staticfiles"]["BACKEND"].startswith("whitenoise.")
