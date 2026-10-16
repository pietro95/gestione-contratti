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

**Accettazione:** installazione da zero su una VM pulita seguendo solo il runbook (verifica manuale del responsabile del rilascio).

## F7 — Interfaccia grafica e identità aziendale

Rev01: scelte confermate dal responsabile del progetto (logo e linee guida tipografiche in `docs/design/`).

Obiettivo: rendere l'applicazione usabile ogni giorno da chi non l'ha sviluppata. Le funzioni
restano quelle di F4–F5; cambiano struttura delle pagine, gerarchia visiva e flussi.

**Identità**
- Logo aziendale nell'intestazione, nella pagina di login, nei PDF stampati e come favicon.
  File dell'identità visiva disponibili in `static/img/logo/` (colore, bianco, nero).
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
- revisione del responsabile del progetto sugli screenshot delle pagine principali, prima e dopo.

## F8 — Correzioni del modello dopo il primo uso

Rev00: note raccolte dal responsabile del progetto dopo il primo uso in produzione (v1.0.2), proposte approvate.

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
- Responsabile del progetto: data di emissione caricata da SAP sui contratti reali, un accorpamento e uno
  spostamento sui dati reali, budget OPEX e CAPEX confrontati con le attese.

## F9.1 — Import dall'interfaccia

Rev00: richiesta del responsabile del progetto del 02/10/2026, proposte approvate.

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
reimportabili, flusso nel browser); L'operatore autorizzato carica dal web le date di emissione estratte da SAP.

## F9.1.1 — Correzioni dopo il primo uso dell'import web

Rev00: segnalazioni raccolte dal responsabile del progetto del 02/10/2026.

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

Rev00: segnalazione raccolta dal responsabile del progetto del 02/10/2026 (contratto 01/03/2025–28/02/2026 rinnovato dal
01/01/2026 nello stesso fabbisogno, in rosso «Senza rinnovo» e senza modo di collegarli).

- **Proposta di collegamento**: il rinnovo può iniziare prima della scadenza del
  predecessore. Si propone il contratto senza predecessore che inizia dopo e finisce dopo,
  con l'inizio più vicino al giorno dopo la fine; i periodi sovrapposti sono segnalati. Un
  contratto parallelo che finisce prima non è un rinnovo.
- **Collegamento a mano** dal contratto («Collega un rinnovo già registrato»): contratti
  dello stesso fabbisogno, senza predecessore, che iniziano dopo. **Scollega dal
  predecessore** per correggere un collegamento sbagliato. Entrambi nello storico.

## F9.2 — Estensione all'ufficio ICTDINN

Rev02: realizzata (v1.5.0). Rev01: risposte del responsabile del progetto del 02/10/2026.

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
  `GestioneContratti_ModelloImport_Struttura` (fogli Cluster, Responsabili,
  Conti, WBS), accettato dal responsabile del progetto.

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

Rev00: richiesta del responsabile del progetto del 05/10/2026.

- **SPEC Rev06** (bozza da approvare): allineamento a F8–F9.3.
- **Scelte F9.2 chiuse**:
  - la transizione finisce per sempre alla prima assegnazione registrata: archiviare tutte le
    assegnazioni non ridà agli Editor i permessi su tutti i cluster;
  - cluster obbligatorio sul conto in amministrazione; caricata la struttura (almeno un conto
    con cluster), una voce non può usare un conto senza cluster e l'import dei contratti lo
    segnala (`CONTO_SENZA_CLUSTER`); l'import del piano dei conti legge la colonna `cluster`.
- **TC-13**: natura per voce (contratto con una voce OPEX e una CAPEX).

## F9.5 — Stampa dei report e spese senza contratto

Rev00: realizzata (v1.5.0). Richiesta del responsabile del progetto del 05/10/2026. Caso numerico: TC-14.

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

Rev00: realizzata (v1.5.1). Richiesta del responsabile del progetto del 05/10/2026. Caso numerico: TC-14.

- La spesa senza contratto si può registrare su un fabbisogno con contratti, se tutti
  finiscono prima della prima spesa; prima andava creato un fabbisogno nuovo.
