# Connettore MCP — specifica (bozza)

Rev01 — 05/10/2026 — proposta scritta da Claude, da approvare da Pietro Verro. Nulla di quanto segue è deciso finché non entra in `docs/SPEC.md` (nuova revisione) e in `docs/ROADMAP.md` (nuova fase).

Storico revisioni:
- Rev00 (05/10/2026): prima bozza, raccomandata l'opzione «solo rete interna con ponte locale».
- Rev01 (05/10/2026): decisioni di Pietro. **Deroga alla SPEC §8.2**: si espone su Internet solo il connettore MCP (§2). D3: il token vale se l'utente ha fatto login negli ultimi 7 giorni (§4.4). D4: il connettore è disponibile a tutti i ruoli. Autenticazione OAuth 2.1 con login AD solo dalla rete interna (§4).

## 1. Obiettivo

Permettere a Claude (claude.ai, Claude Desktop, Cowork, app mobile, Claude Code) di **interrogare il registro in linguaggio naturale** con gli stessi numeri dell'interfaccia: «quali contratti TLC vanno avviati entro marzo?», «budget OPEX 2027 dei miei cluster per fornitore», «perché il fabbisogno X non ha previsti?».

Il connettore è un **server MCP** (Model Context Protocol) che espone strumenti (*tool*) sopra i selettori e i report esistenti. Non è una seconda logica: ogni numero viene da `contratti/engine/` tramite gli stessi adapter usati dalle viste.

Non obiettivi (prima fase):
- scrivere dati di dominio (§8, fase successiva);
- sostituire l'export XLSX/PDF: i report formali restano quelli dell'applicazione;
- esporre l'amministrazione, gli import, le tabelle di configurazione in scrittura.

## 2. Esposizione su Internet (deroga alla SPEC §8.2)

I connettori di claude.ai, Desktop, Cowork e mobile si collegano al server **dall'infrastruttura di Anthropic** (uscita dalla rete `160.79.104.0/21`), non dal PC dell'utente. Per questo serve un'esposizione pubblica. La deroga è limitata al minimo indispensabile.

**Testo proposto per la SPEC §8.2** (lo inserisce Pietro): «Accesso solo dalla rete interna. Unica eccezione: il connettore MCP (`docs/SPEC_MCP.md`), pubblicato su un host dedicato, raggiungibile solo dalla rete di uscita di Anthropic, limitato agli endpoint del protocollo MCP e dello scambio dei token OAuth. Login, interfaccia e amministrazione restano solo interni.»

### 2.1 Cosa è pubblico e cosa no

| Endpoint | Chi lo chiama | Esposto su Internet |
|---|---|---|
| `POST /mcp` | cloud Anthropic; Claude Code dal PC | **Sì** |
| `GET /.well-known/oauth-protected-resource` (RFC 9728) | cloud Anthropic | **Sì** |
| `GET /.well-known/oauth-authorization-server` (RFC 8414) | cloud Anthropic | **Sì** |
| `POST /oauth/token` (scambio del codice e refresh) | cloud Anthropic | **Sì** |
| `GET /oauth/authorize` + login AD + consenso | **browser dell'utente** (redirect) | **No**: solo rete interna |
| Interfaccia, `/admin/`, `/accounts/`, import, report | browser | **No** |

Il punto chiave: l'autorizzazione è un redirect nel browser dell'utente, quindi la pagina di login e consenso resta sull'host interno. **Il login AD non è mai esposto.** Conseguenza: il collegamento del connettore (e la sua ripetizione ogni 7 giorni, §4.4) si fa dalla rete aziendale o da VPN. Una volta collegato, Claude lo usa anche da fuori (es. app mobile), perché le chiamate passano dal cloud di Anthropic.

Confidenza media che Claude accetti un `authorization_endpoint` su un host diverso dall'emittente (RFC 8414 lo ammette; la documentazione Anthropic dice che il server di autorizzazione può stare su un host diverso dal server MCP, ma non tratta questo caso). Primo test da fare all'avvio della fase; se fallisce, piano B in §9 (D8).

### 2.2 Difesa in profondità

