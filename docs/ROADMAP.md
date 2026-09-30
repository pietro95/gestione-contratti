# Roadmap e criteri di accettazione

Ogni fase è una PR (o poche PR) verso `main`. Una fase è chiusa solo quando tutti i suoi criteri sono verificati da test automatici o dal controllo manuale indicato.

## F0 — Scheletro del progetto

- Progetto Django 5.2 con settings `base/dev/test/prod` configurati da variabili d'ambiente (`django-environ`).
- `pyproject.toml` + `uv.lock`, `ruff` configurato, `pytest-django` configurato.
- PostgreSQL anche nei test, niente SQLite, per avere lo stesso comportamento dei `Decimal` e delle date.
- App `accounts` con:
  - backend LDAP opzionale (attivo solo con `LDAP_SERVER_URI` valorizzata);
  - mappatura gruppi → ruoli;
  - login e logout;
  - log dei login.
- Pagina home protetta da login; endpoint `/healthz` senza autenticazione (risponde 200 se il database è raggiungibile).
- `.env.example` completo.

**Accettazione:**
- CI verde;
- test TC-09 completi con un server LDAP di test;
- `docker compose -f deploy/docker-compose.dev.yml up` porta l'app su localhost.

## F1 — Modello dati e amministrazione

- Modelli secondo SPEC §4:
  - `Fornitore`, `Fabbisogno`, `Contratto`, `VoceContratto`, `PianoFatturazione`, `Rata`;
  - `StatoPratica` (storico dei passaggi);
  - tabelle di configurazione: lead time, soglie, piano dei conti con validità temporale, parametri.
- Vincoli di integrità nel database (CheckConstraint), non solo nei form: importi ≥ 0, durata > 0, stima di consumo tra 0 e 100.
- Storia delle modifiche su tutte le entità di dominio.
- Django admin configurato per tutte le entità, come strumento di back-office.
- Data migration con i parametri iniziali, marcati come provvisori.

**Accettazione:** test di vincoli e relazioni; admin navigabile; `makemigrations --check` pulito.

## F2 — Motore di calcolo

`contratti/engine/`, puro:
- generazione dello scadenzario rate;
- competenza a giorni;
- viste impegno, cassa e competenza con livelli fisso, probabile e massimo;
- data limite e alert;
- rinnovi previsti ricorsivi.

**Accettazione:** TC-01 … TC-07 implementati come test parametrizzati, tutti verdi. Proprietà verificata con `hypothesis`: la somma della competenza è sempre uguale al valore della voce.

## F3 — Import Excel

- Comando `import_excel`: lettura dei fogli e delle tabelle con la struttura degli Excel attuali; normalizzazione; report delle anomalie (CSV + riepilogo a video); `--dry-run`; idempotenza.
- Proposta automatica di raggruppamento in fabbisogni (descrizione normalizzata + fornitore) e dei predecessori. Le proposte vanno in una tabella di staging e si confermano da interfaccia o admin, mai in automatico.

**Accettazione:**
- TC-08 verde;
- import completo delle due fixture senza eccezioni;
- report che elenca tutte le anomalie note (SPEC §2.2).

## F4 — Interfaccia operativa

- Elenchi filtrabili: contratti, fabbisogni, fornitori.
- Dettaglio del contratto con voci, scadenzario e storico.
- Form di inserimento con piano di fatturazione e anteprima dello scadenzario.
- Cruscotto degli alert.
- Avanzamento della pratica di rinnovo.
- Conferma delle proposte di raggruppamento dall'import.

**Accettazione:**
- test di permesso per ogni vista (Reader → 403 sulle modifiche);
- test end-to-end del flusso "registro rinnovo → il previsto sparisce".

## F5 — Report

- Budget per anno con le tre viste e i tre livelli, filtri per area, conto, fornitore e finanziamento; distinzione tra dati consolidati e previsionali.
- Piano ordini dell'anno X (SPEC §5.4).
- Confronto con il file Excel (quadratura, SPEC §7.8).
- Export XLSX di ogni report.

**Accettazione:** i totali dei report sulle fixture coincidono con quelli calcolati direttamente dal motore (test).

## F6 — Deploy on-prem

- `deploy/docker-compose.prod.yml`: gunicorn, postgres con volume, reverse proxy HTTPS (certificato della CA interna montato da file).
- Script:
  - `deploy/deploy.sh`: pull, build, migrate, collectstatic, restart;
  - `deploy/backup.sh`: `pg_dump` con rotazione;
  - `deploy/restore.md`: procedura di ripristino.
- Runbook `docs/RUNBOOK.md`: installazione della VM, variabili, rinnovo del certificato, aggiornamento.

**Accettazione:** installazione da zero su una VM pulita seguendo solo il runbook (verifica manuale di Pietro).
