# Contribuire al Registro contratti ICTDINN

## Prima di iniziare

Leggere i documenti pertinenti:

- [SPEC](docs/SPEC.md) per requisiti e regole;
- [TEST_CASES](docs/TEST_CASES.md) per i risultati attesi;
- [ROADMAP](docs/ROADMAP.md) per fase e accettazione;
- [ARCHITECTURE](docs/ARCHITECTURE.md) per i confini tecnici;
- [SECURITY](docs/SECURITY.md) per dati e accessi;
- [CLAUDE.md](CLAUDE.md) per le regole degli assistenti di sviluppo.

Se requisito e richiesta sono in conflitto, la decisione deve essere resa esplicita prima di modificare il comportamento.

## Branch e pull request

- Un branch per obiettivo coerente.
- Commit piccoli e descrittivi in italiano.
- Nessun commit diretto su `main`.
- La pull request deve spiegare cosa cambia, come è stato verificato, impatto, rollback e decisioni aperte.
- Aggiornare documentazione e test nello stesso cambiamento del codice.
- Non aggirare i controlli salvo emergenza formalmente motivata.

## Regole di sviluppo

- Non aggiungere dipendenze senza motivazione.
- Non duplicare logica tra viste, report e MCP.
- Usare `Decimal` per gli importi e `datetime.date` per le date.
- Mantenere puro `contratti/engine/`.
- Non introdurre cancellazioni fisiche dei dati di dominio.
- Usare form, servizi e selettori condivisi per web e MCP.
- Committare ogni migration nuova; non modificare migration già confluite.

## Dati e segreti

È vietato committare:

- dati aziendali reali;
- import, export, backup o dump;
- file `.env`;
- password, token, certificati o chiavi;
- screenshot contenenti informazioni operative.

Le fixture devono usare nomi, codici e importi inventati.

## Verifica locale

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check
uv run pytest
```

Eseguire inoltre le suite mirate alla modifica. Per l'interfaccia usare i test UI/E2E; per MCP eseguire `tests/connettore`; per gli import usare `tests/importer`.

## Modifiche alla documentazione

- La SPEC descrive cosa deve fare il sistema.
- TEST_CASES contiene esempi normativi e non si modifica per far passare il codice.
- ROADMAP descrive fasi e stato.
- ARCHITECTURE descrive struttura e confini.
- RUNBOOK descrive installazione e scenari di produzione.
- OPERATIONS descrive le attività ricorrenti.
- Le decisioni architetturali durature si registrano come ADR.

## Release

Per una pull request destinata a una release seguire [`docs/RELEASE.md`](docs/RELEASE.md) e includere il testo proposto per tag e GitHub Release.
