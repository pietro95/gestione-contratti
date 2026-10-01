# Registro contratti IT/TLC

Web app interna di Siciliacque S.p.A. per gestire i contratti dell'ufficio IT/TLC. Copre:
- scadenze e rinnovi;
- budget su tre viste: impegno, cassa, competenza;
- piano ordini per il Procurement.

- Requisiti: [`docs/SPEC.md`](docs/SPEC.md)
- Casi di test: [`docs/TEST_CASES.md`](docs/TEST_CASES.md)
- Fasi: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Istruzioni per Claude Code: [`CLAUDE.md`](CLAUDE.md)

**Nessun dato reale in questo repository.** I file in `tests/fixtures/` sono anonimizzati.

## Sviluppo

Requisiti: Python 3.12, [`uv`](https://docs.astral.sh/uv/), PostgreSQL 16; per i test LDAP `slapd`
(`apt install slapd ldap-utils`) e, per compilare python-ldap, `libldap2-dev libsasl2-dev`.

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser     # login locale: senza LDAP_SERVER_URI
uv run python manage.py runserver
uv run pytest                               # PostgreSQL anche nei test
uv run ruff check . && uv run ruff format --check .
```

Con Docker: `docker compose -f deploy/docker-compose.dev.yml up --build`, poi http://localhost:8000.

## Produzione

Server Docker aziendale condiviso, tutto sotto `/appdata/gestione-contratti`, dietro il reverse
proxy nginx esistente: [`docs/RUNBOOK.md`](docs/RUNBOOK.md) (installazione, aggiornamento, backup,
certificati) e [`deploy/restore.md`](deploy/restore.md) (ripristino).

Configurazione: variabili d'ambiente, tutte documentate in [`.env.example`](.env.example).

### Autenticazione

- Con `LDAP_SERVER_URI` valorizzata: login con le credenziali di dominio (LDAPS o StartTLS),
  ruolo dai gruppi AD (`Admin` > `Editor` > `Reader`, gruppi annidati inclusi). Chi non è in
  alcun gruppo non entra. L'unico accesso locale ammesso è l'account di emergenza:
  `uv run python manage.py crea_breakglass`.
- Senza `LDAP_SERVER_URI`: login locale con gli utenti Django (solo sviluppo).
- `/healthz`: 200 se il database risponde, 503 altrimenti; senza autenticazione.
