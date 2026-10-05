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

Rev01: scelte confermate da Pietro (logo e linee guida tipografiche in `docs/design/`).

Obiettivo: rendere l'applicazione usabile ogni giorno da chi non l'ha sviluppata. Le funzioni
restano quelle di F4–F5; cambiano struttura delle pagine, gerarchia visiva e flussi.

**Identità**
- Logo aziendale nell'intestazione, nella pagina di login, nei PDF stampati e come favicon.
  File forniti da Pietro in `static/img/logo/` (colore, bianco, nero).
- Colori aziendali come variabili CSS che personalizzano Bootstrap (`static/css/app.css`),
  senza compilazione Sass: blu istituzionale `#003F6B`, azzurro `#5CBBFF` solo su fondo blu
  (su bianco ha contrasto 2,1:1, sotto WCAG AA), verde del logo `#177F42` per gli stati positivi.
  Scala tipografica da applicazione gestionale (titolo di pagina ~28 px, testo 15–16 px): le
  dimensioni delle linee guida sono pensate per il sito web.
- Font Maven Pro (linee guida), servito in locale da `static/vendor/`, nessun CDN.

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
  - nessun grafico: la dashboard grafica resta nella Fase 2 della SPEC.
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
  - date in formato gg/mm/aaaa in tutti i browser, con calendario a comparsa (flatpickr);
  - ricerca nelle tendine lunghe (fornitori, fabbisogni) con Tom Select.
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

## F8 — Correzioni del modello dopo il primo uso

Rev00: note di Pietro dopo il primo uso in produzione (v1.0.2), proposte approvate.

**Numero di contratto**
- In azienda non si usa l'OdA: il riferimento SAP è il numero di contratto. I campi diventano
  `numero_contratto` e `data_emissione` (rinomina, nessun dato perso); lo stato della pratica
  "OdA emesso" diventa "Contratto emesso", anche nello storico. Resta il controllo delle 10 cifre.
- Gli Excel non hanno la data di emissione: comando `import_date_contratti` da un'estrazione
  SAP (CSV o XLSX). Compila solo le date vuote, le discordanze vanno nel report.

**Budget: il fatturato è il riferimento**
- Il budget si legge sulla fatturazione (rate per data fattura): prima colonna e default.
- "Impegno" diventa "Ordinato (contratti emessi)": resta come informazione per il Procurement.
- Elenco di lavoro "Piani da verificare": voci senza piano reale, il cui fatturato è un
  pro-rata, ordinate per importo.

**OPEX e CAPEX distinti**
- Budget con filtro natura obbligatorio (default OPEX); "OPEX e CAPEX, separati" mostra due
  sezioni con totali propri, mai sommati. Lo stesso nell'export e nella home.
- Piano ordini: contiene entrambe le nature, con colonna, filtro e totali per natura; il
  controllo del frazionamento resta trasversale.
- Fabbisogno: natura e conto dei rinnovi previsti, per i contratti nati CAPEX con rinnovi in
  OPEX. Il previsto resta finanziato solo se conserva la natura.

**Catena dei rinnovi**
- "Sposta in un altro fabbisogno" (solo il contratto o anche i successivi): nell'origine la
  catena si richiude, nella destinazione si sceglie il predecessore. Anteprima, poi conferma.
- "Accorpa in…": i contratti passano al fabbisogno scelto, l'origine si archivia; propone il
  collegamento tra catene consecutive; previsto manuale e pratica presenti in entrambi: si
  sceglie quale tenere, nulla si cancella.
- Il fabbisogno non si cambia più dal form di modifica del contratto.

**Accettazione:**
- test verdi, compresi quelli nel browser sulle nuove pagine (accessibilità, flusso Sposta);
- Pietro: data di emissione caricata da SAP sui contratti reali, un accorpamento e uno
  spostamento sui dati reali, budget OPEX e CAPEX confrontati con le attese.