1. **Host pubblico dedicato** (es. `mcp-contratti.<dominio pubblico>`) con certificato di una CA pubblica (Let's Encrypt da Nginx Proxy Manager): Anthropic non si fida della CA interna. Il DNS interno risolve lo stesso nome sul proxy interno (split horizon), così Claude Code usa lo stesso URL dalla rete aziendale.
2. **Allowlist IP** sul proxy (Access List di NPM) per l'host pubblico: `160.79.104.0/21` e la rete interna. Tutto il resto → 403.
3. **Allowlist di percorsi** sul proxy: solo i quattro endpoint pubblici di §2.1; ogni altro percorso → 404 senza arrivare a Django.
4. **Container separato** `mcp` nello stesso compose, stessa immagine, con impostazioni `config.settings.mcp` e `ROOT_URLCONF` che contiene **solo** quei quattro endpoint: anche con il proxy configurato male, admin e interfaccia non esistono su quel processo. Niente sessioni né CSRF lì (solo token).
5. **Utente PostgreSQL dedicato** per il container `mcp`: `SELECT` sulle tabelle di dominio e di configurazione; scrittura solo sulle tabelle dei token e del registro delle chiamate. Una falla di lettura non diventa una falla di scrittura.
6. **Limiti di frequenza** per token e per IP, risposta massima, timeout (§6).
7. **Verifica esterna** dopo ogni deploy (script in `deploy/`, documentato nel RUNBOOK): da un IP fuori allowlist tutto risponde 403; dall'allowlist ogni percorso fuori elenco risponde 404; `/mcp` senza token risponde 401.

### 2.3 Dati verso il fornitore del modello (D1, aperta)

I risultati dei tool entrano nel contesto del modello e transitano dai server di Anthropic. La deroga di rete non cambia questo fatto, ma lo rende operativo. Prima di andare in produzione serve verificare il piano Claude aziendale (conservazione, uso per addestramento) e decidere se escludere categorie di dati (§5, «non esposti»).

## 3. Architettura

```
                      Internet                         Server Docker aziendale
claude.ai / Desktop  ┌───────────────┐  HTTPS, CA    ┌──────────────────────────────────┐
mobile / Cowork ───▶ │ cloud         │  pubblica,    │ Nginx Proxy Manager              │
                     │ Anthropic     │──allowlist───▶│  host pubblico ─▶ container mcp  │
                     │160.79.104.0/21│  IP+percorsi  │   /mcp /oauth/token /.well-known │
                     └───────────────┘               │  host interno  ─▶ container web  │
browser utente (LAN) ── /oauth/authorize, login AD ─▶│   interfaccia, /oauth/authorize  │
Claude Code (LAN) ───── /mcp, /oauth/token ─────────▶│                                  │
                                                     │ PostgreSQL (utente mcp limitato) │
                                                     └──────────────────────────────────┘
```

- **Server MCP**: nuova app Django `mcp/`, vista `POST /mcp`, trasporto *Streamable HTTP* **stateless, solo risposte JSON** (niente SSE, niente sessioni): gira su gunicorn WSGI così com'è. `GET /mcp` → 405.
- **Protocollo**: JSON-RPC 2.0, metodi `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Nessuna *resource*, *prompt* o *sampling* in prima fase. Versione del protocollo: l'ultima stabile all'avvio della fase (oggi 2025-11-25, da riverificare), in una costante, con test.
- **Implementazione del protocollo**: a mano (≈ 300 righe). L'SDK ufficiale `mcp` è ASGI e non si innesta su gunicorn WSGI; si usa **solo nei test** come client di conformità (D7).
- **Server di autorizzazione OAuth**: dentro Django, con `django-oauth-toolkit` (dipendenza fuori stack, da motivare nella PR: implementare OAuth a mano è il punto dove un errore costa di più). Gli endpoint RFC 9728 e RFC 8414 sono JSON statici scritti da noi. Da verificare all'avvio che la versione di `django-oauth-toolkit` supporti rotazione dei refresh token e PKCE S256 come richiesto (§4.2); confidenza alta, non verificata sul codice.

## 4. Autenticazione e autorizzazione

### 4.1 Perché OAuth e non un token fisso

Claude accetta tre modi: OAuth, credenziale fissa in un header (beta, inserita dall'Owner dell'organizzazione Claude e **uguale per tutti gli utenti**), nessuna autenticazione. La credenziale fissa non identifica la persona: salterebbero la visibilità per cluster, il ruolo e il registro per utente. Scartata. Resta OAuth 2.1, con login AD per utente.

### 4.2 Requisiti del client OAuth di Claude (dalla documentazione Anthropic)

- `/mcp` senza token valido → **HTTP 401** con `WWW-Authenticate: Bearer resource_metadata="https://<host>/.well-known/oauth-protected-resource"`. Il `200` con `WWW-Authenticate` è ignorato.
- Nei metadati della risorsa: `resource` **identico** all'URL inserito in Claude (con il percorso `/mcp`); `authorization_servers` con un solo elemento.
- Metadati del server di autorizzazione raggiungibili dal cloud Anthropic; `code_challenge_methods_supported: ["S256"]`. PKCE S256 obbligatorio.
- Redirect URI ammessi: `https://claude.ai/api/mcp/auth_callback` (app ospitate; possibile cambio futuro in `https://claude.com/api/mcp/auth_callback`, da accettare entrambi) e, per Claude Code, `http://localhost/callback` e `http://127.0.0.1/callback` **con qualunque porta**.
- `/oauth/token` accetta `application/x-www-form-urlencoded`, risponde entro 10 secondi; refresh token **ruotati**; refresh non più valido → errore `invalid_grant`.
- Scope: `registro.lettura` (unico in prima fase), più `offline_access` per avere il refresh token.

### 4.3 Registrazione del client

Niente registrazione dinamica (DCR): aprirebbe un endpoint pubblico di creazione di client. Si usano **client pre-registrati** dall'Admin:
- **Claude (app ospitate)**: client confidenziale, redirect `claude.ai`/`claude.com`. ID e secret si inseriscono nelle *Impostazioni avanzate* del connettore personalizzato, quando l'Owner dell'organizzazione Claude lo aggiunge.
- **Claude Code**: client pubblico (senza secret) con redirect loopback. Da verificare all'avvio come Claude Code riceve un client ID pre-registrato (opzione di `claude mcp add` o CIMD con l'ID `https://claude.ai/oauth/claude-code-client-metadata` registrato a mano, senza scaricare il documento: niente chiamate esterne dal server).

