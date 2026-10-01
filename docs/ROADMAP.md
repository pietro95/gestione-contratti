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

## F7 — Interfaccia grafica e identità aziendale

Bozza (Rev00): le scelte indicate con *[da confermare]* attendono la decisione di Pietro.

Obiettivo: rendere l'applicazione usabile ogni giorno da chi non l'ha sviluppata. Le funzioni
restano quelle di F4–F5; cambiano struttura delle pagine, gerarchia visiva e flussi.

**Identità**
- Logo aziendale nell'intestazione, nella pagina di login, nei PDF stampati e come favicon.
  Il file viene fornito da Pietro (SVG, o PNG ad alta risoluzione) e sta in `static/img/`.
- Colori aziendali come variabili CSS che personalizzano Bootstrap (`static/css/app.css`),
  senza compilazione Sass. *[da confermare: codici colore del manuale d'identità]*
- Font servito in locale da `static/vendor/`, nessun CDN. *[da confermare: font aziendale o
  Titillium Web]*

**Struttura**
- Barra laterale con le sezioni:
  - Operatività: Cruscotto, Contratti, Fabbisogni, Fornitori;
  - Report: Budget, Piano ordini;
  - Gestione: Proposte import, Amministrazione (solo Admin).
- Barra superiore con ricerca globale (descrizione, OdA, CIG, fornitore), utente e ruolo.
- Intestazione di pagina uniforme: breadcrumb, titolo, azioni principali a destra.
- Messaggi come notifiche temporanee; conferme (archiviazione, proposte) in finestre modali.

**Pagine**
- **Home = cruscotto**:
  - schede con i numeri chiave (scaduti, oltre la data limite, in avvicinamento, proposte da
    valutare, budget dell'anno corrente);
  - prossime scadenze a 90 giorni;
  - azioni rapide.
- **Elenchi**:
  - colonne ordinabili e intestazione fissa;
  - filtri in un pannello richiudibile, con i filtri attivi mostrati come etichette rimovibili;
  - importi allineati a destra con cifre a larghezza fissa;
  - stati come badge; riga cliccabile;
  - messaggio guidato quando l'elenco è vuoto.
- **Dettaglio contratto**:
  - scheda riassuntiva (date chiave, alert, valore, fornitore);
  - schede: Voci e piano, Scadenzario, Proroghe e rinnovi, Pratica, Storico;
  - linea temporale della catena dei rinnovi.
- **Form**:
  - campi raggruppati in sezioni su più colonne, con aiuti in linea;
  - date in formato gg/mm/aaaa in tutti i browser *[da confermare: calendario a comparsa]*;
  - ricerca nelle tendine lunghe (fornitori, fabbisogni) *[da confermare: libreria locale]*.
- **Budget e piano ordini**: schede di riepilogo in alto, tabella più leggibile (prima colonna
  fissa, livelli selezionabili), avvisi richiudibili, export nell'intestazione.
- **Login**: pagina con logo e messaggi chiari (credenziali di dominio, account di emergenza).
- **Stampa**: intestazione con logo, data e filtri, per i PDF da allegare.

**Qualità**
- Accessibilità WCAG 2.1 AA: contrasto, navigazione da tastiera, focus visibile, etichette.
- Desktop e tablet (≥ 1024 px); su schermi più piccoli almeno la consultazione.
- Nessuna risorsa esterna: tutte le librerie in `static/vendor/` con licenza documentata.

**Accettazione:**
- test esistenti verdi e nessuna funzione persa (stessi URL e stessi permessi);
- test end-to-end nel browser (Playwright, in CI) sulle pagine principali: caricamento senza
  errori JavaScript, navigazione da tastiera, nessuna violazione di accessibilità grave;
- revisione di Pietro sugli screenshot delle pagine principali, prima e dopo.
