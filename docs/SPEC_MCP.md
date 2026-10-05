# Connettore MCP — specifica (bozza)

Rev00 — 05/10/2026 — proposta scritta da Claude, da approvare da Pietro Verro. Nulla di quanto segue è deciso finché non entra in `docs/SPEC.md` (nuova revisione) e in `docs/ROADMAP.md` (nuova fase).

## 1. Obiettivo

Permettere a un assistente AI (Claude Desktop, Claude Code) di **interrogare il registro in linguaggio naturale** con gli stessi numeri dell'interfaccia: «quali contratti TLC vanno avviati entro marzo?», «budget OPEX 2027 dei miei cluster per fornitore», «perché il fabbisogno X non ha previsti?».

Il connettore è un **server MCP** (Model Context Protocol) che espone strumenti (*tool*) sopra i selettori e i report esistenti. Non è una seconda logica: ogni numero viene da `contratti/engine/` tramite gli stessi adapter usati dalle viste.

Non obiettivi (prima fase):
- scrivere dati di dominio (vedi §7, fase successiva);
- sostituire l'export XLSX/PDF: i report formali restano quelli dell'applicazione;
- esporre l'amministrazione, gli import, le tabelle di configurazione in scrittura.

## 2. Vincolo di rete: da dove arriva la connessione

Questo è il punto che decide l'architettura.

- I **connettori personalizzati** di claude.ai, Claude Desktop, Cowork e app mobile si collegano al server MCP **dall'infrastruttura cloud di Anthropic**, non dal PC dell'utente: il server deve essere raggiungibile da Internet (dagli IP di Anthropic). Fonte: centro assistenza Claude, articolo 11175166 «custom connectors using remote MCP».
- La SPEC §8.2 stabilisce invece: **accesso solo dalla rete interna**.

Le due cose sono incompatibili. Alternative:

| | Architettura | Rete | Client | Giudizio |
|---|---|---|---|---|
| **A** | Endpoint MCP HTTP nell'app, pubblicato su Internet con OAuth e allowlist IP di Anthropic | Viola §8.2: serve una deroga formale, esposizione pubblica dell'app | claude.ai, Desktop, mobile | Sconsigliata |
| **B** | Endpoint MCP HTTP nell'app, **solo rete interna**; sul PC un ponte locale *stdio* che lo chiama | Rispetta §8.2 | Claude Desktop (server locale), Claude Code (HTTP diretto, senza ponte) | **Raccomandata** |
| **C** | Server MCP locale che legge il database direttamente | Rispetta §8.2, ma credenziali DB sui PC e permessi per cluster da riscrivere | Desktop, Code | Scartata |

Raccomandazione: **B**. Confidenza alta sul vincolo di rete (documentato da Anthropic); media sul fatto che Claude Desktop continui a supportare i server locali *stdio* nella forma attuale (estensioni `.mcpb` o `claude_desktop_config.json`): va verificato all'avvio della fase.

**Conseguenza da non sottovalutare**: in qualunque architettura i risultati dei tool entrano nel contesto del modello e quindi transitano dai server di Anthropic. Il vincolo «solo rete interna» protegge l'app da accessi esterni, **non** impedisce che i dati interrogati escano verso il fornitore del modello. Serve una decisione esplicita (§9, D1) su quali dati possono uscire e con quale contratto/piano Claude dell'azienda.

## 3. Architettura (opzione B)

```
PC utente                                   Server Docker aziendale
┌──────────────────────┐   HTTPS (rete     ┌──────────────────────────────┐
│ Claude Desktop       │   interna, CA     │ Nginx Proxy Manager          │
│  └ ponte stdio ──────┼── interna) ──────▶│  └ gunicorn / Django         │
│ Claude Code ─────────┼──────────────────▶│      POST /mcp  (app `mcp/`) │
└──────────────────────┘  Bearer token     │      └ selettori, reports,   │
                                           │        engine (sola lettura) │
                                           └──────────────────────────────┘
```

