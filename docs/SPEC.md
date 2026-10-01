# Istruzioni di progetto — Registro contratti IT/TLC

Rev03 — 01/10/2026 — autore: Pietro Verro (IT Manager, Siciliacque S.p.A.)

Storico revisioni:
- Rev00 (30/09/2026): analisi e requisiti.
- Rev01 (30/09/2026): decisa la piattaforma (web app interna, autenticazione LDAP), aggiunti requisiti non funzionali (§8), casi di test in `docs/TEST_CASES.md`, regole per i dati nel repository.
- Rev02 (01/10/2026): decisioni prese durante F0, F1 e la preparazione di F2. Modello dati (§4): proroghe esercitate multiple, previsti manuali sul fabbisogno, stato pratica, modalità `Da verificare`, stima di consumo, data OdA, impianti e progetti, piano dei conti inserito a mano. Regole di calcolo (§5): aritmetica dei mesi a fine mese, data di fine con proroghe, tacito rinnovo negli alert, cassa solo per data fattura, quota variabile, SAL e consumo, ultimo periodo corto, adeguamento, impegno, rinnovi previsti, CAPEX senza ammortamento. Autenticazione (§8.1). Nuovo caso TC-10, TC-03 allineato alla regola di pagamento.
- Rev03 (01/10/2026): rinnovi previsti (§5.3): un solo contratto di partenza per fabbisogno; nei report di budget i previsti già conclusi prima dell'anno selezionato non entrano e il fabbisogno è segnalato come rinnovo mancante.

## 1. Obiettivo

Sostituire i due file Excel (`Contratti_IT.xlsx`, `Contratti_TLC.xlsx`) con un unico registro che:

1. tenga traccia di tutti i contratti dell'ufficio IT/TLC e della loro catena di rinnovi;
2. produca un budget annuale affidabile, distinguendo **impegno**, **cassa** e **competenza**;
3. produca per il Procurement la **previsione annuale degli ordini/procedure da avviare**, con data limite di avvio e importo stimato;
4. segnali in anticipo le scadenze, in funzione della procedura di affidamento e non di un preavviso fisso.

Utenti: IT Manager (owner, scrittura), collaboratori IT (scrittura), Procurement e Controllo di gestione (lettura + export).

## 2. Situazione attuale (as-is) e problemi rilevati

Struttura: una riga per ogni istanza contrattuale (ogni rinnovo = nuova riga), foglio Dashboard con conteggio alert e "Ipotesi di spesa per singolo anno" (min/max) calcolata con MAP/LAMBDA. IT: 66 righe; TLC: 18 righe + 5 in "Contratti_Finanziati" (fuori dashboard).

### 2.1 Difetti di modello

- **Nessun legame tra un contratto e il suo rinnovo.** "Licenze IBM Cognos" compare 3 volte (2024, 2025, 2026), "Manutenzione sito web" 3 volte: il collegamento è solo per somiglianza di descrizione. Senza questo legame non si può prevedere cosa rinnovare né confrontare i costi nel tempo.
- **"Stato" mescola tre cose diverse**: stato del contratto (Attivo, Scaduto), decisione (Rinnovare / Non rinnovare) e avanzamento della pratica (Offerta richiesta, RDA predisposta). "Rinnovato" sulla riga vecchia e "Attivo" sulla nuova descrivono lo stesso fatto due volte.
- **Il budget previsionale considera solo i contratti già firmati.** IT: 203 k€ nel 2026 e 52 k€ nel 2027. Il calo è falso, perché i rinnovi previsti non sono modellati. Per questo il file non serve al Procurement.
- **Il budget distribuisce tutto pro-rata sui mesi**, ignorando come e quando si paga. Esempio: AutoCAD LT 36 mesi, 21.990 € ("Spesa completamente liquidata nel 2023"), viene invece spalmato sul 2023–2026. Stesso dubbio su Sophos Intercept X (26 k€ su 36 mesi).
- **Bug di calcolo nel pro-rata**: la formula conta i mesi di calendario toccati, estremi inclusi. Un contratto di 12 mesi che inizia il 21/12 tocca 13 mesi e quindi viene contato per il 108%. Effetto misurato: IT +11,3 k€ su 515 k€ (32 righe errate), TLC +1,6 k€ (3 righe).
- **Un ordine può avere più voci, ma il file non lo gestisce**: 7300006015 (CIG B77FEA122A) ha 4 righe OVH, 5800005403 ha 2 righe Lenovo. Oggi si duplicano numero ordine e CIG.
- **Le variabili di classificazione sono sparse tra fogli e colonne**: "Contratti_Finanziati" e "Contratti Dissalatori" sono fogli separati; "Codice conto" e "Nuovo codice conto da 01/01/26" sono due colonne.
- **Min/Max senza stima**: "Corrispettivo Extra" è un massimale (quota a consumo). Il budget oscilla tra minimo e massimo senza una stima "probabile".

