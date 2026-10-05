"""Container ``mcp`` sull'host pubblico (SPEC_MCP §2.2): solo connettore, niente interfaccia.

Stessa immagine e stessa configurazione della produzione, con una URLconf ridotta ai soli
endpoint pubblici e senza sessioni, CSRF e messaggi: qui si entra solo con un token OAuth.
Il database si usa con l'utente limitato (``MCP_DATABASE_URL``, comando ``ruolo_db_mcp``).
"""

from .prod import *

ROOT_URLCONF = "config.urls_mcp"
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]
# L'admin resta installato (i modelli servono) ma qui non è raggiungibile: i controlli sui
# middleware dell'admin non riguardano questo processo.
SILENCED_SYSTEM_CHECKS = ["admin.E408", "admin.E409", "admin.E410"]
