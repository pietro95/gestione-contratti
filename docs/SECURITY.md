# Sicurezza

## Ambito

Questo documento raccoglie i principi di sicurezza del Registro contratti. Le istruzioni operative sono nel [RUNBOOK](RUNBOOK.md); i dettagli del connettore sono in [SPEC_MCP](SPEC_MCP.md).

## Classificazione e dati

L'applicazione tratta informazioni aziendali riservate relative a contratti, fornitori, budget, RDA, fatture ed esecuzione.

Nel repository:

- non devono comparire dati aziendali reali;
- fixture e screenshot devono essere anonimizzati;
- non devono essere versionati file di import, export, backup o dump;
- non devono essere versionati segreti, certificati, chiavi o file `.env`.

Le regole sono applicate anche tramite `.gitignore`, ma il controllo umano resta obbligatorio.

## Autenticazione e autorizzazione

- La produzione usa Active Directory tramite LDAPS o StartTLS con CA verificata.
- I ruoli applicativi sono Admin, Editor e Reader.
- Cluster e responsabilità limitano il perimetro dei dati.
- L'account break-glass è riservato alle emergenze, usa una password lunga e non può autorizzare MCP.
- Il login locale ordinario è ammesso solo in sviluppo.
- Ogni vista o strumento che modifica dati deve avere test negativi sui permessi.

## Protezione web

La configurazione di produzione deve mantenere:

- HTTPS terminato dal reverse proxy;
- cookie di sessione e CSRF sicuri;
- host e origini CSRF esplicitamente consentiti;
- HSTS e redirect HTTPS secondo l'architettura del proxy;
- `DEBUG = False`;
- esposizione pubblica limitata agli endpoint previsti;
- log senza segreti o contenuti sensibili non necessari.

## Connettore MCP

Il connettore è una deroga controllata all'accesso esclusivamente interno:

- usa un host dedicato;
- espone solo metadati, OAuth, token e protocollo MCP;
- usa OAuth con PKCE e scope separati per lettura e scrittura;
- applica ruolo e cluster dell'utente;
- richiede anteprima e conferma per le scritture;
- registra le chiamate;
- usa un utente PostgreSQL con privilegi ridotti;
- può essere disattivato senza spegnere l'applicazione principale.

I risultati dei tool transitano nel servizio del fornitore del modello; la minimizzazione definita in SPEC_MCP resta obbligatoria.

## Database, backup e ripristino

- PostgreSQL non espone porte verso l'host.
- Le credenziali dell'applicazione e del connettore devono essere distinte.
- I backup sono dati riservati e devono rispettare protezioni e conservazione aziendali.
- Il ripristino viene verificato automaticamente e periodicamente.
- Prima di ogni aggiornamento con impatto sui dati deve esistere un backup e un piano di rollback.

## Dipendenze e immagini

- Le dipendenze sono bloccate in `uv.lock`.
- Le immagini di produzione devono essere ricostruibili.
- Aggiornamenti di Django, OAuth, LDAP, PostgreSQL e immagini base richiedono test completi.
- Le risorse frontend sono versionate localmente: niente CDN o script remoti.

## Segnalazione di problemi

Una vulnerabilità o una possibile esposizione di dati non va descritta in una issue pubblica. Deve essere comunicata attraverso il canale interno di sicurezza dell'organizzazione e al responsabile del servizio.

La segnalazione dovrebbe includere:

- componente e versione coinvolti;
- impatto osservato o ipotizzato;
- passaggi minimi di riproduzione;
- eventuali log già privati dei dati sensibili;
- misura temporanea adottata.

## Checklist minima per una modifica

- [ ] Nessun dato reale o segreto nel diff.
- [ ] Permessi e visibilità coperti da test.
- [ ] Nuove variabili documentate in `.env.example`.
- [ ] Nuove dipendenze motivate e bloccate.
- [ ] Impatto su backup, migration e rollback valutato.
- [ ] Superficie MCP e privilegi PostgreSQL invariati o esplicitamente revisionati.
- [ ] Documentazione operativa aggiornata.
