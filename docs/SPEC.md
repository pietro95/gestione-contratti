# Istruzioni di progetto — Registro contratti IT/TLC

Rev01 — 30/09/2026 — autore: Pietro Verro (IT Manager, Siciliacque S.p.A.)

Storico revisioni:
- Rev00 (30/09/2026): analisi e requisiti.
- Rev01 (30/09/2026): decisa la piattaforma (web app interna, autenticazione LDAP), aggiunti requisiti non funzionali (§8), casi di test in `docs/TEST_CASES.md`, regole per i dati nel repository.

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

**Fabbisogno** (servizio ricorrente):
- descrizione, area (IT/TLC), categoria (licenze SW, manutenzione HW, connettività, servizi professionali, noleggio, ecc.);
- referente;
- decisione di continuità: `Rinnovare` / `Da valutare` / `Sostituire` / `Dismettere`;
- stima del prossimo importo e note.

**Contratto** (istanza):
- chiave: fabbisogno, contratto predecessore;
- riferimenti: fornitore, n. OdA SAP, n. RDA, CIG;
- procedura (affidamento diretto, MEPA/ODA, RDO, negoziata, aperta, adesione a convenzione/AQ);
- date: data stipula, data inizio, durata in mesi (la data di fine si calcola, con override ammesso);
- rinnovo: opzione di rinnovo/proroga prevista (sì/no, mesi, importo), tacito rinnovo con termine di disdetta in giorni;
- classificazione: finanziamento (ordinario / finanziato + progetto/WBS), natura (OPEX/CAPEX);
- documenti: link al protocollo o a SharePoint, senza caricare file.

**Voce di contratto** (1..n per contratto):
- descrizione;
- conto COGE e centro di costo/WBS;
- importo fisso (imponibile, IVA esclusa);
- massimale variabile e stima di consumo variabile (%, o importo);
- piano di fatturazione.

**Piano di fatturazione** (per voce):
- modalità: `Anticipata` / `Posticipata` / `Una tantum` / `A SAL` / `A consumo`;
- periodicità: mensile, bimestrale, trimestrale, semestrale, annuale, intera durata;
- data della prima fattura (default: inizio se anticipata, fine del primo periodo se posticipata);
- giorni di pagamento (default parametrico, es. 60 gg d.f.f.m.);
- adeguamento ISTAT o indicizzazione, se previsto.

Da questi dati il sistema genera uno **scadenzario rate** (data fattura, data pagamento stimata, importo) modificabile riga per riga. Le rate effettivamente fatturate possono essere marcate come consuntivo.

**Stato pratica di rinnovo** (workflow, sul fabbisogno o sul contratto successore): `Non avviata` → `Offerta richiesta` → `Offerta ricevuta` → `RDA predisposta` → `RDA approvata` → `OdA emesso` → `Contratto attivo`.

**Tabelle di configurazione**:
- lead time per procedura, in mesi;
- soglie per l'importo;
- piano dei conti con validità temporale e mappatura vecchio→nuovo (sostituisce la colonna "Nuovo codice conto da 01/01/26");
- aliquote e indici.

## 5. Logiche di calcolo

### 5.1 Scadenze e alert

- `data_fine = data_inizio + durata − 1 giorno`, salvo override.
- `data_limite_avvio = data_fine − lead_time(procedura)`. Il lead time si può sovrascrivere sul singolo contratto. Sostituisce il valore fisso di 6 mesi.
- Per i contratti a tacito rinnovo: `data_ultima_disdetta = data_fine − preavviso`.
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
| **Cassa / fatturato** | Quando escono i soldi? | somma delle rate dello scadenzario per data fattura (o data pagamento stimata) |
| **Competenza** | Quanto costa all'esercizio X? (conto economico) | pro-rata **a giorni** sul periodo di servizio, indipendente dalla fatturazione |

Esempio: licenza triennale da 30 k€ con pagamento anticipato unico → impegno 30 k€ nell'anno 1, cassa 30 k€ nell'anno 1, competenza 10 k€ all'anno per 3 anni. Se la licenza è capitalizzata (CAPEX), la competenza segue invece l'ammortamento, da gestire come caso distinto.

Ogni vista ha tre livelli:
- **fisso**: somma delle quote fisse;
- **probabile**: fisso + variabile × stima di consumo;
- **massimo**: fisso + intero massimale.

### 5.3 Previsione rinnovi (scenario)

Per ogni fabbisogno con decisione `Rinnovare` o `Da valutare`, il cui contratto attivo scade entro l'orizzonte (default 3 anni), il sistema genera un **contratto previsto**:
- inizio = giorno dopo la scadenza;
- stessa durata e stesso piano di fatturazione del contratto precedente;
- importo = stima manuale del fabbisogno se presente, altrimenti ultimo importo × (1 + adeguamento parametrico).

La generazione è ricorsiva: un annuale che scade nel 2027 genera un previsto 2027 e poi un previsto 2028.

- I contratti previsti entrano in tutte e tre le viste di budget, marcati come "previsionali" e filtrabili.
- Nuovi fabbisogni (senza contratto predecessore) si inseriscono a mano come previsti.

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
2. Validare i codici: CIG di 10 caratteri alfanumerici, OdA SAP di 10 cifre, conti COGE presenti nel piano dei conti. Le anomalie vanno in un report, senza correzioni silenziose.
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
  - Un utente che non appartiene a nessuno dei tre gruppi non entra.
  - Un solo account locale di emergenza (break-glass), con password lunga custodita fuori dall'applicazione.
  - Tutti i parametri LDAP arrivano da variabili d'ambiente.
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
- **Lead time per procedura** e soglie, da concordare con il Procurement. Sono parametri, con valori iniziali provvisori.
- **Anno di imputazione dell'impegno per i contratti previsti**: il default è l'anno di inizio del servizio. Da confermare con il Procurement se preferisce l'anno della data limite di avvio.
- **IVA**: gli importi sono sempre imponibile. Da verificare se il Procurement vuole anche l'IVA nel piano ordini.
- **Mappatura dei gruppi AD e account di servizio**: da creare sul dominio.

## 10. Regole di lavoro per Claude in questo progetto

- Distinguere sempre tra requisito deciso, proposta e ipotesi. Non dare per realizzato ciò che è solo discusso.
- Ogni modifica al modello dati o alle regole di calcolo va registrata in questo documento, con una nuova revisione (Rev02, Rev03, …).
- Ogni regola di calcolo va accompagnata da almeno un caso di test numerico (input → output atteso) in `docs/TEST_CASES.md`, da riusare nei test automatici.
- Nel repository si usano solo i dati anonimizzati di `tests/fixtures/`. Se un dato reale serve e manca, segnalarlo, senza inventarlo.
- I documenti prodotti fuori dal repository seguono lo standard di nome `AAAA.MM.GG_MITTENTE_DESCRIZIONE_RevNN`. I file del repository mantengono i nomi convenzionali (`README.md`, `CLAUDE.md`, ...).