- La spesa fa da successore dell'ultimo contratto: niente alert, niente previsti; il
  contratto resta nello storico e nel budget dei suoi anni. Nota sulla pagina del contratto.

## F9.5.3 — Scorciatoie per la spesa senza contratto

Rev00: realizzata (v1.5.2). Richiesta del responsabile del progetto del 05/10/2026: registrare una spesa senza contratto
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

Rev00: realizzata (v1.5.1). Richiesta del responsabile del progetto del 05/10/2026: la stampa dal browser usciva
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

## F9.5.4 — Più cluster nel filtro, cluster in evidenza nel PDF

Rev00: realizzata (v1.5.2). Richiesta del responsabile del progetto del 05/10/2026.

- Il filtro «Cluster» (budget, piano ordini, spese per WBS, contratti, fabbisogni, cruscotto,
  piani da verificare) accetta più cluster insieme (`?area=IT&area=TLC`). «I miei cluster» e
  «Tutti i cluster» restano e escludono le altre scelte.
- PDF ed export XLSX dicono sempre quali cluster comprendono, anche «Cluster: tutti». Nel
  PDF: i filtri in evidenza sotto il titolo, il cluster nella testata di ogni pagina e nel
  nome del file (`…_Budget_2026_OPEX_IT-TLC.pdf`).

## F9.5.5 — Rinnovo senza contratto come anello della catena

Rev00: realizzata. Richiesta e decisioni del responsabile del progetto del 05/10/2026 (SPEC Rev09, TC-14):
anche senza contratto ogni rinnovo va gestito con scadenza e alert.

- Tolta la spesa ricorrente sul fabbisogno (F9.5, F9.5.1): non gestiva la scadenza, il
  rinnovo si dava per scontato. I dati eventualmente inseriti restano nelle note del
  fabbisogno (migration 0022).
- Contratto segnato **«senza contratto»**: stesse scadenze, data limite, pratica, alert,
  previsti e budget di un contratto; fuori dal piano ordini, anche i suoi previsti.
- «Rinnova senza contratto» sulla pagina del contratto senza successore: form del rinnovo
  senza i dati del documento contrattuale, inizio il giorno dopo la fine, durata 12 mesi.
- «Nuovo senza contratto» nell'elenco dei contratti e nella pagina del fabbisogno.
- Etichetta «senza contratto» in elenchi, cruscotto, pagina del contratto, budget (anche PDF
  ed export).
- Tolte le scorciatoie della spesa di F9.5.3 (v1.5.2), sostituite da quelle qui sopra.

## F10 — Connettore MCP in sola lettura

Rev02: realizzata. Decisioni del responsabile del progetto del 05/10/2026 (SPEC Rev10, `docs/SPEC_MCP.md`
Rev03). Rilasciata con F10.1 nella v1.7.0; in produzione dal 07/10/2026, prova D8 superata
(SPEC_MCP Rev07). Claude interroga il registro con gli stessi
numeri dell'interfaccia.

**Parte 1, realizzata**: OAuth con login interno, `/mcp`, container `mcp` con
utente PostgreSQL limitato, registro e limite, tool `riferimenti`, `cerca`, `scadenze`,
`crea_client_mcp`, `verifica_mcp.sh`, RUNBOOK §12.
**Parte 2, realizzata**: gli altri otto tool (`contratto`, `fabbisogno`,
`fornitore`, `scadenzario`, `budget`, `piano_ordini`, `spese_wbs`, `piani_da_verificare`),
`versione` negli oggetti letti (per F10.1), tool per ruolo come le pagine, pagina «Connettore
MCP» dell'utente con revoca, limite di dimensione della risposta.

- **Primo passo, prima del resto**: prova con claude.ai di un flusso OAuth con la pagina di
  autorizzazione sull'host interno e i metadati e il token endpoint sull'host pubblico
  (SPEC_MCP §2.1). Esito: accettato (D8, 07/10/2026).