## F9.1 — Import dall'interfaccia

Rev00: richiesta di Pietro del 02/10/2026, proposte approvate.

- Pagina Gestione → Import: Excel dei contratti, date di emissione, piano dei conti,
  quadratura con l'Excel. Modello XLSX scaricabile per ogni import, generato dall'app.
- Carica → anteprima (stesso codice, nessuna scrittura; conteggi e anomalie, report XLSX) →
  conferma. La conferma usa il file caricato, vale 24 ore, una sola volta; può confermare chi
  ha caricato il file o un Admin.
- Registro degli import: file, hash, utente, anteprima, esito. Lo stesso file già importato
  è segnalato; rieseguirlo è innocuo.
- Permessi: Excel dei contratti, date di emissione e quadratura per Admin ed Editor (i
  responsabili); piano dei conti solo Admin (tabella di configurazione). Dalla F9.2 gli Editor
  importano solo nei propri cluster.
- File `.xlsx`/`.csv` fino a 10 MB, esecuzione immediata (nessuna coda di lavori).
- I comandi da riga di comando restano e usano lo stesso codice.

**Accettazione:** test verdi (anteprima senza scritture, conferma, scadenza, permessi, modelli
reimportabili, flusso nel browser); Pietro carica dal web le date di emissione estratte da SAP.

## F9.1.1 — Correzioni dopo il primo uso dell'import web

Rev00: segnalazioni di Pietro del 02/10/2026.

- **Import Excel incrementale**: un contratto già registrato si riconosce anche quando il file
  è cambiato (righe inserite o spostate, foglio rinominato, altro cluster, dati corretti) o è
  stato inserito a mano: numero di contratto (o CIG) e data di inizio; senza codici,
  fornitore, descrizione, data di inizio e durata. La riga si scarta e va nel report.
- **Accorpa**: lo stesso contratto registrato due volte si unisce (si tiene quello con più
  dati, l'altro si archivia e la catena passa a quello tenuto). I doppioni già presenti in un
  fabbisogno si uniscono dal dettaglio del fabbisogno.
- **Accorpa, catena dei rinnovi**: a ogni contratto senza successore si propone come rinnovo
  il contratto senza predecessore che inizia per primo dopo la sua fine (ogni contratto una
  volta sola, prima le coppie più vicine), anche quando le catene dei due fabbisogni si
  alternano nel tempo. Se il periodo seguente è già coperto da un rinnovo di un altro
  contratto, nessuna proposta e un avviso (più predecessori: F9.3). Le catene già interrotte
  (fabbisogni accorpati prima della correzione) si ricuciono dal dettaglio del fabbisogno;
  il contratto rimasto in rosso lo segnala.
- **Nuovo contratto guidato**: 1 contratto, 2 voce con piano di fatturazione (anteprima delle
  rate), 3 scadenzario generato, con «Aggiungi un'altra voce» o «Concludi». Salvando una voce
  le rate si generano sempre; quelle modificate a mano o consuntivate non si toccano.

## F9.1.2 — Rinnovi che partono prima della scadenza

Rev00: segnalazione di Pietro del 02/10/2026 (contratto 01/03/2025–28/02/2026 rinnovato dal
01/01/2026 nello stesso fabbisogno, in rosso «Senza rinnovo» e senza modo di collegarli).

- **Proposta di collegamento**: il rinnovo può iniziare prima della scadenza del
  predecessore. Si propone il contratto senza predecessore che inizia dopo e finisce dopo,
  con l'inizio più vicino al giorno dopo la fine; i periodi sovrapposti sono segnalati. Un
  contratto parallelo che finisce prima non è un rinnovo.
- **Collegamento a mano** dal contratto («Collega un rinnovo già registrato»): contratti
  dello stesso fabbisogno, senza predecessore, che iniziano dopo. **Scollega dal
  predecessore** per correggere un collegamento sbagliato. Entrambi nello storico.

## F9.2 — Estensione all'ufficio ICTDINN

Rev02: realizzata (v1.5.0). Rev01: risposte di Pietro del 02/10/2026.

**Realizzato, con le scelte da confermare**
- Cluster al posto dell'area; conto con il suo cluster (vuoto finché non si carica la
  struttura, segnalato `CONTO_SENZA_CLUSTER`); voce con conto di un altro cluster bloccata
  nel form e segnalata nell'import (`CONTO_ALTRO_CLUSTER`).
