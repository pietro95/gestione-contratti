# Connettore MCP — specifica (bozza)

> Specifica normativa del connettore. L'inquadramento architetturale è in [ARCHITECTURE](ARCHITECTURE.md), i principi di protezione in [SECURITY](SECURITY.md) e le procedure di esercizio in [RUNBOOK](RUNBOOK.md).

Rev09 — 21/10/2026 — decisioni del responsabile del progetto, da approvare. Richiamato da `docs/SPEC.md` Rev10 (§8.1, §8.2) e dalle fasi F10 e F12 di `docs/ROADMAP.md`.

Storico revisioni:
- Rev00 (05/10/2026): prima bozza, raccomandata l'opzione «solo rete interna con ponte locale».
- Rev01 (05/10/2026): decisioni del responsabile del progetto. **Deroga alla SPEC §8.2**: si espone su Internet solo il connettore MCP (§2). D3: il token vale se l'utente ha fatto login negli ultimi 7 giorni (§4.4). D4: il connettore è disponibile a tutti i ruoli. Autenticazione OAuth 2.1 con login AD solo dalla rete interna (§4).
- Rev02 (05/10/2026): decisioni del responsabile del progetto. D1 chiusa: i dati possono andare al fornitore del modello. D7: dipendenze approvate. D9 e organizzazione Claude: sono gestite dal responsabile del servizio. D5 spiegata meglio, con proposta.
- Rev03 (05/10/2026): D5 chiusa: calcoli sempre alla data di oggi. Inserita nella SPEC (Rev10) e nella ROADMAP (F10).
- Rev04 (05/10/2026): decisione del responsabile del progetto: il connettore prevede anche la scrittura (§8, sotto-fase F10.1), con anteprima e conferma in due passi, scope OAuth separato, solo Admin ed Editor. Aggiornati §1, §2.2, §4.2, §4.5, §5, §9, §10.
- Rev05 (05/10/2026): decisioni del responsabile del progetto. D11: perimetro dei gruppi A–E. D12: conferma nella chat. D13: nessun limite giornaliero di operazioni.
- Rev06 (05/10/2026): decisione del responsabile del progetto, a valle della realizzazione di F10.1: tre limiti dei tool del gruppo C (§8.2): `modifica_voce` non cambia le quote per periodo esistenti, `crea_contratto` e `modifica_contratto` non gestiscono le note, `registra_rinnovo` non genera le rate.
- Rev07 (07/10/2026): D8 chiusa con esito positivo: nella prova in produzione Claude ha accettato l'autorizzazione sull'host interno (§2.1); il piano B non serve. Nessuna decisione aperta.
- Rev08 (07/10/2026): decisioni del responsabile del progetto, **bozza da approvare**. Il connettore copre il processo d'acquisto della release 2.0 (§11, fase F12): lettura di RDA, fatture, esecuzione e viste; scrittura di tutto il processo tranne gli import (D14); presa in carico, fuori registro e assegnazione ai proposti anche su più fatture (D15); nome dei referenti esposto (D16); testi per SAP e PAC restituiti (D17). Gruppo E di §8.2 definito in §11.3.
- Rev09 (21/10/2026): decisione del responsabile del progetto, **approvata** il 21/10/2026 (SPEC Rev26). Gli strumenti di lettura che filtrano per `cluster` accettano anche `sottocluster` (id da `riferimenti`; id inesistente → errore): `budget`, `spese_wbs`, `piani_da_verificare`, `elenco_rda`, `cruscotto_acquisti`, `contratti_da_chiudere`, `stanziamenti`, `anomalie_esecuzione` (`scadenze` e `piano_ordini` lo avevano già).

## 1. Obiettivo

Permettere a Claude (claude.ai, Claude Desktop, Cowork, app mobile, Claude Code) di **interrogare il registro in linguaggio naturale** con gli stessi numeri dell'interfaccia: «quali contratti TLC vanno avviati entro marzo?», «budget OPEX 2027 dei miei cluster per fornitore», «perché il fabbisogno X non ha previsti?».

Il connettore è un **server MCP** (Model Context Protocol) che espone strumenti (*tool*) sopra i selettori e i report esistenti. Non è una seconda logica: ogni numero viene da `contratti/engine/` tramite gli stessi adapter usati dalle viste.

Due sotto-fasi: **F10** in sola lettura; **F10.1** anche in scrittura (§8), con anteprima e conferma.

Non obiettivi:
- sostituire l'export XLSX/PDF: i report formali restano quelli dell'applicazione;
- esporre l'amministrazione, gli import, le tabelle di configurazione, utenti e assegnazioni dei cluster;
- operazioni che ristrutturano più fabbisogni insieme (spostamento, accorpamento, unione dei doppioni): restano nell'interfaccia (§8.2).

## 2. Esposizione su Internet (deroga alla SPEC §8.2)

