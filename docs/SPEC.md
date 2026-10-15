# Istruzioni di progetto — Registro contratti ICTDINN

> Documento normativo per requisiti e regole di dominio. Per la vista tecnica consultare [ARCHITECTURE](ARCHITECTURE.md) e [DATA_MODEL](DATA_MODEL.md); per le procedure operative consultare [RUNBOOK](RUNBOOK.md) e [OPERATIONS](OPERATIONS.md).

Rev19 — 14/10/2026 — responsabile: IT Manager ICTDINN, Siciliacque S.p.A.

Storico revisioni:
- Rev00 (30/09/2026): analisi e requisiti.
- Rev01 (30/09/2026): decisa la piattaforma (web app interna, autenticazione LDAP), aggiunti requisiti non funzionali (§8), casi di test in `docs/TEST_CASES.md`, regole per i dati nel repository.
- Rev02 (01/10/2026): decisioni prese durante F0, F1 e la preparazione di F2. Modello dati (§4): proroghe esercitate multiple, previsti manuali sul fabbisogno, stato pratica, modalità `Da verificare`, stima di consumo, data OdA, impianti e progetti, piano dei conti inserito a mano. Regole di calcolo (§5): aritmetica dei mesi a fine mese, data di fine con proroghe, tacito rinnovo negli alert, cassa solo per data fattura, quota variabile, SAL e consumo, ultimo periodo corto, adeguamento, impegno, rinnovi previsti, CAPEX senza ammortamento. Autenticazione (§8.1). Nuovo caso TC-10, TC-03 allineato alla regola di pagamento.
- Rev03 (01/10/2026): rinnovi previsti (§5.3): un solo contratto di partenza per fabbisogno; nei report di budget i previsti già conclusi prima dell'anno selezionato non entrano e il fabbisogno è segnalato come rinnovo mancante. Tolto l'adeguamento dal piano di fatturazione (§4, §5.2): non serve, gli importi anno per anno sono già fissati a contratto. Resta l'adeguamento parametrico dei rinnovi previsti (§5.3).
- Rev04 (01/10/2026): quote per periodo sulla voce (§4, §5.2, §5.3): importi fissi diversi per sotto-periodi, tipicamente annuali, facoltativi. Nuovo caso TC-11.
- Rev05 (01/10/2026): nuovo stato pratica `RDA richiesta` (§4); regole di dettaglio dell'import Excel (§7): mappatura di colonne e stati, contratti finanziati e dissalatori, valori di attesa per i dati mancanti, proposte da confermare.
- Rev06 (05/10/2026): allineamento alle fasi F8–F9.3, già in produzione. Ufficio ICTDINN con i cluster al posto dell'area (§1, §4); numero e data di emissione del contratto al posto dell'OdA (§4); natura, conto e WBS sulla voce, WBS di cluster e a progetto (§4); un contratto può rinnovare più contratti (§4, §5.1, §5.3, TC-12); fatturato come riferimento del budget, OPEX e CAPEX mai sommati, CAPEX per WBS (§5.2); Spese per WBS (§5.5); import dall'interfaccia, incrementale, struttura dell'ufficio (§7); permessi e visibilità per cluster (§8.1); decisioni aperte aggiornate (§9).
- Rev07 (05/10/2026): spese ricorrenti senza contratto sul fabbisogno (§4, §5.6, TC-14), per gli acquisti piccoli e periodici pagati con fattura diretta (es. dominio DNS): entrano nel budget, hanno solo un promemoria 🟡 (§5.1) e restano fuori dal piano ordini (§5.4).
- Rev08 (05/10/2026): la spesa senza contratto può proseguire un fabbisogno con contratti, se tutti finiscono prima della prima spesa: la spesa fa da successore dell'ultimo contratto (§4, §5.1, §5.6, TC-14).
- Rev09 (05/10/2026): decisione del responsabile del progetto, da approvare. Tolta la spesa ricorrente sul fabbisogno (Rev07–Rev08): anche senza contratto ogni rinnovo va gestito, con scadenza, data limite, pratica e alert. Il **rinnovo senza contratto** è un contratto segnato «senza contratto», anello della catena come gli altri: stesse regole di scadenze, alert, previsti e budget; fuori dal piano ordini (§4, §5.1, §5.4, §5.6, TC-14). Chiusa la decisione aperta sulle spese ricorrenti nel budget (§9).
- Rev10 (05/10/2026): decisione del responsabile del progetto, da approvare. Connettore MCP in sola lettura per Claude, specificato in `docs/SPEC_MCP.md` (§8.1). **Deroga** all'accesso solo interno: su Internet si espone solo il connettore, su un host dedicato raggiungibile solo dalla rete di uscita di Anthropic; login, interfaccia e amministrazione restano interni (§8.2).
- Rev11 (05/10/2026): decisioni del responsabile del progetto per la release 2.0, **bozza da approvare**. Il registro traccia anche il processo d'acquisto dell'ufficio ICTDINN e sostituisce il file «Riepilogo RDA Ordini» (§1, §2.3). Nuove entità: **richiesta d'acquisto (RDA)**, **documento di esecuzione** (ODA/RDC, DDT, MIGO, MAP, attestazione di regolare esecuzione, modello di ricezione materiale) e **fattura**; chiusura del contratto; RUP, CUP, richiedente e percorso dei documenti (§4). Contratto **una tantum**: fuori dalla catena dei rinnovi, dagli alert e dai previsti, dentro il budget (§4, §5.1, §5.3, §5.4). Gli stati della pratica da `RDA richiesta` in poi si **ricavano dalla RDA** collegata (§4, §5.7, TC-15). Esecuzione, residuo da fatturare e contratti da chiudere (§5.8, TC-16). Import manuale da modello XLSX e import del Riepilogo dal 01/04/2025 (§7). Nuove decisioni aperte (§9).
- Rev12 (05/10/2026): decisione del responsabile del progetto, da approvare. Il connettore MCP prevede anche la scrittura (sotto-fase F10.1, `docs/SPEC_MCP.md` Rev05 §8): solo Admin ed Editor, scope separato, anteprima con gli effetti calcolati e conferma, stesse validazioni e permessi dell'interfaccia, nessuna cancellazione (§8.1).
- Rev13 (07/10/2026): decisioni del responsabile del progetto, **bozza da approvare**. Rivisto il processo d'acquisto della release 2.0 (Rev11) sul flusso reale: il **referente** compila sul portale la **richiesta di RDA** con le posizioni e i campi SAP; l'**addetto amministrativo** la inserisce in SAP aiutato da una **scheda SAP** con i campi già pronti e riporta sul portale i dati di SAP; il contratto lo registrano l'addetto o il referente; le fatture e i documenti SAP che le accompagnano li registra l'addetto, con la scheda SAP della fattura (§4, §5.7, §5.9). Funzione «Amministrazione acquisti» assegnata per utente, senza nuovo ruolo AD (§8.1). Cruscotti dell'addetto (RDA da processare, fatture da lavorare) e del referente (le mie RDA) (§5.7). La richiesta di RDA **parte dal fabbisogno**: se il fabbisogno ha contratti è impostata come rinnovo del contratto in scadenza e precompilata dal suo rinnovo previsto (§4, §5.9). RDA e contratti si inseriscono anche a mano, scollegati, e si collegano dopo (§4, §7). Nessuna mail inviata dal portale: il portale prepara il testo (§5.9). Nuove tabelle di configurazione, con import da Excel: richiedenti SAP, gruppi merci e gruppi acquisti, ciascuna con un valore predefinito; cartella base delle RDA per cluster (§4, §7). Chiusura del contratto: addetto o referente (§4). TC-15 aggiornato, nuovo TC-17.
- Rev14 (07/10/2026): decisioni del responsabile del progetto, **bozza da approvare**. Lavorazione della fattura in tre passi, uno dopo l'altro e per ogni fattura: **RdC** (richiesta di consegna) → **MAP** per i servizi o **MIGO** per le forniture → **trasferimento per il pagamento** (solo data). Tipo d'acquisto (servizio o fornitura) sul contratto, che propone MAP o MIGO (§4, §5.7, §5.9). TC-15 (e) aggiornato.
- Rev15 (07/10/2026): decisioni del responsabile del progetto, **bozza da approvare**. Fattura: importo del documento (SAP) distinto dal **valore base prelevato dal contratto** (conta per il residuo), con oneri previdenziali e bollo; le fatture importate sono visibili a tutti e un referente le **prende in carico**, una per volta o più insieme, con il **referente proposto** dalle fatture precedenti o dal contratto; contratto facoltativo finché la fattura è **da assegnare**; **convalida del referente** come passo prima della RdC; **fuori registro**. **Commento per PAC** composto al trasferimento. **Import settimanale delle fatture** dall'estrazione SAP annotata (§4, §5.7, §5.8, §5.9, §7). Nuovo TC-18; TC-15 (e) precisato.
- Rev16 (12/10/2026): decisione del responsabile del progetto, da approvare. Piano ordini (§5.4): l'anno di un previsto è quello della **data limite di avvio della procedura**, non quello di avvio del servizio; nel piano dell'anno in corso entrano anche i previsti **in ritardo** (data limite passata, servizio non finito prima dell'anno, pratica non conclusa), marcati. Gli avvisi di frazionamento nel PDF sono facoltativi. TC-13 aggiornato, nuovo TC-17.
- Rev17 (12/10/2026): decisione del responsabile del progetto, da approvare. Piano ordini (§5.4): un previsto entra nel piano di ogni anno toccato dalla sua procedura, dalla data limite all'avvio del servizio: «da avviare» nell'anno della data limite, «da concludere» negli anni successivi fino all'avvio. I totali contano solo le righe da avviare. Ritardo ridefinito: data limite passata con pratica non avviata, o servizio che doveva già partire. TC-17 aggiornato.
- Rev18 (14/10/2026): decisione del responsabile del progetto, da approvare. Piano ordini (§5.4): diviso in sezioni OPEX e CAPEX con totali propri; ogni riga ha valore contrattuale e valore normalizzato sull'anno (competenza a giorni); entrano anche i contratti già registrati con competenza nell'anno, anche una tantum (in deroga a Rev11); righe raggruppate per cluster e sottocluster con subtotali; fonte di finanziamento sulla riga. Nuove tabelle **Sottocluster** e **Fonte di finanziamento** (§4).
- Rev19 (14/10/2026): decisioni del responsabile del progetto, **bozza da approvare**. **Autorizzazione extra budget**: attività spot non previste nel budget ma autorizzate espressamente dall'AD (§4). Si collega alla **voce**, OPEX o CAPEX; le voci extra budget sono fuori dai budget dei cluster, con un filtro come le WBS a progetto (§5.2). Il contratto con voci extra budget è **una tantum**: nessun rinnovo, fuori dal piano ordini. Importo autorizzato confrontato con il **massimo** delle voci collegate (fisso + massimale): oltre, avviso e non blocco. Vista Spese extra budget (§5.5 bis). La marcano Admin ed Editor. Nuovo TC-19.
- Rev20 (14/10/2026): decisioni del responsabile del progetto, **bozza da approvare**. Import settimanale delle fatture (§7): un **fornitore non in anagrafica si crea al momento** (`FORNITORE_CREATO`, da verificare), invece di scartare la riga; l'import è disponibile anche **nella pagina delle fatture** per l'amministrazione acquisti. Fatture (§4, §5.7): una fattura con «bloccata fino al» in corso è al passo **`Bloccata`**, non `Da convalidare`; la pagina delle fatture si apre di default su «Le mie fatture» quando tutte le fatture sono state prese in carico. Il test del TC-18 sul passo di una fattura bloccata segue la nuova regola.
- Rev21 (15/10/2026): decisioni del responsabile del progetto, **bozza da approvare**. Il budget si legge sulla **competenza delle fatture**, non più sulla data fattura: la fattura indica il **periodo di competenza** (§4), obbligatorio con il valore base, e nuova vista **«Fatturato e stanziato (competenza)»** (§5.2), prima colonna e riferimento del budget. Nuova entità **stanziamento** (§4): costo di competenza non ancora fatturato, che conta nel budget finché non arriva la fattura. La cassa per data fattura resta come confronto. Nuovo TC-20. Il §5.8 («il budget non cambia») è superato.

## 1. Obiettivo

Sostituire i due file Excel (`Contratti_IT.xlsx`, `Contratti_TLC.xlsx`) con un unico registro che:

1. tenga traccia di tutti i contratti dell'ufficio ICTDINN (cluster IT, TLC, OT, Sicurezza fisica, Innovazione) e della loro catena di rinnovi;
2. produca un budget annuale affidabile, distinguendo **impegno**, **cassa** e **competenza**;
3. produca per il Procurement la **previsione annuale degli ordini/procedure da avviare**, con data limite di avvio e importo stimato;
4. segnali in anticipo le scadenze, in funzione della procedura di affidamento e non di un preavviso fisso;
5. (release 2.0) tracci il processo d'acquisto dell'ufficio ICTDINN, dalla richiesta d'acquisto alla chiusura del contratto (RDA → contratto → esecuzione → fattura → chiusura), e sostituisca il file «Riepilogo RDA Ordini» per la parte ICTDINN.

Utenti: IT Manager (responsabile applicativo e amministrazione), responsabili dei cluster (scrittura sui propri cluster, §8.1), Procurement e Controllo di gestione (lettura + export).

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

### 2.3 Il file «Riepilogo RDA Ordini» (release 2.0)

Analisi del file aggiornato al 02/10/2026 (Rev11). Il file resta on-prem: qui ci sono solo struttura e conteggi.

- Un foglio, intestazione su due righe, 33 colonne in sette gruppi: RDA (numero, data o data dell'ultimo rilascio, descrizione, commessa/WBS, centro di costo, conto, gestore/richiedente SAP, RUP, CUP); RPA/RPC (solo fino ad aprile 2025); contratto (codifica interna fino ad aprile 2025, numero SAP, fornitore, data, inizio e fine delle prestazioni, importo base e massimo); fattura (numero, data, imponibile); DDT (numero, data); attestazione di regolare esecuzione o modello di ricezione materiale (numero, data); percorso sul server, stato, basket del masterplan, note, numeri SAP di ODA/RDC, MAP e MIGO.
- Circa 1.030 RDA dal 2021 su 1.834 righe: le altre righe sono fatture, DDT o attestazioni della stessa RDA, tenute insieme da 3.920 celle unite (una RDA arriva a 52 righe).
- Il file copre tutta l'area, non solo ICTDINN (dal percorso: Sede/Reparti, OT, IT, INV, FER, Elettrico, TLC, Dissalatori). Il registro tratta solo ICTDINN (§7).
- In gran parte forniture una tantum, con DDT ed entrata merci: solo circa 100 righe hanno inizio e fine delle prestazioni.
- Dati: più numeri nella stessa cella, separati da a capo (attestazioni 265 celle, conti 85, fatture 67, centri di costo 54); date di fattura come testo o numero seriale; importi in più formati; BOM nei numeri di contratto; quattro sistemi di numerazione (interna fino ad aprile 2025, poi SAP); stato «Aperto»/«Chiuso» vuoto in due righe su tre e scritto in 12 modi; RDA «Chiuse» senza attestazione; basket del masterplan quasi sempre vuoto (non si riporta).
- Gran parte delle colonne ripete dati di SAP. Il collegamento diretto a SAP non è possibile: i dati SAP entrano a mano o da un import XLSX (§7); nel registro si aggiunge ciò che SAP non dà, cioè il legame con fabbisogno e pratica, RUP, percorso dei documenti, note e chiusura.

## 3. Principi di progettazione

1. **Un solo registro** per l'ufficio ICTDINN. Cluster, natura, WBS e impianto sono attributi, non fogli.
2. **Separare il fabbisogno dal contratto.** Il *Fabbisogno* è il servizio ricorrente, che vive per anni (es. "Licenze IBM Cognos"). Il *Contratto* è la singola istanza con numero di contratto SAP, CIG, date e importi. Un rinnovo è un nuovo contratto sullo stesso fabbisogno.
3. **Il budget nasce dal piano di fatturazione**, non da una divisione per mesi.
4. **Le date derivate si calcolano, le date decise si salvano.** Scadenza, data limite e alert sono sempre calcolati.
5. **SAP resta il riferimento** per numeri di contratto, RDA, codici fornitore, conti COGE e WBS. Il registro li memorizza come chiavi esterne e non li reinventa. L'integrazione iniziale è un import/export, non un'interfaccia online.
6. **Soglie normative, lead time e aliquote sono parametri configurabili**, mai valori fissi nel codice.
7. **Traccia completa delle modifiche** (chi, quando, valore prima e dopo). Nessuna cancellazione fisica.

## 4. Modello dati (logico)

**Fornitore**: ragione sociale, P.IVA, codice SAP, **nome breve** (facoltativo, Rev13: per l'intestazione della RDA e il nome della cartella, §5.9), note.
- La P.IVA è facoltativa e, se presente, univoca.
- Il codice SAP non è univoco: nei file attuali lo stesso codice è assegnato a più fornitori (§2.2). Il sistema lo ammette e lo segnala.

**Fabbisogno** (servizio ricorrente):
- descrizione, cluster, categoria (licenze SW, manutenzione HW, connettività, servizi professionali, noleggio, ecc.);
  - il cluster è una tabella di configurazione (vedi **Cluster**);
  - la categoria è una tabella di configurazione, modificabile dall'amministrazione;
- impianto (facoltativo, da tabella; es. un dissalatore);
- sottocluster (facoltativo, da tabella): sottocategoria del cluster, che deve essere quello del fabbisogno (Rev18);
- fonte di finanziamento (facoltativa, da tabella, Rev18);
- referente: testo libero, più un collegamento facoltativo all'utente dell'applicazione;
- decisione di continuità: `Rinnovare` / `Da valutare` / `Sostituire` / `Dismettere`;
- stima del prossimo importo e note;
- **previsto manuale** (solo per un fabbisogno nuovo, senza contratti): data di avvio prevista, durata, procedura presunta, modalità e periodicità di fatturazione previste, natura, conto e WBS previsti. Sono dati decisi e si salvano; il contratto previsto che ne deriva si calcola (§5.3). Avvio e durata vanno indicati insieme; CAPEX ⇔ WBS come sulla voce.

**Contratto** (istanza):
- chiave: fabbisogno, contratto predecessore (dello stesso fabbisogno);
- **più predecessori, un solo successore** (TC-12): un contratto nuovo può sostituire più contratti (es. SIM voce e SIM M2M in un contratto unico). Il rinnovo principale è il predecessore; gli altri contratti sostituiti **confluiscono** nel nuovo. Ogni contratto ha al massimo un successore: o è il predecessore di uno, o confluisce in uno. Si confluisce solo in un contratto dello stesso fabbisogno che inizia dopo il contratto confluito; un contratto di un altro fabbisogno va prima accorpato;
- riferimenti: fornitore, numero di contratto SAP, data di emissione del contratto, **RDA d'origine** (Rev11: collegamento alla richiesta d'acquisto, al posto del n. RDA come testo), CIG, CUP (facoltativo), RUP (testo libero). In azienda il riferimento SAP è il numero di contratto, non l'OdA. I codici si conservano come arrivano; le anomalie di formato vanno nel report d'import (§7);
- procedura (affidamento diretto, MEPA/ODA, RDO, negoziata, aperta, adesione a convenzione/AQ), con override del lead time sul singolo contratto;
- date: data stipula, data inizio, durata in mesi (la data di fine si calcola, con override ammesso). La data di inizio può mancare solo nei dati importati: il contratto resta escluso dai calcoli e segnalato (TC-08);
- opzioni di rinnovo/proroga previste e non ancora esercitate: zero o più, ciascuna con tipo (rinnovo o proroga), mesi e importo;
- proroghe esercitate: zero o più (vedi **Proroga**);
- tacito rinnovo con termine di disdetta in giorni (obbligatorio se c'è tacito rinnovo);
- classificazione: natura e WBS stanno sulle voci. La natura del contratto si ricava dalle voci (OPEX, CAPEX o mista); il contratto è **finanziato** se ha almeno una voce su una WBS a progetto;
- documenti: link al protocollo o a SharePoint, oppure percorso sul server aziendale (`X:\…`, `\\nas…`, Rev11), senza caricare file;
- **una tantum** (sì/no, Rev11): acquisto che non si rinnova, tipicamente una fornitura (§5.1, §5.3). Non ha predecessore né successore, non entra nella catena, non va in alert e non genera previsti; entra nel budget come ogni contratto. Default: fatturazione `Una tantum`, inizio alla data di emissione, durata 1 mese (da confermare, §9). Sta su un fabbisogno come gli altri contratti, anche insieme a una catena (es. licenze aggiuntive acquistate una volta) o su un fabbisogno di sole forniture;
- **tipo d'acquisto** (Rev14): `Servizio` (default) o `Fornitura`; propone MAP (servizio) o MIGO (fornitura) nella lavorazione delle fatture (§5.9);
- **chiusura** (Rev11): data e utente della chiusura amministrativa (prestazione attestata, fatture registrate). È un atto deciso, si salva; si può annullare. La registrano l'addetto amministrativo o il referente (Rev13: ogni Editor del cluster, §8.1). Su un contratto chiuso non si registrano documenti di esecuzione né fatture: prima si annulla la chiusura;
- **senza contratto** (sì/no): acquisto senza documento contrattuale, per esempio con fattura diretta (§5.6). Numero di contratto, data di emissione e tacito rinnovo non servono; tutto il resto vale come per un contratto.

**Proroga** (0..n per contratto): proroga effettivamente esercitata, anche più volte sullo stesso contratto.
- data dell'atto, nuova data di fine, riferimento (protocollo, contratto integrativo o atto aggiuntivo), note;
- l'eventuale importo aggiuntivo non sta sulla proroga ma in una o più **voci di contratto** collegate alla proroga, ciascuna con il proprio piano di fatturazione. Una proroga senza importo è ammessa.

**Cluster** (tabella): area dell'ufficio che raggruppa più conti (IT, TLC, OT, Sicurezza fisica, Innovazione); codice breve e stabile, nome, note. I cluster IT e TLC hanno lo stesso responsabile e in pratica lo stesso budget: le viste li mostrano insieme ("i miei cluster", §8.1).

**WBS** (tabella): elemento WBS di SAP, su cui si imputano le spese CAPEX. Due tipi:
- **di cluster**: CAPEX "generico" del cluster, entra nel suo budget CAPEX; il cluster è obbligatorio; ha una fonte di finanziamento facoltativa (Rev18, anche per le WBS a progetto);
- **a progetto** (es. nuovi dissalatori): fuori dai budget dei cluster; i contratti restano registrati e consultabili per WBS (§5.5). Sostituisce la tabella Progetti; "finanziato" coincide con "su WBS a progetto".

**Autorizzazione extra budget** (tabella, Rev19): attività spot non prevista in fase di stipula del budget ma autorizzata espressamente dall'AD. Codice, descrizione, cluster, protocollo e data dell'autorizzazione AD, **importo autorizzato** (imponibile), documento (percorso), note; archiviabile, con storia. Non è un elemento SAP: è una WBS a progetto "logica", valida per OPEX e CAPEX.
- si collega alla **voce** (facoltativo), non al contratto: un contratto può avere voci a budget e voci extra budget. La voce conserva natura, conto e WBS (CAPEX ⇔ WBS resta);
- l'autorizzazione deve essere del cluster del fabbisogno;
- un contratto con almeno una voce extra budget è **una tantum** (§4, Rev11): nessun rinnovo, fuori dalla catena, dagli alert, dai previsti e dal piano ordini (anche in deroga alla Rev18, che vi porta i contratti una tantum registrati). Il contratto si dice «extra budget» (prevale su «finanziato»);
- **consumato** = somma del massimo (fisso + massimale variabile) delle voci attive collegate; oltre l'importo autorizzato si mostra un **avviso** (non un blocco): il registro descrive ciò che è stato emesso;
- la marcano Admin ed Editor (modifica della voce); le autorizzazioni si registrano in amministrazione.

**Impianto** (tabella): nome e note.

**Sottocluster** (tabella, Rev18): sottocategoria di un cluster; cluster, nome (unico nel cluster) e note; si archivia, non si cancella. Raggruppa i fabbisogni nel piano ordini (§5.4).

**Fonte di finanziamento** (tabella di configurazione, Rev18): nome unico, attiva, note; nessun valore iniziale. Si assegna al fabbisogno e alla WBS. Per una riga del piano ordini vale la fonte del fabbisogno; se manca, quella della WBS delle voci; se manca, «Ordinaria».

**Voce di contratto** (1..n per contratto):
- descrizione;
- proroga di riferimento, se la voce è l'importo di una proroga;
- **natura** (OPEX/CAPEX), conto COGE, centro di costo e **WBS**. CAPEX ⇔ WBS: una voce CAPEX sta sempre su una WBS, una OPEX su nessuna; una WBS di cluster deve essere del cluster del fabbisogno. Il conto deve essere del cluster del fabbisogno. In SAP ogni posizione ha la sua imputazione: un contratto con quota OPEX e quota CAPEX ha voci separate, mai percentuali. Si conservano anche il codice conto e il codice WBS come importati, se non sono in tabella;
- **natura, conto e WBS dei rinnovi** (facoltativi): la classificazione dei rinnovi previsti, se diversa da quella della voce (es. nata CAPEX, rinnovata in OPEX);
- importo fisso (imponibile, IVA esclusa);
- massimale variabile e stima di consumo del variabile, espressa **o** in percentuale (0–100) **o** in importo (non oltre il massimale), mai in entrambe le forme;
- **quote per periodo** (facoltative): importi fissi diversi per sotto-periodi del servizio, tipicamente annuali (es. 10.000 il primo anno, 10.500 il secondo). Le quote devono essere contigue, coprire tutto il periodo di servizio della voce e sommare all'importo fisso; se non lo fanno si ignorano e l'anomalia è segnalata;
- piano di fatturazione.

**Piano di fatturazione** (per voce):
- modalità: `Anticipata` / `Posticipata` / `Una tantum` / `A SAL` / `A consumo` / `Da verificare` (solo per la migrazione, §7.6);
- periodicità: mensile, bimestrale, trimestrale, semestrale, annuale, intera durata (obbligatoria per anticipata e posticipata);
- data della prima fattura (default: inizio se anticipata, fine del primo periodo se posticipata);
- giorni di pagamento (default parametrico: 60 gg d.f.f.m.). La data di pagamento stimata è la **fine del mese di (data fattura + giorni di pagamento)**. È solo informativa: il budget non la usa (§5.2);
- nessun adeguamento sul piano: i contratti che prevedono importi diversi negli anni li fissano già a contratto, anno per anno.

Da questi dati il sistema genera uno **scadenzario rate** (data fattura, data pagamento stimata, importo) modificabile riga per riga. Le rate effettivamente fatturate possono essere marcate come consuntivo. Una rata aggiunta o modificata a mano resta marcata come tale.

Regole di generazione:
- la rata contiene **solo la quota fissa**; la quota variabile non si salva sulle rate e la ripartisce il motore (§5.2, livelli);
- rate uguali per periodo, con il residuo dell'arrotondamento sull'ultima;
- se la durata non è un multiplo della periodicità, l'ultimo periodo è più corto e la sua rata è proporzionale ai giorni; le altre rate restano uguali tra loro;
- `A SAL`: nessuna rata generata, le rate si inseriscono a mano;
- `A consumo`: rate mensili posticipate;
- `Da verificare`: nessuna rata; la cassa usa il pro-rata a giorni e lo segnala;
- con quote per periodo, ogni quota si fattura come una voce a sé con lo stesso piano (la prima fattura esplicita vale solo per la prima quota); la numerazione delle rate prosegue. La `Una tantum` resta una sola rata dell'intero fisso.

**Stato pratica di rinnovo** (workflow): `Non avviata` → `Offerta richiesta` → `Offerta ricevuta` → `RDA richiesta` → `RDA predisposta` → `RDA approvata` → `Contratto emesso` → `Contratto attivo`.
- `RDA richiesta`: l'IT ha chiesto l'inserimento della RDA in SAP; diventa `RDA predisposta` quando la RDA è inserita. Da Rev13 corrispondono alle fasi `Inviata` e `Inserita` della richiesta di RDA (§5.7).
- La pratica si lega al **contratto in scadenza**; per un fabbisogno nuovo, senza contratti, si lega al fabbisogno. Mai a entrambi.
- Si conserva lo storico dei passaggi (stato, data, utente, note).
- **Rev11, stati ricavati dalla RDA**: da `RDA richiesta` in poi lo stato si ricava dalle RDA collegate alla pratica (§5.7), non si registra a mano. A mano si registrano solo `Offerta richiesta` e `Offerta ricevuta`. I passaggi registrati prima della 2.0 (anche dall'import) restano nello storico.
- Lo **stato corrente** è il più avanzato, nell'ordine del workflow, tra l'ultimo passaggio registrato e lo stato ricavato dalle RDA (TC-15); senza passaggi e senza RDA vale `Non avviata`. Il passaggio a `Contratto attivo` che «Registra rinnovo» scrive oggi resta solo per le pratiche senza RDA collegate; con una RDA lo stato si ricava.

**Richiesta d'acquisto (RDA)** (Rev11, rivista in Rev13). Nasce sul portale come **richiesta di RDA** compilata dal referente; l'addetto amministrativo la inserisce in SAP e vi riporta i dati che SAP restituisce (§5.9). In migrazione si può anche registrare direttamente una RDA già inserita in SAP.
- **cluster** (obbligatorio; per la richiesta nata sul portale è quello del fabbisogno) e **referente** (utente dell'applicazione, obbligatorio per le richieste nate sul portale; per le RDA registrate a mano o importate anche solo testo);
- **la richiesta nasce dal fabbisogno** (Rev13): si crea dalla pagina del fabbisogno (o dal contratto, che porta al suo fabbisogno); un acquisto nuovo richiede prima il fabbisogno. Lo **scopo** si imposta da solo:
  - **rinnovo**, se il fabbisogno ha contratti che non siano tutti una tantum: la RDA si lega al **contratto in scadenza**, cioè il contratto senza successore che scade per ultimo, lo stesso da cui partono i previsti (§5.3); con la catena interrotta (più contratti senza successore) si propone questo e si può sceglierne un altro. I campi si precompilano dal **rinnovo previsto** (§5.9);
  - **primo acquisto**, se il fabbisogno non ha contratti (o solo contratti una tantum): la RDA si lega al fabbisogno; i campi si precompilano dal previsto manuale del fabbisogno, se c'è;
  - **acquisto aggiuntivo**, a scelta dell'utente al posto del rinnovo (es. licenze in più a metà contratto): la RDA si lega al fabbisogno e non tocca la pratica del contratto in scadenza; il contratto che ne nasce è proposto come una tantum;
- legami modificabili dopo: fabbisogno, oppure contratto in scadenza (la pratica, mai entrambi); contratti generati (campo RDA d'origine sul contratto). Solo le RDA registrate a mano (già in SAP) o importate possono restare **senza legami**: si collegano in seguito da una parte o dall'altra; il portale propone il collegamento quando il n. RDA scritto su un contratto coincide con una RDA registrata (proposta da confermare, §7);
- **campi della richiesta** (li compila il referente, nell'ordine della scheda SAP): intestazione (default «nome breve del fornitore proposto − descrizione», §5.9), fornitore proposto (facoltativo), richiedente SAP e gruppo acquisti (dalle tabelle, default il valore predefinito; si può scegliere anche il richiedente di un altro ufficio), note al buyer, allegati (testo: cosa è allegato e dove si trova; il portale non conserva file), percorso sul file server (proposto, §5.9), RUP, CUP, note interne;
- **posizioni** (1..n, numerate): descrizione breve, gruppo merci, quantità (fino a 3 decimali), importo unitario (imponibile), importo della posizione = quantità × importo unitario arrotondato `ROUND_HALF_UP` al centesimo; **di cui variabile** (informativo, Rev13: la parte dell'importo della posizione che è massimale a consumo; in SAP la RDA va sempre per l'importo massimo, perché il contratto si stipula per tutto l'importo e poi si può consumare di meno); campi informativi: natura, conto COGE, centro di costo, WBS (stesse regole della voce: CAPEX ⇔ WBS, conto e WBS di cluster del cluster della RDA). L'importo della RDA è la somma delle posizioni;
- **campi da SAP** (li compila l'addetto, o il referente, §8.1): numero RDA (10 cifre, di norma inizia con 51), data di inserimento, data dell'ultimo rilascio;
- **storico della richiesta** (fatti decisi, si salvano): invio all'addetto, rimando al referente con la nota di cosa correggere, annullamento con motivo; ciascuno con data e utente. Dopo l'invio i campi della richiesta si modificano in due modi, entrambi ammessi: rimandandola al referente, oppure correggendoli direttamente (chi può modificare la RDA, §8.1), con traccia nella storia delle modifiche;
- una RDA genera **zero o più contratti**; «Registra contratto da RDA» precompila fornitore, voci (una per posizione, con descrizione, importo fisso = importo della posizione − di cui variabile, massimale variabile = di cui variabile, natura, conto, centro di costo e WBS), RUP, CUP, fabbisogno e predecessore (il contratto in scadenza). Gli importi del contratto restano quelli emessi: la differenza tra il massimo del contratto (fisso + massimale) e l'importo della RDA si mostra, non si corregge;
- valgono i permessi per cluster (§8.1).

**Documento di esecuzione** (Rev11, 0..n per contratto): tipo (`ODA/RDC`, `DDT`, `MIGO`, `MAP`, `Attestazione di regolare esecuzione`, `Modello di ricezione materiale`), numero, data, importo facoltativo, voce facoltativa, parziale o finale (solo per attestazione e modello di ricezione), **fattura** a cui si riferisce (facoltativa, Rev13: i documenti SAP predisposti a supporto della fattura, es. MAP o MIGO), note. I numeri si conservano come arrivano; le anomalie di formato vanno nel report d'import.

**Fattura** (Rev11, rivista in Rev14–Rev15):
- **fornitore** (obbligatorio), numero, data, **importo del documento** (l'«Importo SAP» dell'estrazione: il totale del documento, per esempio valore base + oneri previdenziali + bollo);
- **contratto** (Rev15): facoltativo finché la fattura è **da assegnare** (arrivata dall'import senza contratto); voce e rata facoltative. Una fattura si può abbinare a una rata dello scadenzario: la rata diventa consuntivo e riceve il numero di fattura; il suo importo non cambia da solo (resta modificabile a mano, tracciato);
- **valore base prelevato dal contratto** (Rev15): è l'importo che conta per fatturato, residuo e avanzamento del contratto (§5.8); vuoto finché qualcuno non lo indica; la proposta è l'importo del documento meno oneri e bollo;
- **oneri previdenziali** e **bollo** (Rev15, facoltativi): entrano nel commento per PAC (§5.9);
- **periodo di competenza** (Rev21): data di inizio e di fine (estremi inclusi), **obbligatorio quando si indica il valore base**. Decide l'anno di budget della fattura (§5.2): il valore base si ripartisce a giorni sugli anni del periodo. Una fattura con valore base e senza competenza (per esempio arrivata dall'import, che non la porta) è segnalata (`COMPETENZA_MANCANTE`) e nel budget si imputa provvisoriamente all'anno della data fattura (`COMPETENZA_FATTURA_MANCANTE`);
- **presa in carico** (Rev15): referente (utente) e data. La fattura importata non ha referente: la vedono tutti e la prende in carico un Admin o un Editor, di qualunque cluster, per sé, una per volta o più insieme dall'elenco. Una fattura già in carico a un altro non si prende: la si lascia (chi l'ha in carico, che la rimette tra quelle da prendere) o la si riassegna (Admin e addetto). Per abbinarla a un contratto servono comunque i permessi sul cluster del contratto;
- **referente proposto** (Rev15, valore derivato, non si salva): per una fattura non in carico, il primo che si trova, tra gli utenti attivi, in quest'ordine:
  1. chi ha in carico (o ha avuto in carico, se trasferita) l'**ultima fattura** dello stesso contratto, assegnato o proposto, per data del documento;
  2. il **referente del contratto**: il referente (utente) del suo fabbisogno;
  3. il referente (utente) della RDA d'origine del contratto;
  4. senza contratto proposto: chi ha in carico l'ultima fattura dello stesso fornitore.

  Senza nessuno dei quattro, nessuna proposta. La proposta non assegna nulla da sola: orienta l'elenco (§5.7) e l'assegnazione multipla;
- **convalida del referente** (Rev15): la fa chi ha in carico la fattura; esito (`Da valutare`, `Convalidabile`, `Non convalidabile`, `In attesa`), nota (es. «in attesa di prove di funzionamento in campo»), **bloccata fino al** (data facoltativa: fattura stanziata e bloccata fino a quella data, compresa; Rev20: fino ad allora il passo è `Bloccata`);
- **fuori registro** (Rev15, sì/no): la fattura non riguarda il registro (altro ufficio, acquisto senza contratto); resta registrata, fuori dalle viste di lavorazione; la segna un Admin o un Editor, anche su più fatture insieme, e si può togliere;
- data di registrazione, trasferimento (Rev14: data e utente), note, chiave d'import.

Lo stesso numero di fattura dello stesso fornitore non si registra due volte. La registra l'addetto amministrativo (o il referente), a mano o con l'import settimanale (§7); la scheda SAP della fattura propone i campi (§5.9).

**Stanziamento** (Rev21, 0..n per voce): costo di competenza per cui il fornitore non ha ancora fatturato quando dovrebbe. Campi: **voce** del contratto, **rata** dello scadenzario che sostituisce (facoltativa), **importo** (imponibile, IVA esclusa), **periodo di competenza** (dal, al), data dello stanziamento, note, **fattura che lo chiude** (facoltativa). Lo registra l'addetto o il referente (Editor del cluster) sul contratto; non ha numero di fattura. Un contratto chiuso non riceve stanziamenti.
- È **attivo** finché non arriva la fattura: lo chiude la fattura abbinata alla stessa rata, oppure indicata sullo stanziamento. Lo stato «chiuso» è derivato (non si salva); un stanziamento si annulla archiviandolo.
- Nel budget a competenza (§5.2) prende il posto della rata che sostituisce, per il suo periodo di competenza; senza rata si somma.
- **Lavorazione** (Rev14, rivista in Rev15), per ogni fattura, in quest'ordine: (0a) **presa in carico**; (0b) **assegnazione al contratto**, se manca; (0c) **convalida del referente**: esito `Convalidabile`; (1) **RdC**, documento di esecuzione `ODA/RDC` collegato alla fattura, una per fattura; (2) **MAP** (servizi) o **MIGO** (forniture), documento collegato alla fattura, proposto dal tipo d'acquisto del contratto e modificabile; (3) **trasferimento per il pagamento**: data e utente sulla fattura, senza numero SAP.
- Il **passo da fare** è il primo che manca, nell'ordine: `Da prendere in carico` → `Da assegnare` → `Da convalidare` (o `Bloccata`) → `RdC da fare` → `MAP/MIGO da fare` → `Da trasferire`; con il trasferimento registrato la fattura è `Trasferita`. Con esito `In attesa` o `Non convalidabile` la fattura resta al passo `Da convalidare`. (Rev20) Con «bloccata fino al» uguale o successiva a oggi, qualunque sia l'esito, il passo è `Bloccata` (non `Da convalidare`): la fattura è da lavorare ma **non è «ferma»**, perché aspetta la data del blocco; passata la data torna al passo che le spetta (`Da convalidare` se l'esito non è `Convalidabile`, altrimenti `RdC da fare`). Una fattura è **da lavorare** finché non è trasferita, salvo se fuori registro. Un passo registrato fuori ordine si accetta: conta il primo mancante.

**Tabelle di configurazione**:
- lead time per procedura, in mesi;
- soglie per l'importo, con validità temporale;
- piano dei conti con validità temporale, mappatura vecchio→nuovo (sostituisce la colonna "Nuovo codice conto da 01/01/26") e **cluster** del conto (ogni conto appartiene a un solo cluster). Si carica dall'interfaccia (import del piano dei conti o della struttura, §7) o dall'amministrazione; i conti reali non entrano nel repository;
- cluster, WBS e **assegnazioni dei cluster agli utenti** (§8.1), caricati con l'import della struttura;
- parametri con validità temporale: giorni di pagamento, pagamento a fine mese, adeguamento dei rinnovi previsti, finestra dell'alert giallo, orizzonte della previsione; (Rev11) giorni oltre i quali una RDA è «ferma» in una fase (§5.7); (Rev13) giorni oltre i quali una fattura è «ferma» da lavorare (§5.7);
- categorie dei fabbisogni;
- (Rev13) **richiedenti SAP** (codice, ufficio o descrizione, attivo, **predefinito**: uno solo, oggi il codice dell'ufficio ICTDINN; gli altri servono per richieste a nome di altri uffici), **gruppi merci** (codice SAP, descrizione, attivo, predefinito; facoltativa la categoria di fabbisogno a cui si propone) e **gruppi acquisti** (codice, nome, attivo, predefinito: il gruppo legato all'ufficio, che si usa quasi sempre; gli altri si scelgono sulla singola RDA). Al più un predefinito per tabella. Si caricano con l'**import da Excel** (§7) o dall'amministrazione, solo Admin; i codici reali non entrano nel repository;
- (Rev13) **cartella base delle RDA** del cluster sul file server (es. `smb://<nas>/Share/ICTDINN/00_IT/RDA_Ordini`);
- (Rev13) **funzioni degli utenti**: «Amministrazione acquisti», assegnata per nome utente di dominio come i cluster (§8.1).

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
  1. nessun alert se la decisione del fabbisogno è `Dismettere`, se esiste un contratto successore registrato, se il contratto è confluito in un contratto nuovo (TC-12) o se il contratto è una tantum (Rev11);
  2. 🔴 se oggi > data di fine;
  3. 🟠 se oggi > data limite e la pratica è `Non avviata` o `Offerta richiesta`;
  4. 🟡 se oggi > data limite con pratica più avanzata, oppure se oggi ≥ data limite − 3 mesi (finestra parametrica);
  5. 🟢 in tutti gli altri casi.

  I casi di verifica sono in `docs/TEST_CASES.md`, TC-06.


### 5.2 Tre viste di budget (tutte per anno, cluster, conto, WBS, fornitore)

| Vista | Domanda a cui risponde | Regola |
|---|---|---|
| **Fatturato e stanziato (competenza)** (Rev21) | Quanto costa all'anno X, sulle fatture e sugli stanziamenti? | per ogni rata: la **fattura registrata** (valore base) o lo **stanziamento** che la sostituisce, imputati **a giorni** al loro periodo di competenza; la rata senza fattura né stanziamento resta la **previsione** (sul periodo della rata, se noto, altrimenti nell'anno della data fattura). Si sommano le fatture e gli stanziamenti non abbinati a una rata. È **il riferimento del budget**: prima colonna e vista di default |
| **Cassa / fatturato** | Quanto viene fatturato nell'anno X? | somma delle rate dello scadenzario **per data fattura** (Rev21: solo confronto, non è più il riferimento). La data di pagamento non è usata: il flusso di cassa effettivo è fuori perimetro |
| **Impegno / ordinato** | Quanto devo ordinare nell'anno X? (Procurement) | intero valore contrattuale nell'anno di emissione del contratto (o di previsto avvio) |
| **Competenza** | Quanto costa all'esercizio X? (conto economico) | pro-rata **a giorni** sul periodo di servizio, indipendente dalla fatturazione |

Esempio: licenza triennale da 30 k€ con pagamento anticipato unico → impegno 30 k€ nell'anno 1, cassa 30 k€ nell'anno 1, competenza 10 k€ all'anno per 3 anni.

Regole di dettaglio:
- **Impegno**: contratto reale nell'anno della data di emissione del contratto, o se manca nell'anno di inizio del servizio; voce di una proroga nell'anno della data dell'atto; contratto previsto nell'anno di inizio del servizio.
- **Competenza**: il periodo di servizio di una voce è quello del contratto; con quote per periodo, il fisso si ripartisce a giorni quota per quota (TC-11), il variabile sull'intera voce; per una voce di proroga va dal giorno dopo la data di fine precedente alla nuova data di fine. I contratti CAPEX seguono lo stesso pro-rata a giorni: l'ammortamento è fuori perimetro.

**Fatturato e stanziato a competenza, regole di dettaglio (Rev21).**
- Una fattura entra con il **valore base** (senza valore base non conta, come per il residuo del contratto, §5.8); fuori registro e archiviate sono escluse. Si abbina alla voce indicata, o alla voce della rata abbinata; senza voce, all'unica voce del contratto o, se ce n'è più d'una, alla voce principale (`FATTURA_SENZA_VOCE`).
- Sulla stessa rata la fattura prevale sullo stanziamento; lo stanziamento chiuso dalla fattura o archiviato non conta.
- Fatture e stanziamenti non abbinati a una rata si **sommano** alle rate previste (`CONSUNTIVO_NON_ABBINATO`): per non contare due volte lo stesso costo si abbinano alla rata.
- La quota variabile (probabile, massimo) segue la competenza a giorni della voce, come nella vista «Competenza».
- Nei contratti previsti non ci sono fatture né stanziamenti: la vista coincide con le rate.
- La vista «Competenza» (pro-rata a giorni sul periodo del contratto) resta com'è, come stima indipendente dalla fatturazione.

Ogni vista ha tre livelli:
- **fisso**: somma delle quote fisse;
- **probabile**: fisso + variabile × stima di consumo;
- **massimo**: fisso + intero massimale.

In cassa la quota variabile (stimata o massima) si distribuisce sulle date delle rate in proporzione agli importi fissi delle rate; se il fisso è zero, in proporzione ai giorni dei periodi. Per la modalità `A consumo` le rate mensili si calcolano sul livello richiesto.

**OPEX e CAPEX** sono budget distinti e non si sommano mai: ogni voce entra nella sezione della sua natura (un contratto misto contribuisce a entrambe). Il default è l'OPEX; "OPEX e CAPEX, separati" mostra due sezioni con totali propri, anche nell'export.
- OPEX per cluster e conto; CAPEX per cluster e WBS di cluster, con il dettaglio per conto sotto ogni WBS (come lo legge il Controllo di gestione).
- Le voci su WBS a progetto sono fuori dai budget dei cluster; un filtro le include o le mostra da sole.
- (Rev19) Anche le voci extra budget sono fuori dai budget dei cluster, OPEX e CAPEX; un filtro separato le include o le mostra da sole.
- Di default ogni utente vede i propri cluster (§8.1).

### 5.3 Previsione rinnovi (scenario)

Per ogni fabbisogno con decisione `Rinnovare` o `Da valutare`, il cui contratto attivo scade entro l'orizzonte (default 3 anni), il sistema genera un **contratto previsto**:
- inizio = giorno dopo la scadenza (data di fine effettiva, proroghe comprese);
- stessa durata **originale** del contratto precedente (senza proroghe) e stesso piano di fatturazione;
- importo: ogni voce del contratto precedente, escluse le voci delle proroghe, si replica con fisso e massimale × (1 + adeguamento parametrico valido alla data di inizio del previsto). Le quote per periodo non si replicano: il previsto riparte dal fisso totale della voce;
- se il fabbisogno ha una stima manuale, la stima sostituisce il fisso totale ed è ripartita tra le voci in proporzione al loro fisso; l'adeguamento dei previsti successivi parte dalla stima (TC-07).

La generazione è ricorsiva: un annuale che scade nel 2027 genera un previsto 2027 e poi un previsto 2028.

- Un fabbisogno non ha contratti paralleli. I previsti partono dal contratto senza successore che scade per ultimo; un contratto confluito in un altro ha un successore e non genera previsti (TC-12). Se restano più contratti senza successore (per esempio un contratto vecchio non collegato alla catena), il fabbisogno segnala la catena interrotta, con la proposta di collegamento (§7).
- I contratti una tantum (Rev11) non contano: non generano previsti, non interrompono la catena e non sono proposti come predecessori o successori. Un fabbisogno con soli contratti una tantum ha previsti solo dal previsto manuale.
- La classificazione del previsto (natura, conto, WBS) è quella decisa per i rinnovi sulla voce d'origine, se c'è, altrimenti quella della voce; per il previsto manuale, quella del fabbisogno. Un previsto è finanziato solo se resta su una WBS a progetto.
- Un contratto scaduto da tempo, senza successore e con decisione `Rinnovare` o `Da valutare`, genera previsti anche per periodi già trascorsi. Nei report di budget dell'anno X entrano solo i previsti che finiscono dal 01/01/X in poi; gli altri non entrano, e il fabbisogno è segnalato come **rinnovo mancante**.

- I contratti previsti entrano in tutte e tre le viste di budget, marcati come "previsionali" e filtrabili.
- Nuovi fabbisogni (senza contratto predecessore) si inseriscono a mano come previsti, con i dati del **previsto manuale** sul fabbisogno (§4).

### 5.4 Output per il Procurement

Report annuale "Piano ordini anno X". Un contratto previsto o da rinnovare entra nel piano di ogni anno toccato dalla sua procedura, dalla **data limite di avvio** all'**avvio del servizio** (Rev16, Rev17):
- **da avviare**: la data limite cade nell'anno X. Solo queste righe entrano nei totali e negli avvisi di frazionamento;
- **da concludere**: la data limite cade in un anno precedente e il servizio parte nell'anno X o dopo: l'ordine va ancora emesso. La riga è fuori dai totali, perché è già contata nel piano dell'anno della data limite. Una pratica a `Contratto emesso` o `Contratto attivo` toglie la riga.

Nel piano dell'anno in corso entrano anche, da concludere, i previsti con servizio già partito, che finiscono dal 01/01/X in poi, con pratica non conclusa. Sempre nell'anno in corso una riga è marcata «in ritardo» se la data limite è passata e la pratica è `Non avviata`, o se il servizio doveva già partire. I piani degli altri anni non hanno ritardi. Ogni riga riporta:
- fabbisogno, fornitore (uscente per un previsto), **valore contrattuale** (importo stimato sull'intera durata) e **valore normalizzato sull'anno X** (Rev18: competenza dell'anno, pro-rata a giorni come §5.2 e TC-11, per fisso, probabile e massimo);
- procedura presunta, data limite di avvio, data di avvio servizio necessaria;
- stato della pratica; stato del contratto («Previsto», «In stipula», «Stipulato»);
- fonte di finanziamento (§4).

**Sezioni (Rev18).** Il piano è diviso in una sezione OPEX e una CAPEX, ciascuna con i totali propri, mai sommati (un foglio per natura nell'export XLSX). Un contratto misto compare in entrambe, con la sola quota della natura. Dentro la sezione le righe sono raggruppate per cluster e sottocluster, con i subtotali; i fabbisogni senza sottocluster stanno in «(senza sottocluster)». Il totale contrattuale conta solo le righe da avviare; il totale normalizzato somma tutte le righe della sezione, perché la competenza di anni diversi non si sovrappone.

**Contratti già registrati (Rev18).** Entrano nel piano anche i contratti registrati, in stipula o stipulati, la cui competenza nell'anno X è diversa da zero (per natura: una quota a competenza zero non compare). Riga «registrato»: senza data limite, fuori dai totali contrattuali e dagli avvisi di frazionamento. Stipulato se la data di stipula o la data di inizio è non successiva a oggi, altrimenti In stipula. Restano fuori gli archiviati, quelli senza data di inizio e i «senza contratto» (§5.6).

Di default il piano mostra i propri cluster (§8.1).

I rinnovi senza contratto, registrati o previsti, non entrano nel piano ordini: non passano dal Procurement (§5.6). Un contratto una tantum registrato entra come ogni contratto registrato, se ha competenza nell'anno (Rev18, in deroga a Rev11); un acquisto una tantum futuro entra come previsto manuale del fabbisogno (Rev11).

Include un avviso quando più fabbisogni della stessa categoria o dello stesso fornitore, sommati, superano una soglia. Serve a valutare l'accorpamento ed evitare il frazionamento. L'applicabilità concreta delle soglie per Siciliacque (settori speciali) va confermata con Procurement/Legale.

Export in XLSX, oltre al PDF quando serve da allegare. Nel PDF gli avvisi di frazionamento sono facoltativi (Rev16): il PDF standard non li riporta.

### 5.5 Spese per WBS

Per una WBS, di cluster o a progetto: i contratti con voci sulla WBS e gli importi anno per anno, nella vista (fatturato, ordinato, competenza) e al livello scelti. Solo contratti registrati, niente previsti: è la spesa sostenuta o impegnata sulla WBS, anche fuori dai budget dei cluster. Export in XLSX. Di default l'elenco mostra le WBS dei propri cluster e tutte le WBS a progetto.

### 5.5 bis Spese extra budget (Rev19)

Elenco delle autorizzazioni extra budget (di default dei propri cluster) con voci collegate, importo autorizzato, consumato e residuo; per un'autorizzazione, i contratti con voci collegate e gli importi anno per anno, nella vista e al livello scelti, come §5.5. Consumato oltre l'autorizzato: avviso.

### 5.6 Rinnovi senza contratto

Un fabbisogno può proseguire senza documento contrattuale (es. un dominio rinnovato ogni anno con una fattura diretta). Ogni periodo va comunque rinnovato in tempo: si registra come un **contratto segnato «senza contratto»** (§4), anello della catena dei rinnovi come gli altri.
- **Registrazione**: «Rinnova senza contratto» dal contratto che scade (predecessore), oppure «Nuovo senza contratto» per il primo periodo. Inizio di default il giorno dopo la fine del predecessore, durata di default 12 mesi (annuale); si riportano le voci, con classificazione e piano di fatturazione, come in un rinnovo (§5.3). La pratica del predecessore passa a «Contratto attivo».
- **Scadenza e alert**: le stesse regole del contratto (§5.1): data di fine = inizio + durata − 1 giorno (annuale dal 15/03/2025: fine 14/03/2026), data limite = fine − lead time della procedura, alert 🟡 🟠 🔴 con la pratica. Il predecessore non va più in alert.
- **Previsti e budget**: come per un contratto (§5.2, §5.3). Il periodo registrato è consolidato; i periodi successivi sono previsti e partono dal rinnovo senza contratto.
- **Piano ordini**: fuori, sia il periodo registrato sia i suoi previsti (§5.4). Un rinnovo registrato poi come contratto vero rientra nelle regole ordinarie.
- Si può alternare: dopo un rinnovo senza contratto si può registrare un contratto, e viceversa.

### 5.7 Fase della RDA, stato della pratica, cruscotti (Rev11, rivista in Rev13)

La fase di una RDA si ricava dai suoi dati; vale la prima regola che si applica, dall'alto:

| Fase | Condizione | Chi deve agire |
|---|---|---|
| `Annullata` | ultimo evento dello storico: annullamento | — |
| `Chiusa` | almeno un contratto generato e tutti i contratti generati chiusi | — |
| `In esecuzione` | almeno un contratto generato con almeno un documento di esecuzione o una fattura | addetto (fatture) |
| `Contratto emesso` | almeno un contratto generato | — |
| `Rilasciata` | data dell'ultimo rilascio presente | Procurement (sollecito dell'addetto) |
| `Inserita` | numero RDA presente | approvatori SAP (sollecito dell'addetto) |
| `Da correggere` | ultimo evento dello storico: rimando al referente | referente |
| `Inviata` | ultimo evento dello storico: invio | addetto (inserimento in SAP) |
| `Bozza` | negli altri casi | referente |

Una RDA registrata a mano già con il numero SAP non ha bisogno dell'invio: la fase si ricava dai campi SAP e dai contratti.

Stato della pratica ricavato (§4): si considerano le RDA collegate alla pratica e si prende la più avanzata. `Inviata` → `RDA richiesta`; `Inserita` → `RDA predisposta`; `Rilasciata` → `RDA approvata`; `Contratto emesso`, `In esecuzione`, `Chiusa` → `Contratto emesso` se nessun contratto generato è iniziato (data di inizio > oggi), altrimenti `Contratto attivo`. `Bozza`, `Da correggere` e `Annullata` non contano, né le RDA di acquisto aggiuntivo (non sono legate a una pratica): lo stato è quello dell'ultimo passaggio registrato (TC-15). La data dello stato ricavato è la data del fatto che lo determina (invio, inserimento, rilascio, emissione, inizio).

Una RDA è **ferma** se è in `Inviata`, `Inserita` o `Rilasciata` da più dei giorni indicati dal parametro (valore iniziale provvisorio: 30), contati dalla data che l'ha portata in quella fase. Una fattura è **ferma** se è da lavorare (non ancora trasferita) da più dei giorni del parametro (provvisorio: 15) dalla sua registrazione.

**Cruscotto dell'addetto** (utenti con la funzione «Amministrazione acquisti», di default su tutti i cluster che può vedere):
- **RDA da processare**, raggruppate per azione: da inserire in SAP (`Inviata`), da sollecitare per il rilascio (`Inserita`), da sollecitare al Procurement (`Rilasciata`); per ciascuna referente, cluster, importo, giorni nella fase, «ferma» in evidenza, accesso diretto alla scheda SAP;
- **fatture da lavorare**, raggruppate per passo da fare (da assegnare, RdC, MAP/MIGO, trasferimento), con i giorni dalla registrazione; quelle da prendere in carico e da convalidare si vedono a parte, le seconde con il referente a cui sollecitare la convalida; (Rev20) le **bloccate**, con la data del blocco, in un gruppo a parte;
- **contratti da chiudere** (§5.8).

**Fatture da prendere in carico** (Rev15, per tutti i ruoli e su tutti i cluster, nel menu e in cima al cruscotto di ogni Admin ed Editor): fornitore, numero, data, importo, contratto proposto, **referente proposto**, giorni dalla registrazione; filtro «proposte a me», attivo di default per chi ha almeno una proposta; casella di selezione per riga e azioni sulle selezionate: «Prendi in carico» e «Fuori registro» (Admin ed Editor), «Assegna ai referenti proposti» (Admin e addetto: le fatture senza proposta restano nell'elenco e sono indicate). Nel cruscotto di ogni utente, le fatture **proposte a lui** sono in evidenza. L'elenco di tutte le fatture, con filtri per passo, referente, fornitore, contratto, è visibile a tutti. (Rev20) Senza una vista scelta, la pagina delle fatture si apre su «Da prendere in carico»; solo se tutte le fatture sono state prese in carico (nessuna da prendere in carico, né proposta a me né ad altri) si apre su **«Le mie fatture»**: le fatture da prendere in carico non proposte a me restano visibili, perché possono interessare. Per l'amministrazione acquisti (Admin e addetto) la pagina riporta anche il modulo dell'**import settimanale** delle fatture (§7), con anteprima e conferma come in Gestione → Import.

**Le mie RDA** (ogni utente, sulle RDA di cui è referente; anche come scheda del cruscotto): fase, data della fase, giorni, numero SAP, contratto generato; in evidenza quelle in `Bozza` e `Da correggere`, che aspettano il referente. Accanto, le **mie fatture** (Rev15): quelle che l'utente ha in carico e non sono trasferite, con il passo da fare; in evidenza quelle da assegnare e da convalidare, che aspettano lui (le `Bloccate` no: aspettano la data del blocco).

La vista **Stato delle RDA** (tutte le RDA, filtri per cluster, referente, fase, anno, fornitore, WBS) resta per tutti i ruoli.

### 5.8 Esecuzione, residuo e chiusura (Rev11)

Per un contratto, con importi imponibili e voci delle proroghe comprese:
- **fatturato** = somma dei valori base delle fatture assegnate al contratto (Rev15: non l'importo del documento); una fattura senza valore base non conta ed è segnalata (`VALORE_BASE_MANCANTE`);
- **residuo sul fisso** = fisso totale − fatturato; **residuo sul massimo** = fisso + massimale − fatturato; un residuo negativo si mostra come tale;
- **avanzamento** = fatturato / fisso totale, in percentuale arrotondata `ROUND_HALF_UP` all'intero; senza fisso, rispetto al massimale;
- anomalie: `FATTURATO_OLTRE_MASSIMO` (fatturato > fisso + massimale); `FATTURA_DOPO_CHIUSURA` (nell'import, fattura per un contratto chiuso: la riga si scarta); `CHIUSO_SENZA_ATTESTAZIONE` (chiuso senza un'attestazione di regolare esecuzione o un modello di ricezione materiale finale); `FATTURA_DUPLICATA` (stesso numero e fornitore). (Rev15) `IMPORTO_NON_QUADRA`: valore base + oneri + bollo diverso dall'importo del documento (avviso, non blocca).

**Contratti da chiudere** (non chiusi, data di fine effettiva < oggi), con il motivo, dal primo che si applica:
1. `Attestazione mancante`: nessuna attestazione o modello di ricezione finale;
2. `Fatture mancanti`: residuo sul fisso > 0;
3. `Pronto da chiudere`: negli altri casi.

(Rev21) Le fatture registrate entrano anche nel budget, nella vista «Fatturato e stanziato (competenza)» (§5.2), con il periodo di competenza; il residuo del contratto continua a usare il valore base (TC-16).

### 5.9 Scheda SAP e testo della richiesta (Rev13)

Il portale non si collega a SAP: aiuta l'addetto a compilarlo. La **scheda SAP** mostra i campi nell'ordine di SAP, ciascuno con il pulsante «Copia», separando i campi SAP da quelli informativi.

**Scheda SAP della RDA** (stesso contenuto della mail usata finora):
- campi SAP: intestazione; per ogni posizione descrizione breve, gruppo merci, quantità, importo unitario; richiedente; gruppo acquisti; note al buyer (facoltative); allegati;
- campi informativi: per ogni posizione codice WBS (`--` se manca), conto, centro di costo; percorso sul file server;
- «Copia testo della richiesta»: lo stesso contenuto come testo pronto per una mail («Si deve predisporre la seguente RDA. …»), per chi la vuole ancora mandare;
- sotto, i campi da riportare dopo l'inserimento: numero RDA, data di inserimento, data dell'ultimo rilascio.

Regole di proposta (modificabili prima dell'invio):
- **intestazione** = nome breve del fornitore proposto (o la ragione sociale), « - », descrizione; senza fornitore, la sola descrizione. Prima descrizione breve uguale all'intestazione;
- **percorso sul file server** = cartella base del cluster / anno della data di creazione / `AAAA_MM_GG_<Fornitore>_<Descrizione>`, con data di creazione, nome breve del fornitore (se c'è) e descrizione; le lettere accentate perdono l'accento (à → a); spazi e ogni carattere diverso da lettere senza accento, cifre, `-` e `_` diventano `_`, senza `_` ripetuti, iniziali o finali;
- richiedente e gruppo acquisti: il predefinito della tabella; gruppo merci: quello indicato per la categoria del fabbisogno, altrimenti il predefinito;
- **descrizione** = descrizione del fabbisogno; **fornitore proposto** = fornitore del contratto in scadenza (rinnovo) o nessuno;
- **posizioni del rinnovo**: una per ogni voce del rinnovo previsto (§5.3: voci del contratto in scadenza escluse le proroghe, adeguamento o stima manuale applicati), con descrizione breve = descrizione della voce (la prima = intestazione), quantità 1, importo unitario = **massimo** della voce prevista (fisso + massimale) e di cui variabile = massimale della voce prevista, natura, conto, centro di costo e WBS dei rinnovi (o della voce); RUP e CUP dal contratto in scadenza;
- **posizioni del primo acquisto**: una sola, con importo la stima del prossimo importo del fabbisogno (se c'è), natura, conto e WBS previsti; senza previsto, vuota;
- **acquisto aggiuntivo**: una posizione vuota, con natura, conto, centro di costo e WBS della prima voce del contratto in scadenza.

**Scheda SAP della fattura** (Rev14), divisa per passo; per ogni passo i dati da copiare e, sotto, quelli da riportare dopo la registrazione in SAP:
- dati comuni: numero e data della fattura, imponibile, fornitore e codice SAP, numero di contratto SAP, RDA, voce e periodo della rata abbinata (se c'è), testo breve proposto («<numero contratto> - <descrizione contratto> - fattura <numero> del <data>»);
- **RdC**: numero di contratto SAP, voce, importo = imponibile della fattura, testo breve; da riportare numero e data della RdC;
- **MAP** o **MIGO** (proposto dal tipo d'acquisto): numero della RdC, importo, periodo o data della prestazione (dalla rata abbinata), testo breve; da riportare numero e data;
- **trasferimento per il pagamento**: da riportare la data; si allega il **commento per PAC** (Rev15).

**Indicazioni per la validazione** (Rev15, testo con «Copia», per chi fa la RdC): `Valore base da prelevare € <valore base>. COGE: <conto>, CDC: <centro di costo>, WBS: <WBS o -->`.

**Commento per PAC** (Rev15), composto dai dati registrati con «Copia», nello stesso formato usato finora:

```
ODA : <numero della RdC>
MAP: <numero del MAP>            (oppure «MIGO: <numero>» per una fornitura)
CDC: <centro di costo>
COGE: <conto>
WBS: <WBS, oppure -->

Valore base prelevato da contratto: € <valore base>
Oneri previdenziali: € <oneri>   (solo se ci sono)
Bollo: € <bollo>                 (solo se c'è)
```

Conto, centro di costo e WBS sono quelli della voce della fattura, o dell'unica voce del contratto; con più voci e nessuna scelta si scrive `--`. Un numero non ancora registrato si scrive `(da registrare)`.

I nomi dei campi SAP sono quelli dell'estrazione e del commento per PAC usati oggi; se ne mancano si aggiungono dopo (§9).

I casi di verifica sono in `docs/TEST_CASES.md`, TC-17 e TC-18.

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
- consuntivazione rate da export SAP (fatture/contratti);
- confronto preventivo/consuntivo;
- storico costi per fabbisogno (trend);
- dashboard grafica.

**Release 2.0** (Rev11, decisioni del responsabile del progetto del 05/10/2026): processo d'acquisto dell'ufficio ICTDINN.
- RDA, documenti di esecuzione, fatture e chiusura (§4); contratti una tantum;
- (Rev13) flusso: richiesta di RDA del referente → inserimento in SAP dell'addetto con la scheda SAP → contratto registrato dall'addetto o dal referente → fatture e documenti SAP registrati dall'addetto (§4, §5.9);
- stato della pratica ricavato dalle RDA (§5.7);
- viste: cruscotto dell'addetto, le mie RDA, stato delle RDA, contratti da chiudere, anomalie dell'esecuzione; scheda «Esecuzione» del contratto (§5.7, §5.8);
- nessuna mail inviata dal portale: la mail resta facoltativa, con il testo preparato dal portale (§5.9);
- inserimento a mano e import XLSX, import del Riepilogo dal 01/04/2025 (§7).

**Fuori perimetro**: gestione documentale (restano protocollo e SharePoint), workflow autorizzativi SAP, gestione gare.

## 7. Migrazione dati

1. Normalizzare i campi: rimuovere il BOM, uniformare i nulli, applicare trim.
2. Validare i codici: CIG di 10 caratteri alfanumerici, numero di contratto SAP di 10 cifre, conti COGE presenti nel piano dei conti (caricato prima dell'import). Le anomalie vanno in un report, senza correzioni silenziose.
3. Deduplicare i fornitori e verificare i codici SAP condivisi (139952).
4. Raggruppare in fabbisogni le righe che sono rinnovi l'una dell'altra (proposta automatica per descrizione + fornitore, poi conferma manuale) e impostare il predecessore.
5. Accorpare in un unico contratto con più voci le righe che condividono numero di contratto e CIG.
6. Assegnare a ogni voce il piano di fatturazione reale, dalle fatture o dagli ordini. Dove non è noto, impostare `Da verificare`: in questo caso il budget di cassa usa il pro-rata e lo segnala.
7. Mappare i vecchi stati: `Rinnovato` / `Non rinnovare` diventano decisioni sul fabbisogno; `Offerta richiesta` / `RDA predisposta` diventano stato pratica; `Attivo` / `Scaduto` si derivano dalle date.
8. Controllo di quadratura: totali per anno ricalcolati a competenza, confrontati con la dashboard Excel. Le differenze attese sono dovute al bug dei mesi e vanno documentate.

Regole di dettaglio dell'import (comando `import_excel`, Rev05):
- **Colonne**: "Contratto" → numero di contratto (conservato com'è); "Corrispettivo Minimo" → importo fisso; "Corrispettivo Extra" → massimale variabile (nessuna stima di consumo: il probabile coincide con il fisso finché non la si inserisce); "Corrispettivo Massimo" non si importa, serve solo a segnalare le formule sovrascritte e i valori incoerenti; conto: quello "dal 01/01/26" se presente, altrimenti il vecchio (le coppie vecchio → nuovo trovate vanno nel report, per compilare a mano la mappatura).
- **RDA**: il numero RDA si ricava dalle note ("RDA nnnnnnnnnn", oppure una nota di sole 10 cifre che inizia con 51); la nota resta intatta.
- **Stati**: `Non rinnovare` → decisione `Dismettere`; `Rinnovato` e `Attivo` → `Rinnovare`; `Offerta richiesta`, `Offerta ricevuta`, `RDA Richiesta`, `RDA Predisposta` → passaggio della pratica **sul contratto della riga stessa** (è il contratto in scadenza), alla data dell'import, con decisione `Rinnovare`; `Scaduto`, `In scadenza`, `Da rinnovare` → nessun dato, si ricavano dalle date.
- **Contratti finanziati e dissalatori**: i fogli "Contratti_Finanziati" e "Contratti Dissalatori" sono spese su WBS a progetto: voci CAPEX sulla WBS della colonna "Codice WBS"; se manca, WBS `WBS-DA-DEFINIRE` e anomalia.
- **Cluster**: l'import si esegue per un cluster; una voce con un conto di un altro cluster è segnalata (`CONTO_ALTRO_CLUSTER`).
- **Dati mancanti**: categoria `Da classificare`; procedura `Da verificare` (lead time 6 mesi, come il preavviso fisso degli Excel); piano di fatturazione `Da verificare`; fornitore assente → `(non indicato)`; descrizione assente → `(senza descrizione)`; durata assente → 12 mesi. Ogni sostituzione è segnalata.
- **Raggruppamenti e catene**: ogni contratto entra in un fabbisogno provvisorio; l'import propone i raggruppamenti (stessa descrizione normalizzata e stesso fornitore) e le coppie predecessore → successore. Le proposte si confermano o scartano a mano; un predecessore si conferma solo dopo il raggruppamento. Confermando un raggruppamento, i contratti passano al fabbisogno del più recente e i fabbisogni provvisori svuotati si archiviano.
- **Idempotenza e import incrementale**: ogni riga ha una chiave d'import stabile; rieseguire l'import non crea duplicati e non sovrascrive le modifiche fatte dopo. Un contratto già registrato si riconosce anche se il file è cambiato (righe inserite o spostate, foglio rinominato, altro cluster) o se è stato inserito a mano: numero di contratto (o CIG) e data di inizio; senza codici, fornitore, descrizione, data di inizio e durata. La riga si scarta e va nel report (`GIA_PRESENTE`).
- **Catene da ricucire**: dopo un accorpamento il sistema propone il collegamento tra un contratto senza successore e il contratto senza predecessore che inizia dopo di lui e finisce dopo, con l'inizio più vicino al giorno dopo la fine; il rinnovo può iniziare prima della scadenza (periodi sovrapposti, segnalati). Le proposte si confermano a mano; il collegamento si può fare o togliere anche dal contratto. Lo stesso contratto registrato due volte si unisce: si tiene quello con più dati, l'altro si archivia.

Regole di dettaglio per la release 2.0 (Rev11):
- **Import settimanale delle fatture** (Rev15, Gestione → Import, Admin ed Editor; Rev20: anche dalla pagina delle fatture, per Admin e addetto), dall'estrazione SAP annotata che oggi si prepara ogni settimana:
  - **struttura**: primo foglio; l'intestazione è la riga che contiene «Fornitore» e «Numero Documento» (sopra può esserci la riga di revisione); colonne `Fornitore`, `Numero Documento`, `Data`, `Importo SAP`; le altre colonne (`#`, `Note`, `REFERENTE`, `CONVALIDABILE ?` o altre) si ignorano, anche se assenti o compilate. Una riga senza fornitore, numero, data e importo non è una fattura (righe vuote, legenda in fondo): si ignora, e se è compilata solo in parte va nel report;
  - **valori**: data `gg.mm.aaaa`, `gg.mm.aa`, `gg/mm/aaaa` o data Excel; numero conservato come scritto (un numero intero di Excel senza decimali); un numero con testo aggiunto (es. «76 In attesa di nota credito») si importa così com'è ed è segnalato (`NUMERO_DA_VERIFICARE`); l'importo è l'importo del documento;
  - **fornitore**: riconosciuto per ragione sociale o nome breve (stessa normalizzazione dell'import dei contratti); non riconosciuto → (Rev20) il fornitore si **crea al momento**, con la ragione sociale scritta nel file, e la riga si importa; il fatto è segnalato (`FORNITORE_CREATO`, «da verificare»: può essere un nome diverso di un fornitore già in anagrafica, da unire a mano) e contato nel riepilogo (fornitori creati). Il fornitore si crea solo se la riga è valida (numero, data e importo leggibili; importo non negativo); in anteprima non si scrive nulla. Un nome che corrisponde a più fornitori non si importa (`FORNITORE_NON_TROVATO`). Le fatture di un fornitore nuovo entrano da prendere in carico, senza contratto né referente proposti;
  - **abbinamento**: la fattura entra **da prendere in carico**, senza referente, visibile a tutti (§5.7); se il fornitore ha un solo contratto non archiviato e non chiuso in servizio alla data della fattura, il contratto è **proposto** (si conferma a mano); le fatture che non riguardano il registro si segnano **fuori registro**; (Rev21) la fattura importata non ha periodo di competenza: lo indica poi il referente con gli importi (§4);
  - **idempotenza**: fornitore + numero già registrati → nessun duplicato; importo o data diversi → segnalati (`IMPORTO_DIVERSO`, `DATA_DIVERSA`), senza sovrascrivere: da qui in poi il riferimento è l'applicazione;
  - anteprima, conferma e registro come gli altri import.
- **Import dell'esecuzione** (modello XLSX dell'applicazione, un foglio per tipo: RDA con una riga per posizione, documenti di esecuzione, fatture): per caricare in blocco ciò che si legge in SAP, a mano o da un'estrazione riportata nel modello. Nessun collegamento a SAP. Le righe si legano al contratto per numero di contratto SAP (o CIG) e alla RDA per numero SAP; senza corrispondenza vanno nel report (`CONTRATTO_NON_TROVATO`, `RDA_NON_TROVATA`). Idempotente: chiave per tipo, numero e data (fatture: fornitore e numero). Stessi passaggi degli altri import (anteprima, conferma, registro). Le estrazioni SAP standard, se disponibili, si mappano sul modello in una fase successiva.
- **Import del Riepilogo RDA Ordini**, una volta: solo le RDA con data dal 01/04/2025 (numerazione SAP) e solo ICTDINN, cioè con un conto di un cluster del registro; le altre vanno nel report (`FUORI_PERIMETRO`). Le righe unite si ricompongono per RDA; le celle con più valori si dividono per riga (a capo); stati, date e importi si normalizzano come in §7.1 e ogni sostituzione si segnala. Contratto già registrato → si collega (stesse regole di riconoscimento dell'import dei contratti); altrimenti si crea come proposta da confermare, una tantum se non ha inizio e fine delle prestazioni. «Chiuso» diventa chiusura alla data dell'import; «Chiuso» senza attestazione è segnalato (`CHIUSO_SENZA_ATTESTAZIONE`). Il basket del masterplan non si importa. (Rev13) Ogni RDA importata ha una sola posizione (descrizione, conto, centro di costo, WBS dell'Excel; quantità 1; importo = importo base del contratto, se c'è); il «Gestore/Richiedente SAP» va nel richiedente SAP, il referente resta vuoto e si assegna dopo (anomalia `REFERENTE_MANCANTE`); nessuno storico di invio. Lo storico precedente resta nel file.
- **Import delle tabelle SAP** (Rev13, Gestione → Import, solo Admin): un file Excel con un foglio per tabella (`Richiedenti`, `Gruppi merci`, `Gruppi acquisti`), colonne codice, descrizione (per i gruppi acquisti: nome), predefinito (sì/no) e, per i gruppi merci, categoria facoltativa. Tutto o niente, idempotente per codice; nessuna cancellazione: un codice assente dal file resta com'è, si disattiva dall'amministrazione. Più di un predefinito nello stesso foglio, codici doppi o categorie inesistenti sono errori bloccanti; anteprima, conferma e registro come gli altri import.
- **Dati esistenti**: il n. RDA già registrato sui contratti diventa una RDA collegata come RDA d'origine (data migration), senza date, con il cluster del fabbisogno del contratto e senza referente (Rev13); il testo originale resta nelle note se non è un numero valido.

Import dall'interfaccia (Gestione → Import), con lo stesso codice dei comandi da riga di comando:
- tipi: Excel dei contratti, date di emissione (estrazione SAP), piano dei conti, struttura dell'ufficio (cluster, responsabili, conti, WBS, dal modello `GestioneContratti_ModelloImport_Struttura`), quadratura con l'Excel;
- carica → anteprima senza scritture (conteggi, anomalie, report) → conferma entro 24 ore, una sola volta, da chi ha caricato il file o da un Admin; registro degli import con file, hash, utente ed esito;
- permessi: contratti, date e quadratura per Admin ed Editor, che importano solo nei propri cluster; piano dei conti e struttura solo Admin;
- import della struttura: tutto o niente, idempotente, nessuna cancellazione di conti e WBS (si dismettono con fine validità o "non attiva"); il foglio Responsabili, se compilato, è l'elenco completo delle assegnazioni.

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
  - L'amministratore ha accesso completo all'amministrazione dell'applicazione; Editor e Reader lavorano dall'interfaccia operativa. Editor aggiunge e modifica i dati di dominio dei propri cluster, Reader solo legge; le tabelle di configurazione le modifica solo l'amministratore; nessuno cancella.
- **Permessi e visibilità per cluster** (F9.2):
  - i cluster si assegnano agli utenti nell'applicazione (amministrazione o import della struttura), per nome utente di dominio, anche prima del primo accesso; non con gruppi AD. Un'assegnazione `TUTTI` abilita tutti i cluster (es. addetto amministrativo). Un'assegnazione tolta si archivia;
  - l'Editor modifica solo i fabbisogni e i contratti dei cluster assegnati; spostare o accorpare tra cluster diversi richiede il permesso su entrambi. I fornitori sono in comune;
  - ogni utente vede di default i propri cluster (cruscotto, elenchi, budget, piano ordini, Spese per WBS); gli altri a richiesta, in lettura. Chi non ha cluster assegnati vede tutto;
  - **funzione «Amministrazione acquisti»** (Rev13): si assegna per nome utente di dominio, come i cluster (amministrazione o import della struttura); un'assegnazione tolta si archivia. Non è un ruolo e non dà permessi: chi la ha è di norma Editor con cluster `TUTTI`. Decide il cruscotto e le viste di default (RDA da processare, fatture da lavorare). I campi da SAP della RDA, le fatture e i documenti di esecuzione li può scrivere ogni Editor del cluster, quindi anche il referente;
  - **transizione**: finché non è mai stata registrata un'assegnazione, gli Editor modificano tutti i cluster; dalla prima assegnazione valgono le regole per cluster, anche se in seguito le assegnazioni si archiviano.
  - Un solo account locale di emergenza (break-glass), con password lunga (almeno 24 caratteri) custodita fuori dall'applicazione.
  - Tutti i parametri LDAP arrivano da variabili d'ambiente. Senza server LDAP configurato vale solo il login locale (sviluppo).
  - Il log dei login (riusciti e falliti, mai la password) si conserva 12 mesi.
  - La sessione dura al massimo 8 ore; la rimozione da un gruppo AD ha effetto al login successivo.
- **Codice**: repository GitHub privato. Lo sviluppo è gestito tramite pull request e sessioni di lavoro controllate; il merge su `main` è eseguito dal responsabile del progetto o da un assistente su richiesta esplicita, dopo revisione e CI verde.
- **Connettore MCP** (Rev10): Claude (claude.ai, Desktop, mobile, Cowork, Claude Code) interroga il registro con gli stessi numeri dell'interfaccia; da F10.1 (Rev12) Admin ed Editor possono anche scrivere, con anteprima e conferma, con le stesse validazioni e gli stessi permessi dell'interfaccia. OAuth 2.1 con login AD per utente, ruolo e visibilità per cluster come nell'interfaccia, disponibile a tutti i ruoli. Specifica, sicurezza e criteri in `docs/SPEC_MCP.md`.
- **Deploy**: manuale sul server Docker aziendale (`deploy/deploy.sh <tag>`, con dump del database prima delle migration; `docs/RUNBOOK.md`). Nessun runner CI dentro la rete aziendale nella prima fase.

### 8.2 Requisiti non funzionali

- **Dati reali mai nel repository.** Gli Excel originali, i dump e i backup restano on-prem. Nel repository ci sono solo i campioni anonimizzati in `tests/fixtures/`, che hanno la stessa struttura degli originali (anomalie comprese) ma nomi, codici e importi falsi. L'import reale si esegue sulla VM di produzione.
- **Segreti solo in variabili d'ambiente** sulla VM (`.env` non versionato). Nel repository c'è solo `.env.example`.
- **Importi** in `Decimal` (`DecimalField(max_digits=14, decimal_places=2)`), mai `float`. Arrotondamento `ROUND_HALF_UP` al centesimo; l'eventuale residuo va sull'ultima rata o sull'ultimo anno.
- **Date** di tipo `date`, senza orario. Fuso orario `Europe/Rome`.
- **Backup**: `pg_dump` giornaliero su una cartella inclusa nel backup aziendale esistente, con procedura di ripristino documentata e provata.
- **Accesso** solo dalla rete interna, dietro reverse proxy HTTPS con certificato della CA interna. Unica eccezione (Rev10): il connettore MCP (`docs/SPEC_MCP.md`), pubblicato su un host dedicato con certificato di una CA pubblica, raggiungibile solo dalla rete di uscita di Anthropic e dalla rete interna, limitato agli endpoint del protocollo MCP, dei metadati OAuth e dello scambio dei token. Login, interfaccia e amministrazione restano solo interni. Cookie `Secure` e `HttpOnly`, CSRF attivo.
- **Log applicativo** dei login riusciti e falliti.
- **Lingua dell'interfaccia**: italiano. Formati numerici e date all'italiana (1.234,56; 31/12/2026).

## 9. Decisioni ancora aperte

- ~~Budget di riferimento per il Controllo di gestione~~: deciso in F8, il riferimento è il fatturato (cassa per data fattura); la natura OPEX/CAPEX si indica sulla voce (F9.2). (Rev21) Superato: il riferimento è il consuntivo a competenza (fatture e stanziamenti).
- (Rev21) **Competenza delle fatture importate**: l'estrazione SAP settimanale non porta il periodo di competenza; le fatture importate restano `COMPETENZA_MANCANTE` finché il referente non lo indica, con imputazione provvisoria all'anno della data fattura. Da decidere: una colonna di competenza nell'estrazione annotata, o un default (per esempio il mese precedente alla data fattura).
- (Rev21) **Rate salvate senza periodo**: la previsione di una rata salvata senza periodo si imputa all'anno della data fattura, non a giorni. Da decidere: memorizzare il periodo sulla rata alla generazione.
- (Rev21) **Stanziamento in automatico**: oggi si registra a mano. Da decidere se le rate scadute senza fattura debbano proporre da sole lo stanziamento.
- (Rev21) **Connettore MCP**: la competenza si indica con `importi_fattura`; gli stanziamenti non hanno ancora strumenti di scrittura né di lettura (F12 a parte).
- **Lead time per procedura** e soglie: parametri con valori iniziali provvisori, modificabili dall'amministrazione. Non bloccano lo sviluppo; le soglie UE dei settori speciali non sono caricate.
- **Anno di imputazione dell'impegno per i contratti previsti**: il default è l'anno di inizio del servizio. Da confermare con il Procurement se preferisce l'anno della data limite di avvio.
- **IVA**: gli importi sono sempre imponibile. Da verificare se il Procurement vuole anche l'IVA nel piano ordini.
- **Mappatura dei gruppi AD e account di servizio**: da creare sul dominio.
- **Release 2.0 (Rev11)**:
  - contratto una tantum: default di inizio (data di emissione o di consegna) e durata (1 mese), che decidono la competenza;
  - significato e uso del MAP e dell'ODA/RDC rispetto al contratto SAP (oggi si registrano come documenti di esecuzione);
  - una sola RDA per pratica o più (es. RDA annullata e riemessa): il modello ne ammette più;
  - fabbisogno per le forniture una tantum: uno per acquisto o uno per categoria e cluster (es. «Forniture hardware OT»);
  - formato delle estrazioni SAP disponibili (RDA, ordini, entrate merci, fatture), per mapparle sul modello d'import;
  - soglia di RDA «ferma» (30 giorni provvisori);
  - (Rev15) campi SAP di RdC, MAP e MIGO: quelli dell'estrazione delle fatture e del commento per PAC; se ne mancano si aggiungono dopo;
  - (Rev13) se proporre il gruppo merci dalla categoria del fabbisogno (previsto, facoltativo);
  - (Rev13) notifiche mail dal portale (invio, rimando, solleciti): escluse da F11, da valutare dopo l'uso; servirebbe un relay SMTP interno.

## 10. Regole di lavoro per Claude in questo progetto

- Distinguere sempre tra requisito deciso, proposta e ipotesi. Non dare per realizzato ciò che è solo discusso.
- Ogni modifica al modello dati o alle regole di calcolo va registrata in questo documento, con una nuova revisione (Rev02, Rev03, …).
- Ogni regola di calcolo va accompagnata da almeno un caso di test numerico (input → output atteso) in `docs/TEST_CASES.md`, da riusare nei test automatici.
- Nel repository si usano solo i dati anonimizzati di `tests/fixtures/`. Se un dato reale serve e manca, segnalarlo, senza inventarlo.
- I documenti prodotti fuori dal repository seguono lo standard di nome `AAAA.MM.GG_MITTENTE_DESCRIZIONE_RevNN`. I file del repository mantengono i nomi convenzionali (`README.md`, `CLAUDE.md`, ...).