- App `mcp/`: `POST /mcp` Streamable HTTP stateless, solo JSON; `initialize`, `ping`,
  `tools/list`, `tools/call`. Undici tool di sola lettura (SPEC_MCP §5), con importi come
  stringhe decimali e date ISO; logica oggi nelle viste (`cerca`, fornitore, catena del
  contratto) spostata in `selettori` e riusata dalle viste.
- OAuth 2.1 con `django-oauth-toolkit`: PKCE S256, client pre-registrati (app Claude e
  Claude Code), access token 1 ora, refresh ruotato, refresh rifiutato senza login negli
  ultimi 7 giorni (durate in `Parametro`); metadati RFC 9728 e RFC 8414.
- Pagina «Connettore MCP» per l'utente (collegamenti, ultimo uso, revoca); revoca da Admin.
- Registro delle chiamate e dei token (12 mesi), limiti di frequenza e dimensione.
- Container `mcp` con URLconf ridotta ai quattro endpoint pubblici, utente PostgreSQL con
  sola lettura sul dominio; script di verifica esterna in `deploy/`.
- RUNBOOK: host pubblico su NPM (certificato pubblico, Access List `160.79.104.0/21` e rete
  interna, percorsi ammessi), DNS split horizon, client OAuth, aggiunta del connettore
  nell'organizzazione Claude, collegamento, revoca.

Criteri di accettazione: SPEC_MCP §7. In particolare: client MCP reale (SDK, solo test) su
tutti i tool; flusso OAuth completo nei test, rotazione e regola dei 7 giorni; `budget` e
`piano_ordini` uguali al centesimo alla vista web e all'export XLSX; 401/403 per token non
validi e utenti senza ruolo; oggetti fuori dai cluster visibili «non trovati»; URLconf del
container `mcp` limitata ai quattro endpoint; prova in produzione da claude.ai e Claude Code.

## F10.1 — Scrittura dal connettore MCP

Rev02: realizzata, rilasciata nella v1.7.0 insieme a F10. **Parte 1**: infrastruttura (scope e consenso, anteprima in
transazione annullata con modifiche ed effetti, conferma con versioni, idempotenza,
interruttore, storia `MCP …`, privilegi PostgreSQL) e tool dei gruppi A, B, D, `archivia` e
`ripristina`. **Parte 2**: gruppo C (`crea_contratto` con voci, piani e quote,
`modifica_contratto`, `registra_rinnovo` anche senza contratto e con contratti sostituiti,
`registra_proroga`, `crea_voce`, `modifica_voce`); logica di voce, rinnovo e proroga spostata
dalle viste ai servizi; TC-12 e TC-14 ricostruiti via MCP. Il gruppo E arriva con F11.

Decisione del responsabile del progetto del 05/10/2026 (SPEC Rev12,
`docs/SPEC_MCP.md` Rev05 §8): perimetro gruppi A–E (D11), conferma nella chat (D12), nessun limite
giornaliero (D13).

- Scope OAuth `registro.scrittura`, concesso a parte nel consenso, solo Admin ed Editor.
- Due passi: ogni tool di scrittura restituisce l'anteprima (modifiche, effetti calcolati dal
  motore, errori) e un `id_operazione`; scrive solo `conferma_operazione`. Versione degli
  oggetti per la concorrenza, conferma idempotente, transazione unica.
- Tool dei gruppi A (pratica, rate, scadenzario), B (fornitori, fabbisogni), C (contratti,
  rinnovi, proroghe, voci, archiviazione), D (catena) di SPEC_MCP §8.2; gruppo E con F11.
  Regole oggi nelle viste spostate nei form e nei servizi, usate da viste e tool.
- Interruttore `mcp_scrittura_attiva` in `Parametro`; storia con motivo
  `MCP …`; privilegi PostgreSQL del container `mcp` senza `DELETE` fuori da rate e token.

Criteri di accettazione: SPEC_MCP §8.4. In particolare: 403 per Reader e per cluster non
propri su ogni tool; l'anteprima non scrive niente; equivalenza con la vista web (stesso stato
del database, stessi errori); conferme scadute, ripetute o su oggetti cambiati gestite;
TC-12 e TC-14 ricostruiti via MCP.