- Natura e WBS per voce (posizioni separate, mai percentuali); CAPEX ⇔ WBS; finanziato =
  WBS a progetto; natura, conto e WBS dei rinnovi sulla voce.
- Permessi per cluster: Admin tutto; Editor solo i fabbisogni dei cluster assegnati (o TUTTI);
  Reader in lettura. **Transizione**: finché non c'è alcuna assegnazione, gli Editor
  modificano tutto. Spostare o accorpare: le destinazioni sono solo nei propri cluster.
- Assegnazioni per nome utente di dominio, anche prima del primo accesso; tolte = archiviate
  (nessuna cancellazione fisica).
- Visibilità: cruscotto, elenchi, budget, piano ordini e Spese per WBS partono dai propri
  cluster; «Tutti i cluster» o un cluster a scelta dalla tendina (`?area=miei|tutti|IT`). Chi
  non ha cluster assegnati vede tutto.
- Import: contratti solo nei propri cluster; date di emissione solo sui contratti dei propri
  cluster (`FUORI_CLUSTER`); struttura solo Admin, dal modello approvato. Il foglio
  Responsabili, se compilato, è l'elenco completo.
- Budget CAPEX per WBS con il dettaglio per conto (pagina ed export, foglio «CAPEX per WBS e
  conto»); WBS a progetto fuori dai budget dei cluster salvo filtro.
- «Spese per WBS»: elenco (WBS dei propri cluster e tutte quelle a progetto) e dettaglio con
  contratti e importi anno per anno, solo contratti registrati, nella vista e al livello
  scelti; export Excel.
- Nome: "Registro contratti ICTDINN" (interfaccia, README, RUNBOOK).

**Nome e aree**
- L'applicazione diventa "Registro contratti ICTDINN". Repository, cartella sul server e gruppi
  AD restano gli stessi.
- Aree: IT, TLC, OT, Sicurezza fisica, Innovazione.

**Cluster**
- Il cluster è un'area che raggruppa più conti: tabella di configurazione con nome e
  responsabili. Ogni conto appartiene a un solo cluster (campo obbligatorio sul conto).
- Il fabbisogno ha un cluster; una voce con un conto di un altro cluster è bloccata nel form e
  segnalata nell'import.
- IT e TLC sono due cluster con lo stesso responsabile e in pratica lo stesso budget: i filtri
  accettano più cluster, con il default "i miei cluster" che li mostra insieme.

**WBS**
- Tabella unica con due tipi:
  - WBS di cluster: CAPEX "generico" del cluster, nel suo budget CAPEX;
  - WBS a progetto (es. nuovi dissalatori): fuori dai budget dei cluster, contratti registrati.
- CAPEX ⇔ WBS obbligatoria sul contratto; OPEX ⇔ nessuna WBS.
- "Finanziato" coincide con "WBS a progetto": il campo finanziamento si ricava dal tipo di WBS.
  La tabella Progetti attuale confluisce nelle WBS a progetto.
- Il campo WBS a testo libero sulla voce si elimina; i valori presenti vanno in un report.

**Budget**
- OPEX per cluster e conto; CAPEX per cluster e WBS di cluster, con il dettaglio per conto (come
  lo legge il Controllo di gestione).
- Pagina "Spese per WBS": per una WBS (anche a progetto) i contratti e il fatturato anno per
  anno.

