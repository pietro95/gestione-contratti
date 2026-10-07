<p align="center">
  <img src="static/img/logo/siciliacque.svg" alt="Siciliacque S.p.A." width="460">
</p>

<h1 align="center">Registro contratti ICTDINN</h1>

<p align="center">
  Applicazione interna per la gestione del ciclo di vita dei contratti e del processo d'acquisto dell'ufficio ICTDINN.
</p>

> [!IMPORTANT]
> Il repository non contiene dati aziendali reali. I file presenti in `tests/fixtures/` sono dati di prova anonimizzati.

## Panoramica

Il Registro contratti ICTDINN supporta le attività degli ambiti IT, TLC, OT, Sicurezza fisica e Innovazione di Siciliacque S.p.A. Dalla programmazione del fabbisogno accompagna il contratto lungo scadenze, rinnovi, budget ed esecuzione, fino alla chiusura.

Le funzioni principali comprendono:

- anagrafica di fabbisogni, fornitori e contratti;
- catene di rinnovo, proroghe, scadenze e avvisi;
- budget per impegno, cassa e competenza;
- piano degli ordini per il Procurement;
- richieste di acquisto (RDA), scheda SAP e avanzamento della pratica;
- import e lavorazione delle fatture;
- esecuzione del contratto, documenti, residui e chiusura;
- cruscotti ed esportazioni XLSX e PDF;
- connettore MCP con OAuth, strumenti in lettura e scrittura controllata.

L'applicazione è progettata per funzionare nella rete aziendale e non usa CDN, telemetria o servizi esterni. Il connettore MCP costituisce un componente separato e facoltativo, esposto secondo le misure descritte nella relativa specifica e nel runbook.

## Stato del progetto

La versione stabile più recente è documentata nelle [release GitHub](https://github.com/pietro95/gestione-contratti/releases). Il branch `main` può contenere funzionalità già completate per la release successiva.

Lo sviluppo è organizzato per fasi e criteri di accettazione:

- [Roadmap](docs/ROADMAP.md)
- [Specifica funzionale](docs/SPEC.md)
- [Specifica del connettore MCP](docs/SPEC_MCP.md)
- [Casi di test di riferimento](docs/TEST_CASES.md)

## Architettura

| Componente | Responsabilità |
|---|---|
| `accounts/` | autenticazione Active Directory, ruoli e account di emergenza |
| `contratti/` | dominio applicativo, contratti, fabbisogni, RDA, fatture e import |
| `contratti/engine/` | calcoli puri per date, scadenze, budget e previsioni |
| `reports/` | cruscotti, report ed esportazioni XLSX/PDF |
| `connettore/` | endpoint MCP, OAuth e operazioni in due fasi |
| `config/` | configurazione Django per sviluppo, test, produzione e MCP |
| `deploy/` | Docker Compose, deploy, backup, ripristino e verifiche operative |
| `tests/` | test unitari, di integrazione, UI ed end-to-end |

Stack principale: Python 3.12, Django 5.2 LTS, PostgreSQL 16, template Django con HTMX e Bootstrap, Gunicorn e Docker Compose.

## Avvio in sviluppo

### Requisiti

- Python 3.12;
- [uv](https://docs.astral.sh/uv/);
- PostgreSQL 16;
- `slapd` e librerie LDAP soltanto per i test di integrazione LDAP.

La configurazione di sviluppo usa, in assenza di un file `.env`, il database locale:

```text
postgres://contratti:contratti@localhost:5432/contratti
```

Dopo aver creato utente e database PostgreSQL:

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

L'applicazione sarà disponibile su [http://localhost:8000](http://localhost:8000). Senza `LDAP_SERVER_URI` il login usa gli utenti locali Django ed è ammesso soltanto in sviluppo.

### Avvio con Docker

```bash
docker compose -f deploy/docker-compose.dev.yml up --build
docker compose -f deploy/docker-compose.dev.yml exec web python manage.py createsuperuser
```

Il servizio è esposto esclusivamente su `127.0.0.1:8000`.

## Qualità e test

Per eseguire i controlli principali:

```bash
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check
uv run pytest
```

Suite mirate:

```bash
uv run pytest tests/engine
uv run pytest tests/importer
uv run pytest tests/reports
uv run pytest tests/connettore
uv run pytest tests/e2e
```

I test usano PostgreSQL anche in locale. I test end-to-end richiedono Chromium di Playwright; quelli LDAP richiedono un server `slapd` di prova e non contattano mai l'Active Directory aziendale.

## Produzione

La produzione gira in container su un server Docker aziendale condiviso, sotto `/appdata/gestione-contratti`, dietro il reverse proxy esistente.

Le procedure operative non vanno ricostruite dal codice:

- [RUNBOOK](docs/RUNBOOK.md): installazione, aggiornamento, autenticazione, backup, certificati e connettore MCP;
- [procedura di ripristino](deploy/restore.md);
- [variabili d'ambiente di esempio](.env.example).

Il deploy avviene tramite `deploy/deploy.sh <tag-o-commit>` e comprende controlli, migration, backup preventivo e avvio dei servizi. Prima di ogni aggiornamento devono essere verificati il piano di rollback e le note della release.

### Autenticazione e ruoli

In produzione l'accesso avviene tramite Active Directory:

- `Admin`: configurazione e tutte le operazioni;
- `Editor`: modifica nei cluster autorizzati;
- `Reader`: consultazione nei cluster autorizzati.

Con `LDAP_SERVER_URI` valorizzata, gli utenti locali sono esclusi a eccezione dell'account di emergenza creato con:

```bash
deploy/manage.sh crea_breakglass
```

LDAP deve usare LDAPS oppure StartTLS con verifica del certificato. L'endpoint `/healthz` restituisce `200` se il database risponde e `503` in caso contrario.

## Documentazione

| Documento | Contenuto |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | requisiti, modello dati, regole e decisioni |
| [`docs/TEST_CASES.md`](docs/TEST_CASES.md) | casi numerici che costituiscono l'oracolo dei test |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | fasi, attività e criteri di accettazione |
| [`docs/SPEC_MCP.md`](docs/SPEC_MCP.md) | architettura, sicurezza e strumenti del connettore |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | gestione dell'ambiente di produzione |
| [`CLAUDE.md`](CLAUDE.md) | regole operative per gli assistenti di sviluppo |

## Sicurezza e dati

- Non committare file `.env`, chiavi, certificati o credenziali.
- Non inserire dati reali, nomi di fornitori, CIG o importi aziendali nelle fixture.
- Conservare gli import operativi esclusivamente nelle directory del server previste dal runbook.
- Trattare le esportazioni e i backup come dati aziendali riservati.
- Seguire sempre la procedura di anteprima e conferma per le scritture tramite MCP.

Il logo e gli altri elementi dell'identità visiva sono destinati esclusivamente all'applicazione interna. Le varianti disponibili e le regole d'uso sono descritte in [`static/img/logo/README.md`](static/img/logo/README.md).