## F11 — Release 2.0: processo d'acquisto (RDA → esecuzione → chiusura)

Rev01: bozza da approvare. Decisioni del responsabile del progetto del 05/10/2026 (SPEC Rev11): solo ICTDINN; le
forniture una tantum entrano come contratti; stati della pratica ricavati dalla RDA;
inserimento a mano e import XLSX, nessun collegamento a SAP; CUP sì, basket del masterplan
no. Decisioni del 07/10/2026 (SPEC Rev13): flusso referente → addetto amministrativo con la
richiesta di RDA e la scheda SAP; funzione «Amministrazione acquisti» assegnata per utente,
nessun nuovo ruolo AD; i campi da SAP li scrive anche il referente; più posizioni per RDA;
nessuna mail dal portale, solo il testo da copiare; RDA e contratti inseriti a mano, scollegati,
collegabili dopo. Decisioni del 07/10/2026 (seconda parte): la richiesta di RDA parte dal
fabbisogno ed è impostata da sola come rinnovo del contratto in scadenza; tabelle dei
richiedenti SAP (con un predefinito), dei gruppi merci e dei gruppi acquisti caricate da Excel;
chiusura del contratto per addetto e referente; i campi SAP della fattura arriveranno più
avanti. Casi numerici: TC-15, TC-16, TC-17. Uscita prevista come `v2.0.0` alla fine
di F11.4; le sotto-fasi si possono rilasciare prima come versioni 1.x successive a quella di
F10.

### F11.1 — Modello e motore

Stato: realizzata (PR #33; nessuna interfaccia nuova oltre all'amministrazione e all'import
delle tabelle SAP).

- Modelli (SPEC §4): `RichiestaAcquisto` con posizioni (`PosizioneRDA`) e storico
  (invio, rimando, annullamento); `DocumentoEsecuzione` (con fattura facoltativa), `Fattura`;
  sul contratto RDA d'origine, una tantum, CUP, RUP, percorso dei documenti, chiusura (data,
  utente); nome breve del fornitore. Storia delle modifiche, nessuna cancellazione, vincoli
  nel database (RDA mai legata sia a contratto sia a fabbisogno; una tantum senza
  predecessore, successore e confluenze; fattura unica per fornitore e numero; quantità e
  importi ≥ 0).
- Configurazione: richiedenti SAP, gruppi merci, gruppi acquisti (ciascuno con al più un
  predefinito), cartella base delle RDA per cluster, funzione «Amministrazione acquisti» per utente (anche
  nell'import della struttura: rinviato, il modello della struttura è approvato e non si
  modifica senza approvazione formale; per ora dall'amministrazione); parametri «RDA ferma» (30 giorni) e «fattura ferma» (15
  giorni), provvisori.
- Data migration: il n. RDA dei contratti diventa una RDA collegata (SPEC §7).
- Import delle tabelle SAP da Excel (richiedenti, gruppi merci, gruppi acquisti), solo Admin,
  con anteprima, conferma e registro (SPEC §7).
- Motore puro: fase della RDA, scopo e proposte della richiesta dal fabbisogno (rinnovo dal
  contratto in scadenza e dal suo previsto, primo acquisto, acquisto aggiuntivo), stato della pratica ricavato (massimo tra passaggi e RDA),
  RDA e fatture ferme, proposte della scheda SAP (intestazione, cartella, testo della
  richiesta), residuo, avanzamento, motivi «da chiudere», anomalie (SPEC §5.7–§5.9); una
  tantum esclusa da alert, previsti, catena e piano ordini.
- Admin per le nuove entità.

**Accettazione:** TC-15, TC-16 e TC-17 come test parametrizzati; import delle tabelle SAP
idempotente, con errore per più predefiniti o codici doppi; TC-01 … TC-14 invariati e
verdi; `makemigrations --check` pulito.

### F11.2 — Richiesta di RDA e scheda SAP

