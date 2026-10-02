# CLAUDE.md — Registro contratti IT/TLC (Siciliacque)

Web app interna per gestire i contratti dell'ufficio IT/TLC: catena dei rinnovi, budget su tre viste (impegno, cassa, competenza), previsione degli ordini per il Procurement.

Owner: Pietro Verro (IT Manager).

## Documenti da leggere prima di lavorare

- `docs/SPEC.md`: requisiti, modello dati, regole di calcolo, decisioni. È il riferimento.
- `docs/TEST_CASES.md`: casi numerici di riferimento. Sono l'oracolo dei test: **non modificarli per far passare un test**.
- `docs/ROADMAP.md`: fasi e criteri di accettazione. Lavora solo sulla fase richiesta.

Se la SPEC è ambigua o in conflitto con la richiesta, fermati e chiedi. Non scegliere in silenzio. Se proponi di cambiare la SPEC, scrivilo nella descrizione della PR: la SPEC la aggiorna Pietro.

## Stack (deciso, non cambiarlo senza approvazione)

- Python 3.12, Django 5.2 LTS, PostgreSQL 16.
- Template Django + HTMX + Bootstrap 5. Le risorse statiche vanno in `static/vendor/`, senza CDN: l'app gira in rete interna. Niente framework SPA.
- Interfaccia (F7): Bootstrap Icons, Tom Select (tendine con ricerca), flatpickr (calendario), font Maven Pro; tema in `static/css/app.css`, comportamenti in `static/js/app.js`. Identità: `static/img/logo/`, `docs/design/`.
- File statici serviti dall'app con `whitenoise` (dietro Nginx Proxy Manager), raccolti nell'immagine Docker.
- `django-auth-ldap` (Active Directory), `django-simple-history`, `openpyxl`, `django-environ`.
- Test: `pytest`, `pytest-django`, `playwright` (test nel browser in `tests/e2e`, con axe-core per l'accessibilità). Lint e format: `ruff`. Dipendenze con `uv`, lock file `uv.lock` versionato.
- Produzione: Docker Compose (gunicorn + postgres + backup) sul server Docker aziendale, tutto in `/appdata/gestione-contratti`, dietro il Nginx Proxy Manager esistente. Deploy manuale con `deploy/deploy.sh <tag>` (`docs/RUNBOOK.md`).

## Comandi

```bash
uv sync                                   # installa le dipendenze
uv run ruff check . && uv run ruff format --check .
uv run pytest                             # tutti i test
uv run python manage.py migrate
uv run python manage.py runserver
uv run python manage.py import_excel <file.xlsx> --area IT --dry-run
uv run python manage.py import_conti <piano_conti.csv> --dry-run
uv run python manage.py import_date_contratti <date_contratti.csv|xlsx> --dry-run
uv run python manage.py quadratura_excel <file.xlsx> --area IT
uv run pytest tests/e2e                   # solo i test nel browser (Chromium di Playwright)
```

Sul server di produzione gli stessi comandi passano da `deploy/manage.sh` (es. `deploy/manage.sh import_excel /import/<file> --area IT`).

Nelle sessioni cloud PostgreSQL è installato ma spento. Lo avvia `scripts/cloud_session_start.sh` (hook SessionStart); se non è attivo: `service postgresql start`.

## Struttura (obiettivo)

```
config/            settings (base/dev/test/prod), urls, wsgi
contratti/         app di dominio: models, admin, views, forms, templates
contratti/engine/  motore di calcolo PURO: scadenzario, competenza, alert, previsioni
contratti/importer/ import Excel, normalizzazione, report anomalie
accounts/          autenticazione LDAP, ruoli, break-glass
reports/           viste budget, piano ordini, export XLSX
tests/             test (fixtures/ contiene SOLO dati anonimizzati)
deploy/            docker-compose.prod.yml, proxy, script di deploy e backup
```

## Regole non negoziabili

1. **Nessun dato reale nel repository.** Si usano solo `tests/fixtures/*.xlsx`, che sono anonimizzati. Non creare fixture con nomi di fornitori reali, CIG reali o importi reali.
2. **Nessun segreto nel codice o nei commit.** La configurazione arriva da variabili d'ambiente; va documentata in `.env.example`.
3. **Soldi in `Decimal`**, `DecimalField(max_digits=14, decimal_places=2)`. Mai `float`, nemmeno nei calcoli intermedi. Arrotondamento `ROUND_HALF_UP` al centesimo, residuo sull'ultima rata o sull'ultimo anno. I totali ripartiti devono quadrare al centesimo con il valore del contratto.
4. **Date `datetime.date`**, estremi inclusi. Sottrazione e addizione di mesi con logica di fine mese (SPEC §5.1): una data di fine mese resta a fine mese (30/11 − 3 mesi = 31/08). `dateutil.relativedelta` da solo non basta (darebbe 30/08): va corretto per le date di fine mese.
5. **Il motore di calcolo (`contratti/engine/`) è puro.** Funzioni e dataclass senza ORM né I/O. Gli adapter convertono i modelli in input del motore. Ogni regola della SPEC §5 ha test unitari che usano i valori di `docs/TEST_CASES.md`.
6. **Valori derivati mai salvati come dato:** data di fine, data limite, alert, contratti previsti. Si calcolano. Unica eccezione: le rate dello scadenzario, che si generano e poi si possono modificare a mano. In quel caso va tracciato che la rata è stata modificata manualmente.
7. **Soglie, lead time, adeguamenti e giorni di pagamento** sono tabelle di configurazione con valori iniziali caricati da una data migration. Mai costanti nel codice.
8. **Nessuna cancellazione fisica** dei dati di dominio: si archiviano. La storia delle modifiche passa da `django-simple-history`.
9. **Ruoli**: Admin, Editor, Reader, dai gruppi AD configurabili. Ogni vista che modifica dati ha un test che verifica il 403 per il Reader.
10. **LDAP mai contattato nei test.** Si usa un server di test (`slapdtest` di python-ldap, `slapd` è installato nell'ambiente cloud) o un mock. Il backend LDAP si attiva solo se `LDAP_SERVER_URI` è valorizzata. Senza, vale solo l'autenticazione locale (sviluppo).

## Convenzioni

- Nomi di dominio in italiano, senza accenti, `snake_case` o `PascalCase` (`Fabbisogno`, `Contratto`, `VoceContratto`, `PianoFatturazione`, `Rata`). Il resto segue le convenzioni Django in inglese.
- Interfaccia in italiano; numeri `1.234,56`, date `31/12/2026`, `TIME_ZONE = "Europe/Rome"`.
- Le migration si committano sempre e non si modificano dopo il merge su `main`.
- Commit piccoli e descrittivi in italiano. Una PR per fase o sotto-fase, con descrizione che riporta cosa è stato fatto, come è stato verificato, cosa resta aperto e le deviazioni dalla SPEC.
- Prima di chiudere una PR: `ruff` pulito, `pytest` verde, migration generate (`makemigrations --check`).
- Ogni PR che diventa una release riporta il testo del tag da creare: nome (`vX.Y.Z`), titolo e descrizione (novità, correzioni, database e rollback, cosa verificare dopo il deploy). Lo stesso testo va nel messaggio finale a Pietro.

## Cosa NON fare

- Non aggiungere dipendenze fuori stack senza motivarlo nella PR.
- Non modificare `docs/TEST_CASES.md` o `docs/SPEC.md` di tua iniziativa.
- Non disattivare o saltare test per far passare la CI.
- Non introdurre chiamate a servizi esterni: CDN, telemetria, API pubbliche.