### 2.2 Qualità dei dati (da bonificare in migrazione)

- Caratteri invisibili (BOM `U+FEFF`) nei campi Contratto e CIG di almeno 6 righe (Ricca IT, Lenovo, Veeam, EDOC).
- Valori nulli scritti in 5 modi diversi: `n/a`, `N/A`, `n/d`, vuoto, `0`.
- Codici sospetti: CIG `B941B595B` (9 caratteri, il CIG ne ha 10); ordine `580006042` (9 cifre, gli altri ne hanno 10); conto `62700` (5 cifre).
- Formula del Corrispettivo Massimo sovrascritta a mano in 3 righe del file IT (J30, J39, J55). Nella riga "Reperibilità ICT" 2025 il valore è anche incoerente (6.000 + 0 = 20.000).
- Righe a valore 0 che rappresentano contratti reali (SR650 V2 PROD, ponte radio Mandarin, DNS) e falsano il budget.
- "Fibra ottica dissalatore di Trapani" senza data di attivazione, quindi `#VALUE!`.
- Stesso numero ordine e stesso CIG su due annualità diverse (5800005193, 2025 e 2026): da verificare se è un ordine pluriennale o un errore.
- L'anagrafica fornitori è duplicata e diverge tra i due file: Ricca IT ha il codice in IT ma non in TLC, Powermedia compare due volte in TLC. Il codice 139952 è assegnato a 4 fornitori diversi (Damper, Ergon, One Team, Powermedia): da verificare.

## 3. Principi di progettazione

1. **Un solo registro** per IT e TLC. Area, finanziamento e impianto sono attributi, non fogli.
2. **Separare il fabbisogno dal contratto.** Il *Fabbisogno* è il servizio ricorrente, che vive per anni (es. "Licenze IBM Cognos"). Il *Contratto* è la singola istanza con OdA, CIG, date e importi. Un rinnovo è un nuovo contratto sullo stesso fabbisogno.
3. **Il budget nasce dal piano di fatturazione**, non da una divisione per mesi.
4. **Le date derivate si calcolano, le date decise si salvano.** Scadenza, data limite e alert sono sempre calcolati.
5. **SAP resta il riferimento** per OdA, RDA, codici fornitore e conti COGE. Il registro li memorizza come chiavi esterne e non li reinventa. L'integrazione iniziale è un import/export, non un'interfaccia online.
6. **Soglie normative, lead time e aliquote sono parametri configurabili**, mai valori fissi nel codice.
7. **Traccia completa delle modifiche** (chi, quando, valore prima e dopo). Nessuna cancellazione fisica.

## 4. Modello dati (logico)

**Fornitore**: ragione sociale, P.IVA, codice SAP, note.
- La P.IVA è facoltativa e, se presente, univoca.
- Il codice SAP non è univoco: nei file attuali lo stesso codice è assegnato a più fornitori (§2.2). Il sistema lo ammette e lo segnala.

**Fabbisogno** (servizio ricorrente):
- descrizione, area (IT/TLC), categoria (licenze SW, manutenzione HW, connettività, servizi professionali, noleggio, ecc.);
  - l'area è un elenco fisso (IT, TLC);
  - la categoria è una tabella di configurazione, modificabile dall'amministrazione;
