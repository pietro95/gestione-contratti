"""Test. Non legge ``.env``: nessuna configurazione dello sviluppatore entra nei test.

LDAP spento di default; i test LDAP lo attivano con le fixture di ``tests/conftest.py``.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-solo-locale-non-segreto")
os.environ.setdefault("DATABASE_URL", "postgres://contratti:contratti@localhost:5432/contratti")

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
DATABASES["default"]["CONN_MAX_AGE"] = 0
