"""Settings comuni. La configurazione arriva da variabili d'ambiente (django-environ).

I moduli dev/test/prod importano da qui e ridefiniscono solo ciò che cambia.
L'autenticazione LDAP si configura in dev e prod con ``accounts.ldap_config``;
i test la attivano solo nei test che la richiedono.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "oauth2_provider",
    "accounts",
    "contratti",
    "reports",
    "connettore",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # File statici serviti dall'app (il reverse proxy inoltra tutto, anche /static/).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.ruolo",
                "accounts.context_processors.versione",
                "contratti.context_processors.navigazione",
            ],
        },
    },
]

# PostgreSQL ovunque, test compresi (niente SQLite).
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Autenticazione
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Il break-glass richiede una password lunga (SPEC §8.1).
BREAKGLASS_MIN_PASSWORD_LENGTH = env.int("BREAKGLASS_MIN_PASSWORD_LENGTH", default=24)

# Sessioni e cookie
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=8 * 60 * 60)
CSRF_COOKIE_HTTPONLY = True

# Localizzazione: interfaccia in italiano, 1.234,56 e 31/12/2026.
LANGUAGE_CODE = "it"
LANGUAGES = [("it", "Italiano")]
TIME_ZONE = env("APP_TIME_ZONE", default="Europe/Rome")

# Versione installata (tag git), impostata da deploy/deploy.sh; mostrata nel piè di pagina.
APP_VERSION = env("APP_VERSION", default="sviluppo")
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Compressione gzip/brotli in collectstatic; nomi senza hash (le librerie hanno la versione
# nel percorso), cache del browser di un'ora.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 3600

# --- Connettore MCP (F10, docs/SPEC_MCP.md) ------------------------------------------
# URL pubblico dell'host dedicato al connettore (es. https://mcp-contratti.esempio.it) e URL
# interno dell'applicazione, dove l'utente fa login e autorizza (SPEC_MCP §2.1). Con
# MCP_URL_PUBBLICO vuoto il connettore è spento: /mcp e i metadati rispondono 404.
MCP_URL_PUBBLICO = env("MCP_URL_PUBBLICO", default="").rstrip("/")
MCP_URL_INTERNO = env("MCP_URL_INTERNO", default="").rstrip("/")
MCP_SCOPE_LETTURA = "registro.lettura"
MCP_SCOPE_SCRITTURA = "registro.scrittura"
# Dimensione massima del risultato di un tool (SPEC_MCP §6): oltre, si chiede di filtrare.
MCP_RISPOSTA_MAX_BYTES = env.int("MCP_RISPOSTA_MAX_BYTES", default=200_000)

OAUTH2_PROVIDER = {
    "SCOPES": {
        MCP_SCOPE_LETTURA: "Lettura del registro contratti",
        MCP_SCOPE_SCRITTURA: "Modifica del registro contratti, con anteprima e conferma",
    },
    "DEFAULT_SCOPES": [MCP_SCOPE_LETTURA],
    "OAUTH2_VALIDATOR_CLASS": "connettore.oauth.Validatore",
    # Durate: codice 60 secondi, access token 1 ora; il refresh non scade da solo, lo ferma
    # la regola dei 7 giorni dall'ultimo login (SPEC_MCP §4.4, D3).
    "AUTHORIZATION_CODE_EXPIRE_SECONDS": 60,
    "ACCESS_TOKEN_EXPIRE_SECONDS": env.int("MCP_ACCESS_TOKEN_SECONDI", default=3600),
    "REFRESH_TOKEN_EXPIRE_SECONDS": None,
    "ROTATE_REFRESH_TOKEN": True,
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    # Nessuna tolleranza sul refresh già ruotato: con i token salvati solo come hash non si
    # può restituire di nuovo quello emesso. Il riuso revoca tutto il collegamento.
    "REFRESH_TOKEN_GRACE_PERIOD_SECONDS": 0,
    "PKCE_REQUIRED": True,
    "REQUEST_APPROVAL_PROMPT": "force",
    # http solo per il redirect loopback di Claude Code, su qualunque porta (RFC 8252).
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https", "http"],
    "ALLOW_LOCALHOST_LOOPBACK": True,
    # Nessuna registrazione dinamica, nessun download di documenti di client: i client si
    # creano a mano con ``manage.py crea_client_mcp`` (SPEC_MCP §4.3).
    "DCR_ENABLED": False,
    "CIMD_ENABLED": False,
    "OAUTH2_RESPONSE_TYPES_SUPPORTED": ["code"],
    "OAUTH2_GRANT_TYPES_SUPPORTED": ["authorization_code", "refresh_token"],
    "OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED": [
        "client_secret_basic",
        "client_secret_post",
        "none",
    ],
    "OAUTH2_PROTECTED_RESOURCE_IDENTIFIER": f"{MCP_URL_PUBBLICO}/mcp" if MCP_URL_PUBBLICO else "",
    "OAUTH2_PROTECTED_RESOURCE_AUTHORIZATION_SERVERS": [MCP_URL_PUBBLICO]
    if MCP_URL_PUBBLICO
    else [],
    "OAUTH2_PROTECTED_RESOURCE_NAME": "Registro contratti ICTDINN",
    "OIDC_ISS_ENDPOINT": MCP_URL_PUBBLICO,
    # RFC 9700: solo S256, niente implicit e password, token solo nell'header, token salvati
    # solo come hash.
    "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PKCE_METHOD": True,
    "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT": True,
    "COMPLIANT_BCP_RFC9700_TOKEN_STORAGE": True,
    # RFC 9207: parametro «iss» nella risposta di autorizzazione (difesa dal mix-up).
    "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS": True,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "loggers": {
        "accounts.auth": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # PDF dei report: WeasyPrint porta fontTools a DEBUG mentre riduce i font; senza
        # propagazione quei messaggi non arrivano al log dell'applicazione.
        "fontTools": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "weasyprint": {"level": "WARNING"},
        "django_auth_ldap": {
            "handlers": ["console"],
            "level": env("LDAP_LOG_LEVEL", default="WARNING"),
            "propagate": False,
        },
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default="WARNING")},
}