Stato: realizzata, in revisione. Oltre a quanto previsto: elenco «Richieste di RDA» nel menu
(filtri per cluster, fase, «le mie»), in attesa dei cruscotti di F11.4. Il testo della
richiesta si vede nella scheda SAP dopo il primo salvataggio (anche in bozza), non nel form.

- Referente: «Nuova richiesta di RDA» dalla pagina del fabbisogno (e dal contratto, che porta al
  suo fabbisogno); scopo impostato da solo (rinnovo del contratto in scadenza o primo
  acquisto), con la scelta «acquisto aggiuntivo»; form con posizioni precompilate (SPEC §5.9) e
  anteprima del testo; «Invia all'addetto»; correzione dopo il rimando.
- Addetto (e referente): scheda SAP con «Copia» per campo e «Copia testo della richiesta»;
  campi da SAP (numero, inserimento, rilascio); «Rimanda al referente» con nota; «Annulla».
- RDA registrata a mano (già in SAP), senza legami; «Collega» RDA ↔ fabbisogno, contratto in
  scadenza, contratto generato, da entrambi i lati; proposte di collegamento per n. RDA.
- «Registra contratto da RDA» (rinnovo o una tantum), precompilato dalle posizioni, con la
  differenza dall'importo della RDA.
- Pratica: il form registra a mano solo `Offerta richiesta` e `Offerta ricevuta`; lo stato
  ricavato mostra la RDA che lo determina.
- Ricerca globale anche per numero RDA.

**Accettazione:** test di permesso per ogni vista (Reader → 403, Editor solo nei propri
cluster, referente non Editor del cluster → 403); test nel browser del flusso «richiesta →
invio → rimando → invio → campi SAP → contratto» e accessibilità (axe-core); testo copiato
uguale a TC-17.

### F11.3 — Esecuzione e fatture

- Contratto: scheda «Esecuzione» (documenti, fatture, abbinamento alle rate, residuo,
  avanzamento, anomalie); «Chiudi» / «Annulla chiusura» in finestra modale; etichetta
  «una tantum».
- Fattura (SPEC Rev14–Rev15): registrazione; importo del documento e valore base
  prelevato dal contratto, oneri e bollo; elenco «Fatture da prendere in carico» visibile a tutti,
  referente proposto (ultima fattura, referente del contratto) con filtro «proposte a me»,
  presa in carico (singola o su più fatture selezionate), «Assegna ai referenti proposti»,
  lascia e riassegna; assegnazione al
  contratto (con proposta); convalida
  del referente (esito, nota, bloccata fino al); RdC → MAP (servizi) o MIGO (forniture) →
  trasferimento per il pagamento; fuori registro (anche su più fatture); «Le mie fatture»; scheda SAP della fattura per passo,
  indicazioni per la validazione e **commento per PAC** con «Copia».
- **Import settimanale delle fatture** dall'estrazione SAP annotata (SPEC §7, TC-18), con
  anteprima, conferma, registro, report delle anomalie.
- Ricerca globale anche per ODA e numero di fattura.

**Accettazione:** test di permesso; test nel browser del flusso «import → presa in carico
multipla → assegnazione →
convalida → RdC → MAP/MIGO → trasferimento → chiusura»; TC-16, TC-18.

### F11.4 — Cruscotti, viste e import

- **Cruscotto dell'addetto** (funzione «Amministrazione acquisti»): RDA da processare per
  azione (da inserire, da sollecitare per il rilascio, da sollecitare al Procurement), fatture
  da lavorare, contratti da chiudere; ferme in evidenza.
- **Le mie RDA** per il referente, anche come scheda del cruscotto.
- **Stato delle RDA** (tutti i ruoli), **Contratti da chiudere**, **Anomalie dell'esecuzione**;
  filtri, export XLSX e PDF.
- Modello XLSX dell'esecuzione (RDA con posizioni, documenti, fatture) nell'import
  dall'interfaccia, con anteprima, conferma, registro e report delle anomalie (SPEC §7).
