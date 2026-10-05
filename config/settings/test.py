"""Test. Non legge ``.env``: nessuna configurazione dello sviluppatore entra nei test.

LDAP spento di default; i test LDAP lo attivano con le fixture di ``tests/conftest.py``.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-solo-locale-non-segreto")
os.environ.setdefault("DATABASE_URL", "postgres://contratti:contratti@localhost:5432/contratti")
# Connettore MCP acceso nei test, con host fittizi (SPEC_MCP §2.1).
os.environ.setdefault("MCP_URL_PUBBLICO", "https://mcp.esempio.test")
os.environ.setdefault("MCP_URL_INTERNO", "https://contratti.esempio.test")

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "mcp.esempio.test", "contratti.esempio.test"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
DATABASES["default"]["CONN_MAX_AGE"] = 0

# WhiteNoise senza collectstatic: file letti dalle cartelle sorgente a ogni richiesta.
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