### 4.4 Validità e ruolo (D3, decisa)

- Codice di autorizzazione: 60 secondi, uso singolo. Access token: 1 ora. Refresh token: ruotato a ogni uso.
- **Regola D3**: il refresh riesce solo se l'ultimo login interattivo dell'utente (interfaccia web o pagina di autorizzazione OAuth) è di **non più di 7 giorni** prima. Altrimenti `invalid_grant`: Claude chiede di ricollegare il connettore, l'utente rifà il login AD dalla rete interna e ruolo e gruppi si riallineano. Effetto: chi viene tolto da un gruppo `GG_Contratti_*` perde l'accesso via MCP entro 7 giorni più 1 ora al massimo; per un'esclusione immediata l'Admin revoca i token o disattiva l'utente.
- A **ogni** chiamata: token valido e non revocato, utente attivo, ruolo presente (`role_of`). Senza ruolo → 403.
- Durate (7 giorni, 1 ora) in `Parametro`, non costanti (regola 7 di CLAUDE.md).
- Revoca: l'utente dalla sua pagina «Connettore MCP» (elenco dei collegamenti, ultimo uso, revoca); l'Admin per qualunque utente. Nessuna cancellazione: i token scadono o si revocano.
- Il break-glass non può autorizzare il connettore.

### 4.5 Permessi (D4, decisa)