**Permessi**
- Admin: tutto. Editor: modifica solo i fabbisogni e i contratti dei propri cluster; un Editor
  può essere abilitato a tutti i cluster (addetto amministrativo). Reader: legge tutto.
- Assegnazione dei cluster agli utenti nell'app (pagina Admin), non con gruppi AD.
- Visibilità: ogni utente vede di default solo i propri cluster; gli altri solo su richiesta
  (filtro "tutti i cluster"), in lettura.
- Fornitori in comune, modificabili da ogni Editor. Spostare o accorpare tra cluster diversi
  richiede il permesso su entrambi.

- Piano ordini: di default solo i propri cluster, come le altre viste.
- Import: gli Editor importano contratti e date solo nei propri cluster; l'import della
  struttura (cluster, responsabili, conti, WBS) è solo Admin, con il modello
  `2026.10.02_PFE_Modello_import_struttura_ICTDINN_Rev00` (fogli Cluster, Responsabili,
  Conti, WBS), accettato da Pietro.

**Quota CAPEX e quota OPEX nello stesso contratto (nota del 02/10/2026, da decidere)**
- Proposta: natura e WBS diventano attributi della voce (in SAP ogni posizione ha la sua
  imputazione: centro di costo o WBS). La natura del contratto si ricava: OPEX, CAPEX o mista.
- Budget: ogni voce va nella sezione della sua natura. Piano ordini: un previsto misto mostra
  le due quote.
- Natura e conto dei rinnovi (F8) passano dalla voce, perché il cambio CAPEX → OPEX può
  riguardare solo alcune voci; sul fabbisogno restano solo per il previsto manuale.

**Un contratto che rinnova più contratti (nota del 02/10/2026, da decidere; F9.3)**
- Caso: SIM voce e SIM M2M accorpati in un unico contratto nuovo, con un unico fabbisogno.
- Realizzato in F9.3 (sotto).