- **Server**: nuova app Django `mcp/` con una sola vista `POST /mcp`, trasporto *Streamable HTTP* in modalità **stateless, solo risposte JSON** (niente SSE, niente sessioni lato server). Compatibile con gunicorn WSGI così com'è.
- **Protocollo**: JSON-RPC 2.0, metodi `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Nessuna *resource*, *prompt* o *sampling* in prima fase. Versione del protocollo: l'ultima stabile all'avvio della fase, fissata in una costante e verificata con un test.
- **Implementazione**: a mano in Django (≈ 300 righe: parsing JSON-RPC, validazione argomenti con JSON Schema dichiarato nel tool, serializzazione). Motivo: l'SDK ufficiale `mcp` è ASGI (Starlette/anyio) e non si innesta su gunicorn WSGI senza cambiare il server applicativo. L'SDK si usa **solo nei test** (gruppo `dev`) come client, per verificare la conformità reale. Dipendenza fuori stack da motivare nella PR.
- **Ponte locale per Claude Desktop**: script Python minimo, distribuito come estensione `.mcpb` o voce in `claude_desktop_config.json`, che inoltra stdio ↔ `POST /mcp` aggiungendo il token. Alternativa senza codice nostro: `mcp-remote` (npm), da valutare: aggiunge Node sui PC.
- **Claude Code**: `claude mcp add --transport http registro https://<host>/mcp --header "Authorization: Bearer …"`, nessun ponte.

## 4. Autenticazione e autorizzazione

La sessione Django (cookie, 8 ore, login LDAP) non va bene per un client MCP. Si introducono **token personali**.

- Modello `TokenMcp`: utente, nome (es. «Desktop portatile»), hash SHA-256 del token (il token in chiaro si mostra una volta sola), prefisso visibile per riconoscerlo, creato il, scade il, ultimo uso, revocato. Nessuna cancellazione: si revoca (regola 8).
- Generazione dalla pagina profilo dell'utente; revoca dall'utente o dall'Admin. Durata massima configurabile da `Parametro` (proposta: 90 giorni), mai costante nel codice (regola 7).
- A ogni chiamata: token valido, non scaduto, non revocato, utente attivo, **ruolo presente** (`role_of`). Senza ruolo → 403.
- **Problema aperto (D3)**: il ruolo deriva dai gruppi AD e si aggiorna solo al login (SPEC §8.1). Con un token di 90 giorni, chi viene tolto da `GG_Contratti_*` mantiene l'accesso via MCP finché non rientra. Opzioni: (a) il token vale solo se l'utente ha fatto login web negli ultimi N giorni; (b) verifica dei gruppi AD con l'account di servizio a ogni chiamata, con cache breve; (c) durata breve (7 giorni). Proposta: **(a) con N = 7**, semplice e senza traffico LDAP aggiuntivo.
- **Permessi**: il token ha i permessi dell'utente, ristretti a **sola lettura** in prima fase anche per Admin ed Editor. Visibilità per cluster identica all'interfaccia (`contratti/permessi.py`): default i propri cluster, altri su richiesta esplicita con il parametro `cluster`. Chi non ha cluster assegnati vede tutto, come nell'interfaccia.
- La simulazione della data (`?oggi=`, solo Admin) non si espone: i tool calcolano sempre a `date.today()` (D5).
- Il break-glass non può creare token.

## 5. Strumenti (prima fase, sola lettura)

Convenzioni comuni:
- **Importi** come stringa decimale con punto e due decimali (`"12345.60"`), mai numeri JSON: un numero JSON è un float per il client (regola 3). Il modello li presenta in formato italiano.
- **Date** ISO `AAAA-MM-GG`.
- Ogni risultato include `alla_data` (la data di calcolo), i filtri effettivamente applicati (cluster compresi) e un `link` alla pagina corrispondente dell'app, perché l'utente verifichi sull'interfaccia.
- Elenchi paginati: `limite` (default 25, max 100) e `cursore`; il risultato dichiara `troncato: true` se ci sono altri elementi. Mai risultati parziali senza dirlo.
- Anomalie ed esiti del motore (es. pro-rata per `Da verificare`, data di inizio mancante, quote ignorate) si riportano in `avvisi`, come nell'interfaccia: il modello non deve presentare un numero «sporco» come pulito.
- Ogni tool dichiara `inputSchema` e `outputSchema` JSON e l'annotazione `readOnlyHint: true`.