I connettori di claude.ai, Desktop, Cowork e mobile si collegano al server **dall'infrastruttura di Anthropic** (uscita dalla rete `160.79.104.0/21`), non dal PC dell'utente. Per questo serve un'esposizione pubblica. La deroga è limitata al minimo indispensabile.

**Testo proposto per la SPEC §8.2** (da recepire nella SPEC): «Accesso solo dalla rete interna. Unica eccezione: il connettore MCP (`docs/SPEC_MCP.md`), pubblicato su un host dedicato, raggiungibile solo dalla rete di uscita di Anthropic, limitato agli endpoint del protocollo MCP e dello scambio dei token OAuth. Login, interfaccia e amministrazione restano solo interni.»

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

Verificato in produzione il 07/10/2026 (D8): Claude accetta un `authorization_endpoint` su un host diverso dall'emittente (ammesso da RFC 8414) e apre nel browser la pagina di login interna; metadati e scambio dei token restano sull'host pubblico.

### 2.2 Difesa in profondità

1. **Host pubblico dedicato** (es. `mcp-contratti.<dominio pubblico>`) con certificato di una CA pubblica (Let's Encrypt da Nginx Proxy Manager): Anthropic non si fida della CA interna. Il DNS interno risolve lo stesso nome sul proxy interno (split horizon), così Claude Code usa lo stesso URL dalla rete aziendale.
2. **Allowlist IP** sul proxy (Access List di NPM) per l'host pubblico: `160.79.104.0/21` e la rete interna. Tutto il resto → 403.
3. **Allowlist di percorsi** sul proxy: solo i quattro endpoint pubblici di §2.1; ogni altro percorso → 404 senza arrivare a Django.
4. **Container separato** `mcp` nello stesso compose, stessa immagine, con impostazioni `config.settings.mcp` e `ROOT_URLCONF` che contiene **solo** quei quattro endpoint: anche con il proxy configurato male, admin e interfaccia non esistono su quel processo. Niente sessioni né CSRF lì (solo token).
5. **Utente PostgreSQL dedicato** per il container `mcp`: `SELECT` sulle tabelle di dominio e di configurazione; scrittura solo sulle tabelle dei token e del registro delle chiamate. Una falla di lettura non diventa una falla di scrittura. Con F10.1 i privilegi si estendono come in §8.3, sempre senza `DELETE` sulle tabelle di dominio diverse dalle rate.
6. **Limiti di frequenza** per token e per IP, risposta massima, timeout (§6).
7. **Verifica esterna** dopo ogni deploy (script in `deploy/`, documentato nel RUNBOOK): da un IP fuori allowlist tutto risponde 403; dall'allowlist ogni percorso fuori elenco risponde 404; `/mcp` senza token risponde 401.

### 2.3 Dati verso il fornitore del modello (D1, chiusa)

I risultati dei tool entrano nel contesto del modello e transitano dai server di Anthropic. Decisione del responsabile del progetto (Rev02): ammesso, nessuna categoria di dati esclusa per questo motivo. Le esclusioni di §5 restano per minimizzazione.

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
- Scope: `registro.lettura`; con F10.1 `registro.scrittura` (§8.1), concesso a parte nella pagina di consenso e solo ad Admin ed Editor; più `offline_access` per avere il refresh token.

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
- In F10 il connettore è **solo lettura per tutti**. Con F10.1 Admin ed Editor possono anche scrivere, con lo scope `registro.scrittura` e le regole di §8; il Reader resta in lettura.
- Visibilità per cluster identica all'interfaccia (`contratti/permessi.py`): di default i propri cluster, gli altri su richiesta esplicita con il parametro `cluster`. Chi non ha cluster assegnati vede tutto.
- La simulazione della data (`?oggi=`, solo Admin nell'interfaccia) non si espone: i calcoli usano sempre la data di oggi (D5).

## 5. Strumenti di lettura (F10)

Convenzioni comuni:
- **Importi** come stringa decimale con punto e due decimali (`"12345.60"`), mai numeri JSON: un numero JSON è un float per il client (regola 3). Il modello li presenta in formato italiano.
- **Date** ISO `AAAA-MM-GG`.
- Ogni risultato riporta `alla_data` (data di calcolo), i filtri applicati (cluster compresi) e un `link` alla pagina dell'app sull'host interno, per la verifica.
- Elenchi paginati: `limite` (default 25, max 100) e `cursore`; `troncato: true` se ci sono altri elementi. Mai risultati parziali senza dirlo.
- Anomalie ed esiti del motore (pro-rata per `Da verificare`, data di inizio mancante, quote ignorate) in `avvisi`, come nell'interfaccia.
- Ogni tool dichiara `inputSchema`, `outputSchema` e `readOnlyHint: true`.
- Ogni oggetto restituito ha `id` e `versione` (ultimo record della storia), che servono alla scrittura (§8.1).

| Tool | Argomenti | Restituisce | Riusa |
|---|---|---|---|
| `cerca` | `testo` (≥ 2 caratteri), `tipo` (contratti/fabbisogni/fornitori, facoltativo) | id, descrizione, fornitore, numero contratto, CIG, stato temporale, cluster | `views.cerca` (logica da spostare in `selettori`) |
| `scadenze` | `cluster`, `alert` (🔴 🟠 🟡), `entro` (data) | contratti e previsti in alert con data di fine, data limite, procedura, lead time, stato pratica | `selettori.cruscotto` |
| `contratto` | `id` | anagrafica, catena (predecessori, successore, confluiti), proroghe, opzioni, voci con classificazione e piano, data di fine e data limite calcolate, alert, storico pratica | adapters + `servizi.contratto_e_predecessori` / `contratto_e_successivi` |
| `fabbisogno` | `id` | descrizione, cluster, categoria, decisione di continuità, catena dei contratti, previsti calcolati con importi e date, rinnovo mancante | `adapters.previsti_fabbisogno` |
| `scadenzario` | `contratto_id` o `voce_id` | rate: numero, data fattura, pagamento stimato, importo, consuntivo, modificata a mano | modelli `Rata` |
| `budget` | `anno`, `cluster`, `sottocluster`, `natura`, `conto`, `fornitore`, `wbs`, `progetti`, `previsionali`, `raggruppa_per` (cluster, conto, fornitore, wbs, fabbisogno) | per gruppo: fatturato, ordinato, competenza × fisso, probabile, massimo; OPEX e CAPEX **separati e mai sommati**; rinnovi mancanti | `reports.budget.calcola_budget`, `raggruppa` |
| `piano_ordini` | `anno`, `cluster`, `categoria`, `natura` | righe del piano (SPEC §5.4), avvisi di frazionamento | `reports.piano_ordini.calcola_piano` |
| `spese_wbs` | `wbs_id`, `vista`, `livello`; senza WBS (elenco): `cluster`, `sottocluster`, `tipo` | contratti e importi anno per anno sulla WBS | `reports.wbs` |
| `piani_da_verificare` | `cluster`, `sottocluster` | voci con piano `Da verificare` | `selettori.voci_piano_da_verificare` |
| `fornitore` | `id` | anagrafica, contratti attivi e storici, totali per anno | viste fornitore |
| `riferimenti` | — | cluster visibili e propri, categorie, procedure con lead time e se sono proponibili per un fabbisogno (`per_fabbisogni`, Rev24), soglie valide | tabelle di configurazione |

Non esposti (minimizzazione, non serve all'uso previsto): referente (dato personale), note libere di contratti e fabbisogni (possono contenere dati imprevisti), utenti e assegnazioni, registro degli import.

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
- **Prova in produzione**, prima dell'apertura a tutti: collegamento da claude.ai e da Claude Code con un account di prova autorizzato; verifica esterna di §2.2 punto 7.

## 8. Scrittura (F10.1)

Rev04, decisione del responsabile del progetto: il connettore prevede anche la scrittura. Si realizza dopo la lettura (F10), in una sotto-fase propria (F10.1), sullo stesso server e con lo stesso OAuth.

### 8.1 Principi

1. **Stesso percorso dell'interfaccia.** Ogni tool di scrittura passa dal form Django e dal servizio che usa la vista corrispondente (es. `RinnovoForm` + `servizi.registra_rinnovo`): stesse validazioni, stessi messaggi d'errore, nessuna regola duplicata. Se una regola oggi sta solo nella vista, prima si sposta nel form o nel servizio, poi la usano entrambi.
2. **Permessi.** Scrivono solo Admin ed Editor; il Reader riceve 403 su ogni tool di scrittura (regola 9: un test per tool). Serve lo scope OAuth `registro.scrittura`, chiesto a parte nella pagina di consenso: chi collega il connettore può concedere solo la lettura. Cluster come nell'interfaccia (`permessi.verifica_oggetto`); un oggetto di un cluster non modificabile → 403 se visibile, «non trovato» se non visibile.
3. **Due passi: anteprima e conferma.** Un tool di scrittura non scrive mai: restituisce l'**anteprima** e un `id_operazione`. Scrive solo `conferma_operazione(id_operazione)`. L'anteprima contiene:
   - le modifiche campo per campo (prima → dopo) e gli oggetti che si creano;
   - gli **effetti calcolati dal motore**: data di fine, data limite e alert risultanti, rate che si generano, variazione del budget dell'anno corrente e del successivo per vista e natura, previsti che spariscono o compaiono, pratica del predecessore che passa a «Contratto attivo»;
   - gli errori di validazione (in quel caso nessun `id_operazione`) e gli avvisi.

   L'`id_operazione` vale 15 minuti (in `Parametro`), una sola volta, ed è legato a utente, tool, argomenti e versione degli oggetti toccati. Valore pratico: l'utente vede le conseguenze calcolate prima che accadano, non solo i dati che ha dettato. La descrizione dei tool chiede al modello di mostrare l'anteprima e attendere il consenso; `conferma_operazione` è l'unico tool con `destructiveHint: true`, così nelle impostazioni di Claude si può lasciare «chiedi sempre» solo su quello.
4. **Concorrenza.** I tool di lettura restituiscono la `versione` di ogni oggetto (ultimo record della storia). Se tra anteprima e conferma qualcuno ha modificato un oggetto toccato, la conferma si rifiuta e serve una nuova anteprima.
5. **Idempotenza.** Una seconda `conferma_operazione` con lo stesso id (Claude ripete le chiamate andate in timeout) restituisce l'esito della prima, senza rieseguire.
6. **Modifiche parziali.** I tool `modifica_*` cambiano solo i campi passati; un campo sconosciuto o non modificabile è un errore, mai ignorato.
7. **Atomicità.** Ogni operazione confermata è una transazione: tutto o niente.
8. **Tracciabilità.** In `django-simple-history` l'utente è la persona, il motivo `MCP <tool> <id_operazione>`. Nel registro delle chiamate (§6): anteprime, conferme, rifiuti, id degli oggetti toccati.
9. **Nessuna cancellazione** (regola 8): non esistono tool di cancellazione; `archivia` e `ripristina` sì.
10. **Freni.** Interruttore generale `mcp_scrittura_attiva` (`Parametro`, solo Admin): spegne la scrittura senza deploy, la lettura resta. L'Admin può togliere lo scope di scrittura a un collegamento senza revocare la lettura.

### 8.2 Tool di scrittura

Un oggetto principale per operazione (un contratto si crea con le sue voci e i loro piani in un'operazione sola). Argomenti con gli stessi nomi dei campi dei form; per conti, WBS, categorie e procedure si usano gli id restituiti da `riferimenti`, che con la scrittura elenca anche conti e WBS dei cluster visibili.

| Gruppo | Tool | Riusa |
|---|---|---|
| **A. Pratica e rate** | `avanza_pratica` (contratto o fabbisogno, stato, data, note); dopo F11 solo gli stati che si registrano a mano (`Offerta richiesta`, `Offerta ricevuta`) | `PassaggioPraticaForm`, `servizi.avanza_pratica` |
| | `modifica_rata` (importo, data fattura, consuntivo, numero fattura): resta marcata «modificata a mano» | `RataForm`, `servizi.salva_rata_manuale` |
| | `genera_scadenzario` (voce): rifiutato con il motivo se ci sono rate modificate a mano o consuntivate | `servizi.genera_scadenzario` |
| **B. Anagrafiche** | `crea_fornitore`, `modifica_fornitore` | `FornitoreForm` |
| | `crea_fabbisogno`, `modifica_fabbisogno` (decisione di continuità, stima, previsto manuale) | `FabbisognoForm` |
| **C. Contratti** | `crea_contratto` (anche «senza contratto»), con voci, piani e quote per periodo | `ContrattoForm`, `VoceForm`, `PianoForm` |
| | `modifica_contratto` | `ContrattoModificaForm` |
| | `registra_rinnovo` (anche senza contratto; contratti sostituiti che confluiscono) | `RinnovoForm` / `RinnovoSenzaContrattoForm`, `VoceRinnovoForm`, `servizi.registra_rinnovo` |
| | `registra_proroga` (con l'eventuale voce dell'importo) | `ProrogaForm`, `servizi.registra_proroga` |
| | `crea_voce`, `modifica_voce` (con piano e quote) | `VoceForm`, `PianoForm` |
| | `archivia`, `ripristina` (fornitore, fabbisogno, contratto, voce) | `servizi.archivia` |
| **D. Catena** | `collega_rinnovo`, `scollega_predecessore`, `confluisci`, `togli_confluenza` | `servizi.collega_rinnovo`, `scollega_predecessore`, `confluisci`, `togli_confluenza` |
| **E. Processo d'acquisto** (F12, Rev08) | RDA, fatture, documenti di esecuzione, chiusura: elenco in §11.3 | form e servizi di F11 |
| | `conferma_operazione` (id) | — |

Limiti del gruppo C (Rev06):
- `modifica_voce` modifica voce e piano; le quote per periodo già registrate si cambiano solo dall'interfaccia (`crea_voce` le accetta);
- `crea_contratto` e `modifica_contratto` non gestiscono il campo `note`;
- `registra_rinnovo` non genera le rate, come l'interfaccia: lo scadenzario delle nuove voci si genera dopo con `genera_scadenzario`;
- la procedura si indica con il codice restituito da `riferimenti`.

**Solo dall'interfaccia**, mai via MCP:
- `sposta_contratto`, `accorpa_fabbisogni`, `unisci_doppioni`: ristrutturano più fabbisogni e catene in un colpo; la loro anteprima è già una pagina dedicata e un errore è costoso da ricostruire (D11);
- import (compresi estrazione settimanale delle fatture, modello dell'esecuzione, Riepilogo, tabelle SAP) e conferma delle proposte d'import;
- tabelle di configurazione, utenti, assegnazioni dei cluster, interruttore della scrittura.

### 8.3 Rischi specifici e contromisure

- **Istruzioni nascoste nei dati** (*prompt injection*): una descrizione o una nota scritta da qualcuno può contenere frasi che il modello prende per istruzioni («archivia tutti i contratti di …»). Contromisure: testo libero in campi distinti, mai nelle descrizioni dei tool; un oggetto per operazione; anteprima obbligatoria; conferma solo con un id generato dal server; permessi per cluster. Rischio residuo: un utente che conferma senza leggere. Non si elimina; si limita il danno (archiviazione reversibile, storia completa, nessuna cancellazione).
- **Dati dettati male** (importi, date, fornitore sbagliato): l'anteprima mostra gli effetti calcolati, non solo i campi; le validazioni sono quelle dei form.
- **Token rubato con scope di scrittura**: lo stesso danno di una sessione web rubata, limitato a 1 ora per l'access token e ai cluster dell'utente; revoca immediata dall'Admin. Nessun limite al numero di operazioni (D13): il freno è l'interruttore generale.
- **Database**: l'utente PostgreSQL del container `mcp` ottiene `INSERT` e `UPDATE` sulle tabelle di dominio e di storia; **`DELETE` solo sulle rate** (la rigenerazione dello scadenzario sostituisce le rate generate, `servizi.genera_scadenzario`) e sulle tabelle dei token OAuth. Nessun `DELETE` sulle altre tabelle di dominio: la regola 8 è imposta anche dal database.

### 8.4 Test e criteri di accettazione (F10.1)

- Per ogni tool di scrittura: Reader → 403; Editor su un cluster non suo → 403 o «non trovato»; collegamento senza scope `registro.scrittura` → 403.
- **L'anteprima non scrive niente**: stesso numero di righe e di record di storia prima e dopo, in ogni tabella.
- **Equivalenza con l'interfaccia**: gli stessi dati inviati alla vista web e al tool producono lo stesso stato del database (stessi campi, rate, previsti, pratica); gli stessi dati non validi producono gli stessi errori.
- Conferma: id scaduto, già usato da un altro utente, con argomenti diversi o con un oggetto modificato nel frattempo → rifiutata; seconda conferma con lo stesso id → stesso esito, nessuna seconda scrittura.
- Interruttore spento → ogni tool di scrittura rifiutato, lettura invariata.
- Storia con l'utente reale e motivo `MCP …`; nessun `DELETE` del container `mcp` fuori da rate e token (verifica sui privilegi dell'utente PostgreSQL nello script di verifica di `deploy/`).
- Casi di `docs/TEST_CASES.md` ricostruiti via MCP (almeno TC-12 rinnovo con confluenza e TC-14 rinnovo senza contratto): anteprima e risultato coincidono con i valori attesi.

## 9. Decisioni

Prese:
- D1 (Rev02): i dati possono andare al fornitore del modello (§2.3).
- D2 (Rev01): esposizione su Internet in deroga, solo connettore (§2).
- D3 (Rev01): rinnovo del token solo con login negli ultimi 7 giorni (§4.4).
- D4 (Rev01): tutti i ruoli (§4.5).
- D6 decade: con l'esposizione pubblica Desktop usa il connettore come claude.ai.
- D5 (Rev03): calcoli sempre alla data di oggi, come nell'interfaccia; nessun parametro `alla_data`. «Cosa scade o va avviato entro il …» si ottiene con il filtro `entro` di `scadenze` e con `piano_ordini` per anno.
- D7 (Rev02): `django-oauth-toolkit` (runtime) e SDK `mcp` (solo `dev`) approvati.
- D9 (Rev02): host pubblico, DNS, firewall perimetrale e organizzazione Claude (aggiunta del connettore da parte dell'Owner) li gestisce il responsabile del servizio. Il RUNBOOK descrive cosa configurare.

- D10 (Rev04): il connettore prevede la scrittura, sotto-fase F10.1 (§8).
- D11 (Rev05): perimetro della scrittura: gruppi A–E di §8.2; spostamento, accorpamento e unione dei doppioni solo nell'interfaccia.
- D12 (Rev05): conferma nella chat, con anteprima e `conferma_operazione` (§8.1), per tutti i gruppi.
- D13 (Rev05): nessun limite al numero di operazioni confermate.

- D8 (Rev07): chiusa con esito positivo. Prova in produzione del 07/10/2026: Claude apre `/oauth/authorize/` sull'host interno indicato nei metadati, il collegamento riesce e i tool rispondono (§2.1). Il piano B (login pubblicato o IdP esterno) non serve.

- D14 (Rev08): scrittura di tutto il processo d'acquisto tranne gli import (§11.3).
- D15 (Rev08): `prendi_in_carico`, `segna_fuori_registro` e `assegna_ai_referenti_proposti` anche su più fatture, al massimo 50, con anteprima per fattura (§11.3).
- D16 (Rev08): del referente si espone solo il nome; filtri «mie» e «proposte a me» sull'utente del token (§11.1).
- D17 (Rev08): testo della richiesta, scheda SAP, indicazioni per la validazione e commento per PAC restituiti in campi propri (§11.1).

Aperte: nessuna.

## 10. Stima

Prima fase: circa una volta e mezza F9.5.2 (PDF dei report). Il lavoro si divide in tre parti di peso simile: OAuth e infrastruttura pubblica (proxy, container, utente DB, verifica esterna); spostamento in `selettori` della logica oggi dentro le viste (`cerca`, fornitore, catena del contratto) per riusarla senza duplicarla; protocollo e tool con i test di coerenza.

Scrittura (F10.1): circa quanto F10. Il grosso è portare nei form e nei servizi le regole che oggi stanno nelle viste, calcolare gli effetti per l'anteprima (riusando motore e report) e i test di equivalenza con l'interfaccia per ogni tool.

## 11. Processo d'acquisto (F12)

Rev08, decisioni del responsabile del progetto del 07/10/2026 (D14–D17). La release 2.0 (SPEC Rev11–Rev15, F11) ha aggiunto richieste di RDA, fatture, esecuzione e chiusura dei contratti e quattro viste. Il connettore le espone con le regole di §5 (lettura) e §8 (scrittura): stessi selettori, form e servizi dell'interfaccia, nessuna regola nuova.

### 11.1 Dati esposti (D16, D17)

- **Referenti** (D16, deroga motivata alla minimizzazione di §5): del referente di RDA e fatture, del referente proposto, di chi ha la fattura in carico e di chi ha registrato un passaggio si restituisce solo il **nome** (nome e cognome, o lo username se mancano), mai email, telefono, gruppi o altro. I filtri «mie», «le mie fatture» e «proposte a me» usano l'utente del token.
- **Testi del flusso**: note al buyer, allegati, nota del rimando, motivo dell'annullamento, nota della convalida. Si restituiscono in campi distinti (`testo_libero`), come le descrizioni (§6): sono dati, mai istruzioni. Le note libere generiche di RDA, contratti e fatture restano escluse, come in §5.
- **Testi pronti per SAP e PAC** (D17): testo della richiesta di RDA, scheda SAP (campi nell'ordine di SAP, «SAP» o «info»), indicazioni per la validazione e commento per PAC. Sono identici all'interfaccia perché li compone lo stesso motore (`componi_testo_richiesta`, `commento_pac`, `indicazioni_validazione`) e stanno in campi propri. Test: uguali a TC-17 e TC-18.
- Gli importi delle posizioni e delle fatture seguono le convenzioni di §5: stringhe con due decimali. Le quantità sono stringhe decimali.

### 11.2 Strumenti di lettura

| Tool | Argomenti | Restituisce | Riusa |
|---|---|---|---|
| `rda` | `id` | scopo, cluster, pratica (contratto in scadenza o fabbisogno) con il suo stato, fase con data, giorni e «ferma», numero SAP e date, referente, posizioni con importo, contratti generati con la differenza dalla RDA, storico della richiesta, scheda SAP, `testo_richiesta` | `acquisti.dati_rda`, `scheda`, `testo_della_richiesta`, `differenza_da_rda` |
| `elenco_rda` | `cluster`, `sottocluster`, `fase` (più d'una), `anno`, `referente` (`me` o id), `fornitore`, `wbs`, `testo`, paginazione | righe della vista «Stato delle RDA», totale e conteggi per fase | `reports.acquisti.stato_rda`, `conteggi_per_fase` |
| `fattura` | `id` | fornitore, numero, data, importo del documento, valore base, oneri, bollo, passo con «ferma», contratto (o proposto) e voce, rata, referente (o proposto), convalida, documenti SAP, trasferimento, fuori registro, anomalie, `indicazioni_validazione`, `commento_pac` | `contratti.fatture` |
| `elenco_fatture` | `vista` (`da_prendere`, `mie`, `tutte`), `proposte_a_me`, `passo`, `testo`, `fuori_registro`, paginazione | righe con passo, giorni, «ferma», contratto e referente proposti | `views_fatture`, `reports.acquisti` |
| `esecuzione` | `contratto_id` | fatturato, residuo sul fisso e sul massimo, avanzamento, motivo «da chiudere», anomalie del contratto e delle fatture, fatture con il passo, documenti di esecuzione | `acquisti.riepilogo_esecuzione`, `fatture.anomalie` |
| `cruscotto_acquisti` | `cluster`, `sottocluster` | RDA da processare per azione con le ferme, fatture da lavorare per passo, contratti da chiudere | `reports.acquisti` |
| `contratti_da_chiudere` | `cluster`, `sottocluster` | righe con motivo, fatturato e residui | `reports.acquisti.contratti_da_chiudere` |
| `stanziamenti` | `cluster`, `sottocluster`, `contratto_id` | rate scadute senza fattura proposte allo stanziamento (importo e competenza proposti) e stanziamenti registrati; totali proposto e stanziato | `contratti.stanziamenti.proposte`, `m.Stanziamento` |
| `anomalie_esecuzione` | `cluster`, `sottocluster` | contratti e fatture con le anomalie, conteggi | `reports.acquisti.anomalie_esecuzione`, `conteggi_anomalie` |

Tool esistenti estesi:
- `contratto`: RDA d'origine, tipo d'acquisto, una tantum, RUP, CUP, chiusura;
- `fabbisogno`: richieste di RDA;
- `cerca`: anche RDA e fatture (numero, RdC, MAP, MIGO), come la ricerca globale;
- `riferimenti`: richiedenti SAP, gruppi acquisti e gruppi merci attivi con il predefinito, tipi d'acquisto, scopi della RDA.

Vincolo verificabile, come in §5: **per gli stessi filtri, `elenco_rda`, `contratti_da_chiudere` e `anomalie_esecuzione` danno gli stessi totali e conteggi della vista web e dell'export XLSX.**

### 11.3 Strumenti di scrittura (gruppo E di §8.2, D14)

Tutto il processo d'acquisto si fa dalla chat con anteprima e conferma (§8.1), **tranne gli import** (estrazione settimanale delle fatture, modello dell'esecuzione, Riepilogo, tabelle SAP), che restano solo nell'interfaccia come gli altri import (§8.2). Permessi come nell'interfaccia:
- la RDA la modifica chi modifica nel suo cluster;
- una fattura senza contratto la modificano chi la ha in carico, l'addetto e l'Admin; una fattura abbinata, chi modifica nel cluster del contratto;
- la convalida la registrano chi ha la fattura in carico e l'Admin;
- assegnare ad altri e riassegnare spetta all'Admin e all'addetto.

| Area | Tool | Riusa | Effetti nell'anteprima |
|---|---|---|---|
| **RDA** | `crea_rda` (fabbisogno; scopo, contratto in scadenza e posizioni proposti dal fabbisogno se non indicati; `invia` sì/no) | `RichiestaForm`, `PosizioniFormSet`, `acquisti.proposta_richiesta`, `crea_richiesta`, `invia` | fase risultante, stato della pratica, testo della richiesta |
| | `modifica_rda` (campi e posizioni: nuove o modificate, nessuna cancellazione; dopo l'invio è una correzione diretta, segnalata) | `salva_richiesta`, `correzione_diretta` | differenze, importo |
| | `invia_rda`, `rimanda_rda` (nota), `annulla_rda` (motivo) | `acquisti.invia`, `rimanda`, `annulla` | fase e stato della pratica risultanti |
| | `dati_sap_rda` (numero, inserimento, rilascio) | `DatiSapForm`, `aggiorna_dati_sap` | fase, stato della pratica, contratti con lo stesso n. RDA proposti |
| | `registra_rda` (già in SAP, a mano) | `RdaManualeForm` | — |
| | `collega_rda` (pratica, contratto generato, scollega) | `collega_pratica`, `collega_contratto`, `scollega_contratto` | stato della pratica |
| | `registra_contratto_da_rda` | `ContrattoDaRdaForm`, `VociDaRdaFormSet`, `registra_contratto_da_rda` | contratto, voci e rate, predecessore, differenza dalla RDA, effetti di §8.1 (fine, data limite, budget, previsti) |
| **Fatture** | `registra_fattura` (a mano; dal contratto già abbinata) | `FatturaForm`, `fatture.registra` | passo |
| | `prendi_in_carico` (**più fatture**, D15), `segna_fuori_registro` (**più fatture**, sì/no) | `fatture.prendi_in_carico`, `segna_fuori_registro` | per ogni fattura: presa o rifiutata e perché |
| | `assegna_ai_referenti_proposti` (**più fatture**; Admin e addetto) | `fatture.assegna_ai_proposti` | referente per fattura, quelle senza proposta |
| | `lascia_fattura`, `riassegna_fattura` (Admin e addetto) | `fatture.lascia`, `riassegna` | — |
| | `assegna_contratto_fattura` (contratto, voce; o scollega) | `ContrattoFatturaForm`, `fatture.assegna_contratto` | passo, fatturato e residuo del contratto |
| | `convalida_fattura` (esito, nota, bloccata fino al) | `ConvalidaForm`, `fatture.convalida` | passo |
| | `importi_fattura` (valore base, oneri, bollo, competenza dal/al, voce, rata) | `ImportiForm`, `fatture.aggiorna_importi` | `IMPORTO_NON_QUADRA`, fatturato e residuo, rata che diventa consuntivo, commento per PAC |
| | `documento_fattura` (RdC, MAP, MIGO) | `DocumentoFatturaForm`, `fatture.registra_documento` | passo, commento per PAC |
| | `trasferisci_fattura` (data; o annulla) | `TrasferimentoForm`, `fatture.trasferisci`, `annulla_trasferimento` | passo |
| **Esecuzione** | `documento_esecuzione` (DDT, attestazione, modello di ricezione, finale) | `DocumentoEsecuzioneForm` | motivo «da chiudere» |
| **Stanziamenti** (Rev09) | `registra_stanziamento` (voce, importo, competenza dal/al, rata) | `StanziamentoForm` | budget a competenza dei cluster toccati |
| | `stanzia_rate` (fino a 50 rate) | `stanziamenti.conferma` | budget, stanziamenti creati |
| | `chiudi_stanziamento` (fattura), `annulla_stanziamento` | `ChiudiStanziamentoForm`, archiviazione | budget |
| | `chiudi_contratto`, `annulla_chiusura` | `acquisti.chiudi`, `annulla_chiusura` | fase delle RDA, anomalie (`CHIUSO_SENZA_ATTESTAZIONE`) |

**Operazioni su più fatture (D15)**: eccezione esplicita alla regola «un oggetto principale per operazione» (§8.2), solo per `prendi_in_carico`, `segna_fuori_registro` e `assegna_ai_referenti_proposti`:
- al massimo 50 fatture per operazione;
- l'anteprima elenca le fatture che passano e quelle rifiutate con il motivo;
- la conferma applica solo le prime, in una transazione;
- la versione di ogni fattura vale per la concorrenza: una fattura cambiata dopo l'anteprima rende la conferma rifiutata per intero.

### 11.4 Rischi specifici

- **Dati da SAP nei campi di testo**: nomi dei fornitori e numeri di fattura arrivano dall'estrazione settimanale. Sono testo di terzi, quindi la regola di §6 vale anche per loro.
- **Operazioni multiple**: una richiesta mal interpretata («prendi tutte quelle di …») tocca più fatture in un colpo. Contromisure: limite di 50, anteprima che le elenca una per una, presa in carico solo per sé (assegnare ad altri è dell'Admin e dell'addetto), operazioni reversibili («lascia», «rimetti nel registro»).
- **Testi per SAP e PAC**: il modello potrebbe riscriverli invece di copiarli. La descrizione dei tool chiede di riportarli tali e quali; il campo resta quello del server.

### 11.5 Test e criteri di accettazione (F12)

- Per ogni tool nuovo valgono §7 (lettura) e §8.4 (scrittura):
  - Reader → 403 sulla scrittura;
  - cluster non propri → 403 o «non trovato»;
  - l'anteprima non scrive;
  - equivalenza con la vista web (stesso stato del database, stessi errori);
  - conferme scadute, ripetute o su oggetti cambiati gestite.
- Casi ricostruiti via MCP:
  - **TC-15**: fasi della RDA e stato della pratica;
  - **TC-16**: esecuzione, residuo e chiusura;
  - **TC-17**: `testo_richiesta` identico;
  - **TC-18**: presa in carico multipla con il rifiuto «già in carico a …», referente proposto, convalida bloccata, commento per PAC identico.
- `elenco_rda`, `contratti_da_chiudere` e `anomalie_esecuzione` uguali alla vista web e all'export XLSX.
- Operazioni multiple: oltre 50 fatture → errore; conferma rifiutata per intero se una fattura è cambiata.
- Nessun dato dei referenti oltre al nome; nessuna nota libera generica nelle risposte.
- `ruff`, `pytest`, `makemigrations --check` puliti.

### 11.6 Stima

Circa quanto F10.1: la logica c'è già tutta in `contratti/acquisti.py`, `contratti/fatture.py` e `reports/acquisti.py`. Il grosso è nelle anteprime con gli effetti (fase, passo, residuo, commento per PAC dopo la modifica) e nei test di equivalenza per circa 25 tool di scrittura. Proposta in due sotto-fasi:
- **F12.1**: lettura ed estensioni dei tool esistenti;
- **F12.2**: scrittura.

## Fonti

- Anthropic, «Authentication for connectors»: https://claude.com/docs/connectors/building/authentication (requisiti OAuth, callback, rete di uscita).
- Anthropic, «IP addresses»: https://platform.claude.com/docs/en/api/ip-addresses (`160.79.104.0/21`).
- Centro assistenza Claude, articolo 11175166, connettori personalizzati con MCP remoto (connessione dal cloud Anthropic).