**Da avere prima di iniziare**
- Elenco iniziale dei cluster, dei conti e delle WBS di ciascun cluster, nel modello (dati
  reali: si caricano sul server dall'import, non nel repository).

## F9.3 — Un contratto che rinnova più contratti

Rev00: realizzata (v1.5.0). Caso numerico: TC-12 (SIM voce e SIM M2M).

- Il rinnovo principale resta il predecessore; gli altri contratti sostituiti «confluiscono»
  nel contratto nuovo (campo `confluito_in`). Ogni contratto ha al massimo un successore: o è
  il predecessore di uno, o confluisce in uno.
- Si confluisce solo in un contratto dello stesso fabbisogno (prima «Accorpa in…») che inizia
  dopo il contratto confluito.
- Effetti: i contratti confluiti non vanno in alert e i rinnovi previsti partono solo dal
  contratto nuovo; la loro pratica passa a «Contratto attivo».
- «Registra rinnovo» chiede quali altri contratti del fabbisogno il nuovo sostituisce.
- Scheda Rinnovi del contratto: «Sostituisce anche» (elenco, con «Togli») e, sul contratto
  confluito, «Confluito in …» con «Togli il collegamento»; dal menu «Sostituisce anche altri
  contratti» per collegarli dopo.
- Spostare un contratto confluito (o in cui altri confluiscono) è rifiutato: prima si toglie
  il collegamento. I doppioni passano la confluenza al contratto tenuto.

## F9.4 — SPEC Rev06, chiusura delle scelte F9.2, TC-13

Rev00: richiesta di Pietro del 05/10/2026.

- **SPEC Rev06** (bozza da approvare): allineamento a F8–F9.3.
- **Scelte F9.2 chiuse**:
  - la transizione finisce per sempre alla prima assegnazione registrata: archiviare tutte le
    assegnazioni non ridà agli Editor i permessi su tutti i cluster;
  - cluster obbligatorio sul conto in amministrazione; caricata la struttura (almeno un conto
    con cluster), una voce non può usare un conto senza cluster e l'import dei contratti lo
    segnala (`CONTO_SENZA_CLUSTER`); l'import del piano dei conti legge la colonna `cluster`.
- **TC-13**: natura per voce (contratto con una voce OPEX e una CAPEX).

## F9.5 — Stampa dei report e spese senza contratto

Rev00: realizzata (v1.5.0). Richiesta di Pietro del 05/10/2026. Caso numerico: TC-14.

- **Stampa**: A4 orizzontale; dimensioni di base sull'elemento `html` (Bootstrap usa i rem);
  tabelle a tutta pagina, testo a capo, nessuna colonna tagliata; intestazioni ripetute su ogni
  pagina, totali una volta sola in fondo; titoli non separati dalla tabella. Test nel browser
  con il media di stampa.
- **Spesa ricorrente senza contratto** sul fabbisogno (SPEC §5.6): fornitore, importo,
  periodicità, prima spesa e fine facoltativa.
  - entra nel budget come consolidato, nelle tre viste, filtrabile per fornitore;
  - solo promemoria 🟡 nel cruscotto, prima della prossima spesa;
  - fuori dal piano ordini, nessun contratto previsto;
  - scheda del fabbisogno con prossime e ultime spese.

## F9.5.1 — Rinnovo senza contratto

Rev00: realizzata (v1.5.1). Richiesta di Pietro del 05/10/2026. Caso numerico: TC-14.

- La spesa senza contratto si può registrare su un fabbisogno con contratti, se tutti
  finiscono prima della prima spesa; prima andava creato un fabbisogno nuovo.
- La spesa fa da successore dell'ultimo contratto: niente alert, niente previsti; il
  contratto resta nello storico e nel budget dei suoi anni. Nota sulla pagina del contratto.

## F9.5.3 — Scorciatoie per la spesa senza contratto

Rev00: realizzata. Richiesta di Pietro del 05/10/2026: registrare una spesa senza contratto
senza passare dal form completo del fabbisogno.

- «Nuova spesa senza contratto» nell'elenco dei fabbisogni: crea il fabbisogno con i soli
  dati necessari (descrizione, cluster, categoria, spesa, classificazione).
- «Rinnova senza contratto» sulla pagina del contratto senza successore: form della sola
  spesa, precompilato (fornitore, prima spesa il giorno dopo la fine, periodicità del piano
  di fatturazione, natura/conto/WBS della prima voce); aggiorna il fabbisogno.
- «Spesa senza contratto» / «Modifica spesa» sulla pagina del fabbisogno.
- Le scorciatoie mettono il fabbisogno «senza contratto» con decisione «Rinnovare» e tolgono
  l'eventuale previsto manuale. Valgono le regole di SPEC §4 e §5.6 (contratti finiti prima
  della prima spesa).
- Tolto l'esempio dal titolo della sezione nel form del fabbisogno.

## F9.5.2 — PDF dei report generati dal server

Rev00: realizzata (v1.5.1). Richiesta di Pietro del 05/10/2026: la stampa dal browser usciva
in A4 verticale con la pagina ruotata e parti mancanti (dialogo di stampa di macOS, che ignora
`@page`).

- «Scarica PDF» su budget, piano ordini e spese per WBS al posto di «Stampa / PDF»: il PDF lo
  genera il server con WeasyPrint, uguale su ogni browser e sistema operativo.
- A4 orizzontale; intestazione con logo, titolo e numero di pagina su ogni pagina; piede con i
  filtri, data e utente; intestazioni delle colonne ripetute, totali una volta sola.
- Budget: OPEX e CAPEX su pagine separate; «PDF con il dettaglio delle voci» a richiesta.
- Template dedicati (`reports/templates/reports/pdf/`, `static/css/pdf.css`), senza Bootstrap;
  solo file locali di `static/` (nessuna risorsa esterna). Logo in PNG per il PDF.
- La stampa dal browser (Ctrl+P) resta, con il CSS di stampa di F9.5.