| Tool | Argomenti | Restituisce | Riusa |
|---|---|---|---|
| `cerca` | `testo` (≥ 2 caratteri), `tipo` (contratti/fabbisogni/fornitori, facoltativo) | id, descrizione, fornitore, numero contratto, CIG, stato temporale, cluster | `views.cerca` (logica da spostare in `selettori`) |
| `scadenze` | `cluster`, `alert` (🔴 🟠 🟡), `entro` (data) | contratti e previsti in alert con data di fine, data limite, procedura, lead time, stato pratica | `selettori.cruscotto` |
| `contratto` | `id` | anagrafica, catena (predecessori, successore, confluiti), proroghe, opzioni, voci con classificazione e piano, data di fine e data limite calcolate, alert, storico pratica | adapters + `servizi.contratto_e_predecessori` / `contratto_e_successivi` |
| `fabbisogno` | `id` | descrizione, cluster, categoria, decisione di continuità, catena dei contratti, previsti calcolati con importi e date, rinnovo mancante | `adapters.previsti_fabbisogno` |
| `scadenzario` | `contratto_id` o `voce_id` | rate: numero, data fattura, pagamento stimato, importo, consuntivo, modificata a mano | modelli `Rata` |
| `budget` | `anno`, `cluster`, `natura`, `conto`, `fornitore`, `wbs`, `progetti`, `previsionali`, `raggruppa_per` (cluster, conto, fornitore, wbs, fabbisogno) | per gruppo: le tre viste (fatturato, ordinato, competenza) × livelli (fisso, probabile, massimo), OPEX e CAPEX **separati e mai sommati**; rinnovi mancanti | `reports.budget.calcola_budget`, `raggruppa` |
| `piano_ordini` | `anno`, `cluster`, `categoria`, `natura` | righe del piano (§5.4), avvisi di frazionamento | `reports.piano_ordini.calcola_piano` |
| `spese_wbs` | `wbs_id`, `vista`, `livello` | contratti e importi anno per anno sulla WBS | `reports.wbs` |
| `piani_da_verificare` | `cluster` | voci con piano `Da verificare` | `selettori.voci_piano_da_verificare` |
| `fornitore` | `id` | anagrafica, contratti attivi e storici, totali per anno | viste fornitore |
| `riferimenti` | — | cluster visibili e propri, categorie, procedure con lead time, soglie valide: serve al modello per costruire i filtri | tabelle di configurazione |

Non esposti: referente (dato personale) salvo decisione contraria (D1); utenti e assegnazioni; registro degli import; note libere dei contratti (possono contenere dati non previsti) salvo decisione contraria.

Vincolo di coerenza, verificabile: **per gli stessi filtri e la stessa data, `budget` e `piano_ordini` restituiscono gli stessi totali al centesimo della vista web e dell'export XLSX.** Se non coincidono è un difetto.

## 6. Registro, limiti, errori