- **Tutti i ruoli** (Admin, Editor, Reader) possono collegare il connettore.
- In prima fase il connettore è **solo lettura per tutti**, anche per Admin ed Editor.
- Visibilità per cluster identica all'interfaccia (`contratti/permessi.py`): di default i propri cluster, gli altri su richiesta esplicita con il parametro `cluster`. Chi non ha cluster assegnati vede tutto.
- La simulazione della data (`?oggi=`, solo Admin nell'interfaccia) non si espone (D5).

## 5. Strumenti (prima fase, sola lettura)

Convenzioni comuni:
- **Importi** come stringa decimale con punto e due decimali (`"12345.60"`), mai numeri JSON: un numero JSON è un float per il client (regola 3). Il modello li presenta in formato italiano.
- **Date** ISO `AAAA-MM-GG`.
- Ogni risultato riporta `alla_data` (data di calcolo), i filtri applicati (cluster compresi) e un `link` alla pagina dell'app sull'host interno, per la verifica.
- Elenchi paginati: `limite` (default 25, max 100) e `cursore`; `troncato: true` se ci sono altri elementi. Mai risultati parziali senza dirlo.
- Anomalie ed esiti del motore (pro-rata per `Da verificare`, data di inizio mancante, quote ignorate) in `avvisi`, come nell'interfaccia.
- Ogni tool dichiara `inputSchema`, `outputSchema` e `readOnlyHint: true`.

| Tool | Argomenti | Restituisce | Riusa |
|---|---|---|---|
| `cerca` | `testo` (≥ 2 caratteri), `tipo` (contratti/fabbisogni/fornitori, facoltativo) | id, descrizione, fornitore, numero contratto, CIG, stato temporale, cluster | `views.cerca` (logica da spostare in `selettori`) |
| `scadenze` | `cluster`, `alert` (🔴 🟠 🟡), `entro` (data) | contratti e previsti in alert con data di fine, data limite, procedura, lead time, stato pratica | `selettori.cruscotto` |
| `contratto` | `id` | anagrafica, catena (predecessori, successore, confluiti), proroghe, opzioni, voci con classificazione e piano, data di fine e data limite calcolate, alert, storico pratica | adapters + `servizi.contratto_e_predecessori` / `contratto_e_successivi` |
| `fabbisogno` | `id` | descrizione, cluster, categoria, decisione di continuità, catena dei contratti, previsti calcolati con importi e date, rinnovo mancante | `adapters.previsti_fabbisogno` |
| `scadenzario` | `contratto_id` o `voce_id` | rate: numero, data fattura, pagamento stimato, importo, consuntivo, modificata a mano | modelli `Rata` |
| `budget` | `anno`, `cluster`, `natura`, `conto`, `fornitore`, `wbs`, `progetti`, `previsionali`, `raggruppa_per` (cluster, conto, fornitore, wbs, fabbisogno) | per gruppo: fatturato, ordinato, competenza × fisso, probabile, massimo; OPEX e CAPEX **separati e mai sommati**; rinnovi mancanti | `reports.budget.calcola_budget`, `raggruppa` |
| `piano_ordini` | `anno`, `cluster`, `categoria`, `natura` | righe del piano (SPEC §5.4), avvisi di frazionamento | `reports.piano_ordini.calcola_piano` |
| `spese_wbs` | `wbs_id`, `vista`, `livello` | contratti e importi anno per anno sulla WBS | `reports.wbs` |
| `piani_da_verificare` | `cluster` | voci con piano `Da verificare` | `selettori.voci_piano_da_verificare` |
| `fornitore` | `id` | anagrafica, contratti attivi e storici, totali per anno | viste fornitore |
| `riferimenti` | — | cluster visibili e propri, categorie, procedure con lead time, soglie valide | tabelle di configurazione |

Non esposti, salvo decisione contraria (D1): referente (dato personale), note libere di contratti e fabbisogni (possono contenere dati imprevisti), utenti e assegnazioni, registro degli import.

Vincolo verificabile: **per gli stessi filtri e la stessa data, `budget` e `piano_ordini` restituiscono gli stessi totali al centesimo della vista web e dell'export XLSX.** Una differenza è un difetto.

## 6. Registro, limiti, errori

- **Registro delle chiamate**: utente, client, tool, argomenti, esito, durata, IP di origine, numero di elementi; mai il contenuto del risultato né il token. Conservazione 12 mesi, come il log dei login. Consultabile dall'Admin. Anche le emissioni, i refresh e i rifiuti di token si registrano.
- **Limiti** (in `Parametro`): richieste al minuto per token (proposta 60) e per IP sul token endpoint (proposta 30); risposta massima (proposta 200 KB, poi `troncato`); timeout del calcolo sotto quello di gunicorn.
- **Errori**: argomenti non validi → JSON-RPC `-32602` con messaggio in italiano; oggetto inesistente o fuori dai cluster visibili → stesso «non trovato» (non si rivela l'esistenza); token assente, scaduto o revocato → HTTP 401 con `WWW-Authenticate`; ruolo assente → HTTP 403.
- **Contenuti scritti dagli utenti**: descrizioni e note finiscono nel contesto del modello. In sola lettura il rischio di *prompt injection* è basso (nessuna azione possibile); diventa rilevante con la scrittura (§8). Il testo libero si restituisce in campi distinti, mai concatenato alle descrizioni dei tool.

## 7. Test e criteri di accettazione (prima fase)

- **Conformità MCP**: un client reale (SDK ufficiale, solo test) esegue `initialize`, `tools/list` e ogni `tools/call` contro il server di test.
- **Flusso OAuth completo nei test**: 401 con `resource_metadata` → metadati → authorize con PKCE S256 → token → chiamata → refresh con rotazione; vecchio refresh rifiutato con `invalid_grant`; redirect non ammesso rifiutato; loopback accettato su qualunque porta.
- **Regola D3**: refresh rifiutato con ultimo login di 8 giorni prima, accettato con 6.
- **URLconf del container `mcp`**: contiene solo i quattro endpoint pubblici (test che elenca le route).
- **Coerenza dei numeri**: per i casi di `docs/TEST_CASES.md` coperti dai report, `budget` e `piano_ordini` via MCP danno gli stessi valori dei test esistenti.
- Importi sempre stringhe con due decimali; nessun `float` nella serializzazione (test che fallisce se compare).
- **Autorizzazione**: token scaduto, revocato, di utente disattivato o senza ruolo → 401/403; Reader ed Editor vedono solo i cluster previsti; oggetto di un cluster non visibile → «non trovato».
- Ogni chiamata nel registro; token in chiaro mai nei log né nel database (solo hash).
- Nessuna chiamata esterna dal server.
- `ruff`, `pytest`, `makemigrations --check` puliti.
- **RUNBOOK**: host pubblico su NPM (certificato, Access List, percorsi), DNS split horizon, utente PostgreSQL limitato, creazione dei client OAuth, aggiunta del connettore in Claude da parte dell'Owner, collegamento dell'utente, revoca, script di verifica esterna.
- **Prova in produzione**, prima dell'apertura a tutti: collegamento da claude.ai e da Claude Code di Pietro; verifica esterna di §2.2 punto 7.

## 8. Fase successiva: scrittura (da decidere dopo l'uso della prima)

Solo dopo almeno un mese di uso in lettura. Candidati, in ordine di rischio crescente:
1. `avanza_pratica` (passaggio di stato con note): utile, reversibile con un nuovo passaggio.
2. `marca_consuntivo` su una rata.
3. Registrazione di proroghe e rinnovi: **no via MCP**, troppi controlli di coerenza; la conferma umana avviene meglio nell'interfaccia.

Regole per qualunque tool di scrittura: scope OAuth separato (`registro.scrittura`), solo Admin ed Editor; stesso controllo `permessi.verifica_oggetto` delle viste; test del 403 per il Reader (regola 9); modifica in `django-simple-history` con motivo «via MCP»; annotazione `destructiveHint`; il permesso di scrittura del database per il container `mcp` si estende solo alle tabelle toccate.

## 9. Decisioni

Prese (Rev01): D2 esposizione su Internet in deroga, solo connettore; D3 login negli ultimi 7 giorni; D4 tutti i ruoli. D6 (ponte locale per Desktop) decade: con l'esposizione pubblica Desktop usa il connettore come claude.ai.

Aperte:
- **D1 — Dati verso il fornitore del modello** (§2.3). Blocca l'apertura in produzione, non lo sviluppo.
- **D5 — Data di calcolo**: sempre oggi, oppure parametro `alla_data` per tutti (utile per «come sarà il cruscotto a gennaio?»).
- **D7 — Dipendenze**: `django-oauth-toolkit` (runtime) e SDK `mcp` (solo `dev`, test di conformità).
- **D8 — Piano B se Claude non accetta l'authorize su host interno** (§2.1): pubblicare anche `/oauth/authorize` e il login (esposizione del login AD su Internet, sconsigliata), oppure delegare il login a un IdP già pubblico, se Siciliacque ne ha uno (Entra ID/ADFS): da verificare.
- **D9 — Nome dell'host pubblico** e dominio su cui crearlo; chi in azienda gestisce DNS pubblico e firewall perimetrale.
- **Organizzazione Claude**: il connettore personalizzato lo aggiunge un Owner dell'organizzazione Claude di Siciliacque. Da verificare chi è e su quale piano.

## 10. Stima

Prima fase: circa una volta e mezza F9.5.2 (PDF dei report). Il lavoro si divide in tre parti di peso simile: OAuth e infrastruttura pubblica (proxy, container, utente DB, verifica esterna); spostamento in `selettori` della logica oggi dentro le viste (`cerca`, fornitore, catena del contratto) per riusarla senza duplicarla; protocollo e tool con i test di coerenza.

## Fonti

- Anthropic, «Authentication for connectors»: https://claude.com/docs/connectors/building/authentication (requisiti OAuth, callback, rete di uscita).
- Anthropic, «IP addresses»: https://platform.claude.com/docs/en/api/ip-addresses (`160.79.104.0/21`).
- Centro assistenza Claude, articolo 11175166, connettori personalizzati con MCP remoto (connessione dal cloud Anthropic).