- impianto (facoltativo, da tabella; es. un dissalatore);
- referente: testo libero, più un collegamento facoltativo all'utente dell'applicazione;
- decisione di continuità: `Rinnovare` / `Da valutare` / `Sostituire` / `Dismettere`;
- stima del prossimo importo e note;
- **previsto manuale** (solo per un fabbisogno nuovo, senza contratti): data di avvio prevista, durata, procedura presunta, modalità e periodicità di fatturazione previste. Sono dati decisi e si salvano; il contratto previsto che ne deriva si calcola (§5.3). Avvio e durata vanno indicati insieme.

**Contratto** (istanza):
- chiave: fabbisogno, contratto predecessore (dello stesso fabbisogno; un contratto ha al massimo un successore);
- riferimenti: fornitore, n. OdA SAP, data di emissione dell'OdA, n. RDA, CIG. I codici si conservano come arrivano; le anomalie di formato vanno nel report d'import (§7);
- procedura (affidamento diretto, MEPA/ODA, RDO, negoziata, aperta, adesione a convenzione/AQ), con override del lead time sul singolo contratto;
- date: data stipula, data inizio, durata in mesi (la data di fine si calcola, con override ammesso). La data di inizio può mancare solo nei dati importati: il contratto resta escluso dai calcoli e segnalato (TC-08);
- opzioni di rinnovo/proroga previste e non ancora esercitate: zero o più, ciascuna con tipo (rinnovo o proroga), mesi e importo;
- proroghe esercitate: zero o più (vedi **Proroga**);
- tacito rinnovo con termine di disdetta in giorni (obbligatorio se c'è tacito rinnovo);
- classificazione: finanziamento (ordinario / finanziato), con progetto obbligatorio se e solo se finanziato; natura (OPEX/CAPEX);
- documenti: link al protocollo o a SharePoint, senza caricare file.

**Proroga** (0..n per contratto): proroga effettivamente esercitata, anche più volte sullo stesso contratto.
- data dell'atto, nuova data di fine, riferimento (protocollo, OdA integrativo o atto aggiuntivo), note;
- l'eventuale importo aggiuntivo non sta sulla proroga ma in una o più **voci di contratto** collegate alla proroga, ciascuna con il proprio piano di fatturazione. Una proroga senza importo è ammessa.

**Progetto** (tabella): codice WBS e descrizione, per i contratti finanziati.

**Impianto** (tabella): nome e note.

**Voce di contratto** (1..n per contratto):
- descrizione;
- proroga di riferimento, se la voce è l'importo di una proroga;
- conto COGE e centro di costo/WBS; si conserva anche il codice conto come importato, se non è nel piano dei conti;
- importo fisso (imponibile, IVA esclusa);
- massimale variabile e stima di consumo del variabile, espressa **o** in percentuale (0–100) **o** in importo (non oltre il massimale), mai in entrambe le forme;
- piano di fatturazione.

**Piano di fatturazione** (per voce):
- modalità: `Anticipata` / `Posticipata` / `Una tantum` / `A SAL` / `A consumo` / `Da verificare` (solo per la migrazione, §7.6);
- periodicità: mensile, bimestrale, trimestrale, semestrale, annuale, intera durata (obbligatoria per anticipata e posticipata);
- data della prima fattura (default: inizio se anticipata, fine del primo periodo se posticipata);
- giorni di pagamento (default parametrico: 60 gg d.f.f.m.). La data di pagamento stimata è la **fine del mese di (data fattura + giorni di pagamento)**. È solo informativa: il budget non la usa (§5.2);
- adeguamento: nessuno, ISTAT o percentuale fissa (§5.2).

Da questi dati il sistema genera uno **scadenzario rate** (data fattura, data pagamento stimata, importo) modificabile riga per riga. Le rate effettivamente fatturate possono essere marcate come consuntivo. Una rata aggiunta o modificata a mano resta marcata come tale.

Regole di generazione:
- la rata contiene **solo la quota fissa**; la quota variabile non si salva sulle rate e la ripartisce il motore (§5.2, livelli);
- rate uguali per periodo, con il residuo dell'arrotondamento sull'ultima;
- se la durata non è un multiplo della periodicità, l'ultimo periodo è più corto e la sua rata è proporzionale ai giorni; le altre rate restano uguali tra loro;
- `A SAL`: nessuna rata generata, le rate si inseriscono a mano;
- `A consumo`: rate mensili posticipate;
- `Da verificare`: nessuna rata; la cassa usa il pro-rata a giorni e lo segnala.

**Stato pratica di rinnovo** (workflow): `Non avviata` → `Offerta richiesta` → `Offerta ricevuta` → `RDA predisposta` → `RDA approvata` → `OdA emesso` → `Contratto attivo`.
- La pratica si lega al **contratto in scadenza**; per un fabbisogno nuovo, senza contratti, si lega al fabbisogno. Mai a entrambi.
- Si conserva lo storico dei passaggi (stato, data, utente, note). Lo stato corrente è l'ultimo passaggio; senza passaggi vale `Non avviata`.

**Tabelle di configurazione**:
- lead time per procedura, in mesi;
- soglie per l'importo, con validità temporale;
- piano dei conti con validità temporale e mappatura vecchio→nuovo (sostituisce la colonna "Nuovo codice conto da 01/01/26"). Si **inserisce a mano** dall'amministrazione: non c'è import del piano dei conti, e i conti reali non entrano nel repository;
- parametri con validità temporale: giorni di pagamento, pagamento a fine mese, adeguamento dei rinnovi previsti, finestra dell'alert giallo, orizzonte della previsione;
- categorie dei fabbisogni.

I valori iniziali sono caricati come **provvisori** e si modificano dall'amministrazione.

Nessun dato di dominio si cancella fisicamente: si archivia, e la storia delle modifiche registra chi, quando, valore prima e dopo.

## 5. Logiche di calcolo

### 5.1 Scadenze e alert

- **Aritmetica dei mesi** (addizione e sottrazione, ovunque nel calcolo): una data di fine mese resta a fine mese; le altre date mantengono il giorno, ridotto all'ultimo giorno del mese se questo è più corto. Esempi: 30/11 − 3 mesi = 31/08; 31/12 − 4 mesi = 31/08; 30/06 − 4 mesi = 28/02 (29/02 negli anni bisestili); 30/09 + 3 mesi = 31/12; 15/03 − 1 mese = 15/02; 31/05 − 3 mesi = 28/02.
- `data_fine = data_inizio + durata − 1 giorno`, salvo override.
- Con proroghe esercitate, la **data di fine effettiva** è la nuova data di fine più lontana tra le proroghe. Data limite, data ultima di disdetta e alert si calcolano sulla data di fine effettiva (TC-10).
- `data_limite_avvio = data_fine − lead_time(procedura)`. Il lead time si può sovrascrivere sul singolo contratto. Sostituisce il valore fisso di 6 mesi.
- Per i contratti a tacito rinnovo: `data_ultima_disdetta = data_fine − preavviso`. Negli alert (regole 3 e 4) la data di riferimento è la più vicina tra data limite e data ultima di disdetta.
- Colori degli alert. Le regole si valutano in quest'ordine e vale la prima che si applica:
  1. nessun alert se la decisione del fabbisogno è `Dismettere` o se esiste un contratto successore registrato;
  2. 🔴 se oggi > data di fine;
  3. 🟠 se oggi > data limite e la pratica è `Non avviata` o `Offerta richiesta`;
  4. 🟡 se oggi > data limite con pratica più avanzata, oppure se oggi ≥ data limite − 3 mesi (finestra parametrica);
  5. 🟢 in tutti gli altri casi.

  I casi di verifica sono in `docs/TEST_CASES.md`, TC-06.

### 5.2 Tre viste di budget (tutte per anno, conto, area, fornitore, finanziamento)

| Vista | Domanda a cui risponde | Regola |
|---|---|---|
| **Impegno / ordini** | Quanto devo ordinare nell'anno X? (Procurement) | intero valore contrattuale nell'anno di emissione (o di previsto avvio) dell'OdA |
| **Cassa / fatturato** | Quanto viene fatturato nell'anno X? | somma delle rate dello scadenzario **per data fattura**. La data di pagamento non è usata: il flusso di cassa effettivo è fuori perimetro |
| **Competenza** | Quanto costa all'esercizio X? (conto economico) | pro-rata **a giorni** sul periodo di servizio, indipendente dalla fatturazione |

Esempio: licenza triennale da 30 k€ con pagamento anticipato unico → impegno 30 k€ nell'anno 1, cassa 30 k€ nell'anno 1, competenza 10 k€ all'anno per 3 anni.

Regole di dettaglio:
- **Impegno**: contratto reale nell'anno della data dell'OdA, o se manca nell'anno di inizio del servizio; voce di una proroga nell'anno della data dell'atto; contratto previsto nell'anno di inizio del servizio.
- **Competenza**: il periodo di servizio di una voce è quello del contratto; per una voce di proroga va dal giorno dopo la data di fine precedente alla nuova data di fine. I contratti CAPEX seguono lo stesso pro-rata a giorni: l'ammortamento è fuori perimetro.
- **Adeguamento sul piano**: `Percentuale` si applica a ogni anniversario della data di inizio; `ISTAT`, in assenza dell'indice reale, usa la percentuale del parametro di adeguamento.

Ogni vista ha tre livelli:
- **fisso**: somma delle quote fisse;
- **probabile**: fisso + variabile × stima di consumo;
- **massimo**: fisso + intero massimale.

In cassa la quota variabile (stimata o massima) si distribuisce sulle date delle rate in proporzione agli importi fissi delle rate; se il fisso è zero, in proporzione ai giorni dei periodi. Per la modalità `A consumo` le rate mensili si calcolano sul livello richiesto.

### 5.3 Previsione rinnovi (scenario)

Per ogni fabbisogno con decisione `Rinnovare` o `Da valutare`, il cui contratto attivo scade entro l'orizzonte (default 3 anni), il sistema genera un **contratto previsto**:
- inizio = giorno dopo la scadenza (data di fine effettiva, proroghe comprese);
- stessa durata **originale** del contratto precedente (senza proroghe) e stesso piano di fatturazione;
- importo: ogni voce del contratto precedente, escluse le voci delle proroghe, si replica con fisso e massimale × (1 + adeguamento parametrico valido alla data di inizio del previsto);
- se il fabbisogno ha una stima manuale, la stima sostituisce il fisso totale ed è ripartita tra le voci in proporzione al loro fisso; l'adeguamento dei previsti successivi parte dalla stima (TC-07).

La generazione è ricorsiva: un annuale che scade nel 2027 genera un previsto 2027 e poi un previsto 2028.

- Un fabbisogno non ha contratti paralleli. Se ha più contratti senza successore (per esempio un contratto vecchio non collegato alla catena), i previsti partono solo da quello che scade per ultimo.
- Un contratto scaduto da tempo, senza successore e con decisione `Rinnovare` o `Da valutare`, genera previsti anche per periodi già trascorsi. Nei report di budget dell'anno X entrano solo i previsti che finiscono dal 01/01/X in poi; gli altri non entrano, e il fabbisogno è segnalato come **rinnovo mancante**.

- I contratti previsti entrano in tutte e tre le viste di budget, marcati come "previsionali" e filtrabili.
- Nuovi fabbisogni (senza contratto predecessore) si inseriscono a mano come previsti, con i dati del **previsto manuale** sul fabbisogno (§4).

### 5.4 Output per il Procurement

Report annuale "Piano ordini anno X". Una riga per ogni contratto previsto o da rinnovare, con:
- fabbisogno, fornitore uscente, importo stimato sull'intera durata;
- procedura presunta, data limite di avvio, data di avvio servizio necessaria;
- stato della pratica.

Include un avviso quando più fabbisogni della stessa categoria o dello stesso fornitore, sommati, superano una soglia. Serve a valutare l'accorpamento ed evitare il frazionamento. L'applicabilità concreta delle soglie per Siciliacque (settori speciali) va confermata con Procurement/Legale.

Export in XLSX, oltre al PDF quando serve da allegare.

## 6. Perimetro funzionale

**MVP**:
- anagrafiche (fornitori, fabbisogni, contratti, voci, piani di fatturazione);
- scadenzario rate generato;
- alert;
- tre viste di budget con i livelli fisso/probabile/massimo;
- previsione rinnovi;
- report Procurement;
- import iniziale dagli Excel;
- export XLSX;
- traccia delle modifiche;
- login aziendale.

**Fase 2**:
- notifiche email sulle date limite;
- consuntivazione rate da export SAP (fatture/OdA);
- confronto preventivo/consuntivo;
- storico costi per fabbisogno (trend);
- dashboard grafica.

**Fuori perimetro**: gestione documentale (restano protocollo e SharePoint), workflow autorizzativi SAP, gestione gare.

## 7. Migrazione dati

1. Normalizzare i campi: rimuovere il BOM, uniformare i nulli, applicare trim.
2. Validare i codici: CIG di 10 caratteri alfanumerici, OdA SAP di 10 cifre, conti COGE presenti nel piano dei conti (inserito a mano prima dell'import). Le anomalie vanno in un report, senza correzioni silenziose.
3. Deduplicare i fornitori e verificare i codici SAP condivisi (139952).
4. Raggruppare in fabbisogni le righe che sono rinnovi l'una dell'altra (proposta automatica per descrizione + fornitore, poi conferma manuale) e impostare il predecessore.
5. Accorpare in un unico contratto con più voci le righe che condividono OdA e CIG.
6. Assegnare a ogni voce il piano di fatturazione reale, dalle fatture o dagli ordini. Dove non è noto, impostare `Da verificare`: in questo caso il budget di cassa usa il pro-rata e lo segnala.
7. Mappare i vecchi stati: `Rinnovato` / `Non rinnovare` diventano decisioni sul fabbisogno; `Offerta richiesta` / `RDA predisposta` diventano stato pratica; `Attivo` / `Scaduto` si derivano dalle date.
8. Controllo di quadratura: totali per anno ricalcolati a competenza, confrontati con la dashboard Excel. Le differenze attese sono dovute al bug dei mesi e vanno documentate.

## 8. Decisioni prese e requisiti non funzionali

### 8.1 Decisioni prese (Rev01)

- **Piattaforma**: web app interna, ospitata su una VM on-prem di Siciliacque.
- **Stack**:
  - Python 3.12, Django 5.2 LTS (supporto fino ad aprile 2028; migrazione a 6.2 LTS pianificata nel 2027);
  - PostgreSQL 16;
  - interfaccia server-side con template Django + HTMX + Bootstrap 5, con le risorse statiche incluse nel repository (nessuna CDN);
  - librerie: `django-auth-ldap`, `django-simple-history` (traccia delle modifiche), `openpyxl` (import/export);
  - test e qualità: `pytest-django`, `ruff`; gestione dipendenze con `uv`.
- **Autenticazione**: LDAP sull'Active Directory aziendale.
  - Connessione LDAPS (porta 636) con la CA interna, oppure StartTLS. Mai bind in chiaro.
  - Account di servizio in sola lettura per la ricerca degli utenti; login con `sAMAccountName`.
  - Ruoli derivati dai gruppi AD, gruppi annidati inclusi:
    - `GG_Contratti_Admin` → amministratore;
    - `GG_Contratti_Editor` → scrittura;
    - `GG_Contratti_Reader` → sola lettura (Procurement, Controllo di gestione).

    I nomi dei gruppi sono configurabili.
  - Un utente che non appartiene a nessuno dei tre gruppi non entra; se aveva già un utente, perde ruolo e privilegi.
  - Con più gruppi vale il ruolo più alto (Admin > Editor > Reader). L'annidamento dei gruppi è configurabile (matching rule AD, ricorsivo, nessuno).
  - L'amministratore ha accesso completo all'amministrazione dell'applicazione; Editor e Reader lavorano dall'interfaccia operativa. Editor aggiunge e modifica i dati di dominio, Reader solo legge; le tabelle di configurazione le modifica solo l'amministratore; nessuno cancella.
  - Un solo account locale di emergenza (break-glass), con password lunga (almeno 24 caratteri) custodita fuori dall'applicazione.
  - Tutti i parametri LDAP arrivano da variabili d'ambiente. Senza server LDAP configurato vale solo il login locale (sviluppo).
  - Il log dei login (riusciti e falliti, mai la password) si conserva 12 mesi.
  - La sessione dura al massimo 8 ore; la rimozione da un gruppo AD ha effetto al login successivo.
- **Codice**: repository GitHub privato. Lo sviluppo è affidato a Claude Code (sessioni cloud) tramite pull request; il merge su `main` lo fa solo Pietro, dopo revisione e CI verde.
- **Deploy**: manuale sulla VM interna (`git pull` + `docker compose up -d --build` + `migrate`), con uno script di deploy nel repository. Nessun runner CI dentro la rete aziendale nella prima fase.

### 8.2 Requisiti non funzionali

- **Dati reali mai nel repository.** Gli Excel originali, i dump e i backup restano on-prem. Nel repository ci sono solo i campioni anonimizzati in `tests/fixtures/`, che hanno la stessa struttura degli originali (anomalie comprese) ma nomi, codici e importi falsi. L'import reale si esegue sulla VM di produzione.
- **Segreti solo in variabili d'ambiente** sulla VM (`.env` non versionato). Nel repository c'è solo `.env.example`.
- **Importi** in `Decimal` (`DecimalField(max_digits=14, decimal_places=2)`), mai `float`. Arrotondamento `ROUND_HALF_UP` al centesimo; l'eventuale residuo va sull'ultima rata o sull'ultimo anno.
- **Date** di tipo `date`, senza orario. Fuso orario `Europe/Rome`.
- **Backup**: `pg_dump` giornaliero su una cartella inclusa nel backup aziendale esistente, con procedura di ripristino documentata e provata.
- **Accesso** solo dalla rete interna, dietro reverse proxy HTTPS con certificato della CA interna. Cookie `Secure` e `HttpOnly`, CSRF attivo.
- **Log applicativo** dei login riusciti e falliti.
- **Lingua dell'interfaccia**: italiano. Formati numerici e date all'italiana (1.234,56; 31/12/2026).

## 9. Decisioni ancora aperte

- **Budget di riferimento per il Controllo di gestione**: competenza economica o cassa? Quali conti sono CAPEX? Il sistema calcola comunque tutte e tre le viste, quindi la risposta non blocca lo sviluppo.
- **Lead time per procedura** e soglie: parametri con valori iniziali provvisori, modificabili dall'amministrazione. Non bloccano lo sviluppo; le soglie UE dei settori speciali non sono caricate.
- **Anno di imputazione dell'impegno per i contratti previsti**: il default è l'anno di inizio del servizio. Da confermare con il Procurement se preferisce l'anno della data limite di avvio.
- **IVA**: gli importi sono sempre imponibile. Da verificare se il Procurement vuole anche l'IVA nel piano ordini.
- **Mappatura dei gruppi AD e account di servizio**: da creare sul dominio.

## 10. Regole di lavoro per Claude in questo progetto

- Distinguere sempre tra requisito deciso, proposta e ipotesi. Non dare per realizzato ciò che è solo discusso.
- Ogni modifica al modello dati o alle regole di calcolo va registrata in questo documento, con una nuova revisione (Rev02, Rev03, …).
- Ogni regola di calcolo va accompagnata da almeno un caso di test numerico (input → output atteso) in `docs/TEST_CASES.md`, da riusare nei test automatici.
- Nel repository si usano solo i dati anonimizzati di `tests/fixtures/`. Se un dato reale serve e manca, segnalarlo, senza inventarlo.
- I documenti prodotti fuori dal repository seguono lo standard di nome `AAAA.MM.GG_MITTENTE_DESCRIZIONE_RevNN`. I file del repository mantengono i nomi convenzionali (`README.md`, `CLAUDE.md`, ...).