- Import una tantum del Riepilogo RDA Ordini dal 01/04/2025, solo ICTDINN (SPEC §7).
- Fixture anonimizzate con la stessa struttura del Riepilogo (celle unite, celle con più
  valori, stati scritti in modi diversi, righe fuori perimetro).

**Accettazione:** i totali delle viste sulle fixture coincidono con il motore (test); export
e PDF con i filtri in evidenza come in F9.5.4; import completo della fixture senza eccezioni,
report con tutte le anomalie note (SPEC §2.3), idempotenza.

### F11.5 — Competenza delle fatture e stanziamenti

Approvata dal responsabile del progetto il 16/10/2026 (SPEC Rev21 e Rev22, decisioni del 15/10/2026).

- Fattura: periodo di competenza (dal, al), obbligatorio con il valore base (form, servizio e
  strumento `importi_fattura`); anomalia `COMPETENZA_MANCANTE` per le fatture importate senza.
- Stanziamento: nuova entità sulla voce (e sulla rata che sostituisce), registrato dalla
  scheda «Esecuzione» del contratto, chiuso dalla fattura o annullato; storico e admin.
- Budget: nuova vista «Fatturato e stanziato (competenza)», prima colonna e riferimento; la
  cassa per data fattura resta come confronto (SPEC §5.2, TC-20). Report, export e strumento
  `budget` del connettore la riportano.
- Criterio di accettazione: TC-20 verde; il Reader riceve 403 sulle viste dello stanziamento.
- (Rev22) Competenza di default delle fatture importate e registrate: il mese prima della data.
  Periodo salvato sulla rata alla generazione dello scadenzario (migration `0038`, ricavato al
  volo per le rate salvate prima). Stanziamento proposto dalle rate scadute senza fattura
  (parametro `stanziamento_giorni`, migration `0039`), con conferma singola o multipla e pagina
  «Stanziamenti» nei report. Connettore: `stanziamenti`, `registra_stanziamento`,
  `stanzia_rate`, `chiudi_stanziamento`, `annulla_stanziamento` (SPEC_MCP Rev09).
- Aperto: tolleranza definitiva dello stanziamento (SPEC §9).

## F12 — Connettore MCP per il processo d'acquisto

Rev00: bozza da approvare. Decisioni del responsabile del progetto del 07/10/2026 (`docs/SPEC_MCP.md` Rev08 §11,
D14–D17). Il connettore copre richieste di RDA, fatture, esecuzione e chiusura e le quattro
viste della release 2.0, con le regole di F10 (lettura) e F10.1 (anteprima e conferma).

### F12.1 — Lettura

- Tool `rda`, `elenco_rda`, `fattura`, `elenco_fatture`, `esecuzione`,
  `cruscotto_acquisti`, `contratti_da_chiudere`, `anomalie_esecuzione` (SPEC_MCP §11.2).
- Estensioni di `contratto`, `fabbisogno`, `cerca`, `riferimenti`.
- Nome dei referenti (D16), testi per SAP e PAC in campi propri (D17), testi del flusso in
  campi distinti.

**Accettazione:** SPEC_MCP §7 e §11.5; TC-15, TC-16, TC-17 (`testo_richiesta`), TC-18
(commento per PAC) via MCP; totali e conteggi uguali alla vista web e all'export XLSX.

### F12.2 — Scrittura

- Tool del gruppo E (SPEC_MCP §11.3): RDA, contratto dalla RDA, fatture, documenti di
  esecuzione, chiusura; tutto tranne gli import (D14).
- Operazioni su più fatture per presa in carico, fuori registro e assegnazione ai proposti,
  al massimo 50, con anteprima per fattura (D15).
- Anteprima con gli effetti: fase della RDA, stato della pratica, passo della fattura, fatturato
  e residuo, commento per PAC risultante, effetti di F10.1 per il contratto dalla RDA.

**Accettazione:** SPEC_MCP §8.4 e §11.5; per ogni tool Reader 403 ed equivalenza con
l'interfaccia; TC-18 ricostruito via MCP (presa in carico multipla, rifiuto «già in carico»,
convalida bloccata, commento per PAC).