- **Registro delle chiamate**: utente, token (prefisso), tool, argomenti, esito, durata, numero di elementi restituiti; mai il contenuto del risultato. Conservazione 12 mesi, come il log dei login. Consultabile dall'Admin.
- **Limiti**: richieste per minuto per token (proposta 60), dimensione massima della risposta (proposta 200 KB, poi `troncato`), timeout del calcolo allineato a gunicorn. Valori in `Parametro`.
- **Errori**: argomenti non validi → errore JSON-RPC `-32602` con messaggio in italiano; oggetto inesistente o fuori dai cluster visibili → stesso errore «non trovato» (non si rivela l'esistenza); token assente o non valido → HTTP 401; ruolo assente → HTTP 403.
- **Sicurezza dei contenuti**: descrizioni e note sono testo scritto da utenti e finiscono nel contesto del modello. In sola lettura il rischio di *prompt injection* è basso (nessuna azione possibile); diventa rilevante con la scrittura (§7). Il testo libero si restituisce in campi distinti, mai concatenato alle istruzioni del tool.

## 7. Fase successiva: scrittura (da decidere dopo l'uso della prima)

Solo dopo almeno un mese di uso in lettura. Candidati, in ordine di rischio crescente:
1. `avanza_pratica` (passaggio di stato con note): utile, reversibile con un nuovo passaggio.
2. `marca_consuntivo` su una rata.
3. Registrazione di proroghe e rinnovi: **no via MCP**, troppi controlli di coerenza e la conferma umana avviene meglio nell'interfaccia.

Regole per qualunque tool di scrittura: stesso controllo `permessi.verifica_oggetto` delle viste; test del 403 per il Reader (regola 9); modifica registrata in `django-simple-history` con motivo «via MCP, token …»; annotazione `destructiveHint`; il client chiede conferma all'utente prima di eseguire.

## 8. Test e criteri di accettazione (prima fase)

- Conformità: un client MCP reale (SDK ufficiale, solo test) esegue `initialize`, `tools/list` e ogni `tools/call` contro il server di test.
- Coerenza dei numeri: per i casi di `docs/TEST_CASES.md` già coperti dai report, `budget` e `piano_ordini` via MCP danno gli stessi valori dei test esistenti.
- Importi sempre stringhe con due decimali; nessun `float` nella serializzazione (test che fallisce se compare).
- Autorizzazione: token scaduto, revocato, di utente disattivato o senza ruolo → 401/403; Reader e Editor vedono solo i cluster previsti; un oggetto di un cluster non visibile risponde «non trovato».
- Ogni chiamata compare nel registro; il token in chiaro non compare mai nei log né nel database.
- Nessuna chiamata esterna dal server (regola: niente servizi esterni).
- `ruff`, `pytest`, `makemigrations --check` puliti.
- RUNBOOK: configurazione del proxy per `/mcp`, generazione del token, configurazione di Claude Desktop e Claude Code.

## 9. Decisioni da prendere (Pietro)

- **D1 — Dati verso il fornitore del modello.** I risultati dei tool vanno ad Anthropic. Serve verificare il piano Claude aziendale (conservazione dei dati, uso per addestramento) e decidere se escludere categorie di dati (referenti, note, importi?). Senza questa decisione la fase non parte. Confidenza alta che la questione esista; la risposta dipende dal contratto, che non conosco.
- **D2 — Architettura.** B (rete interna, Desktop con ponte locale, Code diretto) oppure A (esposizione su Internet con deroga a §8.2). Raccomando B.
- **D3 — Validità del ruolo con il token** (§4): proposta login web negli ultimi 7 giorni.
- **D4 — Chi può avere un token**: tutti i ruoli o solo Admin ed Editor in un primo periodo.
- **D5 — Data di calcolo**: sempre oggi, oppure parametro `alla_data` per tutti (utile per «come sarà il cruscotto a gennaio?»). La simulazione oggi è riservata all'Admin nell'interfaccia.
- **D6 — Ponte per Claude Desktop**: script Python nostro (`.mcpb`) o `mcp-remote` (Node).
- **D7 — Dipendenza di test**: SDK `mcp` nel gruppo `dev` per i test di conformità.

## 10. Stima

Prima fase (sola lettura, §3–§6, §8): una fase della dimensione di F9.5.2 (PDF dei report). Il lavoro grosso è spostare in `selettori` la logica oggi dentro le viste (`cerca`, fornitore, catena del contratto) per riusarla senza duplicarla; il protocollo in sé è piccolo.
