# Runbook — Registro contratti ICTDINN in produzione

Installazione, aggiornamento ed esercizio sul **server Docker aziendale già in uso** (Ubuntu),
condiviso con altri applicativi di produzione. Ogni comando si può copiare così com'è; le parti
da adattare sono indicate come `<SEGNAPOSTO>`.

## 0. Principi

- **Tutto in una cartella**: `/appdata/gestione-contratti`. Fuori da lì si tocca solo la
  configurazione del reverse proxy esistente, Nginx Proxy Manager (§5).
- **Nessun impatto sugli altri container**:
  - gli script usano solo il progetto Docker Compose `gestione-contratti` (container
    `gestione-contratti-*`, rete `gestione-contratti_interna`, immagini `gestione-contratti:*`);
  - l'app ascolta su una porta non standard scelta da te (`APP_PORT`), solo su `127.0.0.1`
    salvo diversa scelta (`APP_BIND`); il database non espone porte;
  - nessun volume Docker con nome: i dati sono cartelle sotto `/appdata/gestione-contratti`.
- **Si installano versioni**, cioè tag git (`v1.0`, `v1.1`, …), mai modifiche a mano del codice
  sul server.

Struttura:

| Cartella | Contenuto |
|---|---|
| `app/` | codice (checkout git): non si modifica a mano |
| `config/.env` | configurazione e password (permessi 600) |
| `config/certs/ca-interna.pem` | certificato della CA interna, per LDAPS |
| `postgres/` | dati del database |
| `backup/` | dump giornalieri e pre-aggiornamento |
| `import/` | Excel e CSV da importare, report delle anomalie (nel container: `/import`) |

Il backup della VM copre l'intera cartella, dump compresi (§8).

## 1. Prerequisiti (una volta)

Sul server ci sono già Docker Engine e il plugin Compose. Verifica:

```bash
docker --version && docker compose version && git --version && curl --version | head -1
```

L'utente che installa deve poter usare Docker (gruppo `docker`) e scrivere in `/appdata`.

## 2. Cartella e codice

Il repository è privato: per scaricarlo dal server si usa una **deploy key** in sola lettura.

```bash
ssh-keygen -t ed25519 -N "" -C "deploy gestione-contratti" -f ~/.ssh/gestione-contratti_deploy
cat ~/.ssh/gestione-contratti_deploy.pub
```

Su GitHub: repository → Settings → Deploy keys → Add deploy key, incolla la chiave pubblica,
**senza** "Allow write access". Poi:

```bash
cat >> ~/.ssh/config <<'FINE'
Host github-gestione-contratti
  HostName github.com
  User git
  IdentityFile ~/.ssh/gestione-contratti_deploy
  IdentitiesOnly yes
FINE
sudo mkdir -p /appdata/gestione-contratti
sudo chown "$USER": /appdata/gestione-contratti
cd /appdata/gestione-contratti
git clone github-gestione-contratti:pietro95/gestione-contratti.git app
mkdir -p config/certs postgres backup import
```

## 3. Configurazione (`config/.env`)

```bash
cd /appdata/gestione-contratti
cp app/.env.example config/.env
chmod 600 config/.env
```

**Porta**: scegli una porta libera e non standard. Controlla che nessuno la usi:

```bash
ss -ltn | grep -w <PORTA> || echo "libera"
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -w <PORTA> || echo "nessun container"
```

Genera password e chiave (solo caratteri esadecimali, niente da codificare negli URL):

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"   # DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(24))"   # password del database
```

Modifica `config/.env` (`nano config/.env`). Valori da impostare:

| Variabile | Valore |
|---|---|
| `APP_PORT` | la porta scelta |
| `APP_BIND` | `127.0.0.1` se nginx gira sull'host; se nginx è in un container, l'IP con cui quel container raggiunge l'host (es. `172.17.0.1`) |
| `DJANGO_SECRET_KEY` | la chiave generata |
| `DJANGO_ALLOWED_HOSTS` | il nome DNS dell'app, es. `contratti.siciliacque.local` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` + lo stesso nome |
| `POSTGRES_PASSWORD` e la password dentro `DATABASE_URL` | la password generata, identica nei due punti |
| `LDAP_*` | i parametri di Active Directory (vedi i commenti nel file) |
| `LDAP_GROUP_ADMIN/EDITOR/READER` | i DN dei gruppi AD dei ruoli |
| `BACKUP_ORA`, `BACKUP_GIORNI` | ora del dump giornaliero e giorni di conservazione |

### 3.1 Certificato della CA interna e verifica di LDAPS

L'app si fida dei domain controller tramite il certificato **pubblico** della CA aziendale
(AD CS): `config/certs/ca-interna.pem`. Nessuna chiave privata.

1. **Esporta la CA**, da un server o PC Windows del dominio:
   - sul server CA: `certutil -ca.cert ca-interna.cer`;
   - oppure `certlm.msc` → Autorità di certificazione radice attendibili → la CA → Esporta →
     *Codificato Base-64 X.509 (.cer)*.

   Se i certificati sono emessi da una CA **subordinata**, servono entrambe: radice e
   subordinata nello stesso file.
2. **Sul server Docker**:
   ```bash
   # Base-64: basta copiarlo; binario (DER): va convertito
   openssl x509 -inform der -in ca-interna.cer -out ca-interna.pem 2>/dev/null || cp ca-interna.cer ca-interna.pem
   # con una subordinata: cat radice.pem subordinata.pem > ca-interna.pem
   cp ca-interna.pem /appdata/gestione-contratti/config/certs/ca-interna.pem
   ```
3. **Verifica ogni DC** che metterai in `LDAP_SERVER_URI`, con il nome DNS completo, mai l'IP:
   ```bash
   openssl s_client -connect <dc01.dominio>:636 -CAfile ca-interna.pem \
     -verify_hostname <dc01.dominio> -verify_return_error </dev/null 2>/dev/null | grep "Verify return code"
   ```
   L'esito deve essere `Verify return code: 0 (ok)`. Gli altri casi:

   | Codice | Significato e rimedio |
   |---|---|
   | `20`, `21` | catena incompleta: manca la CA subordinata nel file |
   | `62` | il nome usato non è nel certificato del DC: usa il nome DNS completo |
   | `66` (`EE certificate key too weak`) | il certificato del DC ha una chiave < 2048 bit. Ubuntu e il container la rifiutano: va riemesso, vedi sotto |

   **Riemettere il certificato dei DC con chiave a 2048 bit** (sulla CA):
   1. `certtmpl.msc`: duplica il modello *Kerberos Authentication* (o *Domain Controller
      Authentication*) e imposta:
      - in *Crittografia*, dimensione minima 2048;
      - in *Modelli sostituiti*, i modelli vecchi;
      - in *Sicurezza*, Domain Controllers con Registrazione e Registrazione automatica.
   2. `certsrv.msc` → Modelli di certificato → Nuovo → Modello di certificato da emettere.
   3. Su ogni DC: `certutil -pulse`, poi verifica in `certlm.msc` → Personale.
   4. Il DC usa il nuovo certificato dopo il riavvio, oppure subito con
      `renewServerCertificate`:
      - apri `ldp.exe` → Modify, DN vuoto;
      - attributo `renewServerCertificate`, valore `1`, Add.
   5. Ripeti la verifica del punto 3.

## 4. Primo avvio

La versione da installare è un tag git (lo crea Pietro su GitHub: Releases → Draft a new
release, oppure `git tag v1.0 && git push origin v1.0`).

```bash
/appdata/gestione-contratti/app/deploy/deploy.sh v1.0
```

Lo script:
1. controlla configurazione e porta;
2. scarica la versione;
3. costruisce l'immagine;
4. avvia il database;
5. applica le migration;
6. avvia app e backup;
7. attende che `/healthz` risponda.

Al termine stampa `Installata la versione v1.0.`

Verifica:

```bash
cd /appdata/gestione-contratti/app/deploy && source comune.sh && compose ps
```

Devono comparire `gestione-contratti-db-1`, `-web-1` e `-backup-1`, tutti `Up`, con `db` e
`web` `(healthy)`.

## 5. Reverse proxy

L'app serve da sola anche i file statici (CSS, JavaScript): il proxy deve solo terminare HTTPS e
inoltrare **tutto** a `APP_BIND:APP_PORT`, senza regole per `/static/`.

Preliminari comuni:
1. **DNS**: record A per il nome scelto (es. `contratti.siciliacque.it`) verso il server.
2. **Certificato dalla CA interna**: richiesta con il nome nel SAN.
   ```bash
   openssl req -new -newkey rsa:3072 -nodes -keyout contratti.key -out contratti.csr \
     -subj "/CN=<NOME_DNS>" -addext "subjectAltName=DNS:<NOME_DNS>"
   ```
   Consegna `contratti.csr` alla CA (modello Web Server). La chiave resta sul server, leggibile
   solo da root.

### 5.1 Nginx Proxy Manager (il proxy in uso)

Nginx Proxy Manager gira in un container, quindi non raggiunge `127.0.0.1` dell'host. Nel `.env`:
- `APP_BIND` = indirizzo dell'host raggiungibile dal container del proxy. Il gateway del bridge
  Docker si trova con:
  ```bash
  docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'
  ```
  Di solito è `172.17.0.1`. Se il proxy usa un'altra rete Docker, prendi il gateway di quella rete.
- Mai `0.0.0.0` senza firewall: esporrebbe l'app senza HTTPS su tutta la rete.

Nell'interfaccia di Nginx Proxy Manager:
1. **SSL Certificates** → Add SSL Certificate → **Custom**: carica la chiave e il certificato.
   Se la CA ha una subordinata, carica come certificato il file con certificato più subordinata.
2. **Hosts → Proxy Hosts** → Add Proxy Host:
   - **Details**:
     - Domain Names: `<NOME_DNS>`;
     - Scheme: `http`;
     - Forward Hostname/IP: `APP_BIND`;
     - Forward Port: `APP_PORT`;
     - attiva *Block Common Exploits*.
   - **SSL**: il certificato appena caricato, *Force SSL* e *HTTP/2 Support* attivi.
   - **Custom locations** e **Advanced**: vuoti.

     Nginx Proxy Manager invia già `X-Forwarded-Proto`, l'header da cui Django capisce che la
     connessione è HTTPS. Se in futuro serve caricare file più grandi di 1 MB, in Advanced va
     aggiunto `client_max_body_size 20m;`.
3. Salva: il proxy si ricarica senza interrompere gli altri siti.

### 5.2 Nginx con file di configurazione (alternativa)

Parti da `app/deploy/nginx/gestione-contratti.conf.esempio`. Sostituisci `__SERVER_NAME__`,
`__APP_UPSTREAM__` (`APP_BIND:APP_PORT`), `__CERT__` e `__KEY__`, poi:
```bash
sudo cp /appdata/gestione-contratti/app/deploy/nginx/gestione-contratti.conf.esempio \
  /etc/nginx/sites-available/gestione-contratti.conf
sudo nano /etc/nginx/sites-available/gestione-contratti.conf
sudo ln -s /etc/nginx/sites-available/gestione-contratti.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 5.3 Verifica

Da un PC della rete:
- `https://<NOME_DNS>/healthz` risponde `{"status": "ok"}`;
- `http://<NOME_DNS>` rimanda a `https://`;
- la pagina di login appare con lo stile, non come testo semplice.

Dal server:
```bash
curl -sk -o /dev/null -w "%{http_code} %{content_type}\n" \
  https://<NOME_DNS>/static/vendor/bootstrap-5.3.8/bootstrap.min.css
```
Esito atteso: `200 text/css`.

## 6. Primo utilizzo

I comandi applicativi si lanciano con `deploy/manage.sh`, che li esegue nel container:

```bash
cd /appdata/gestione-contratti/app/deploy
```

### 6.0 Avvio temporaneo senza Active Directory

Se LDAPS non è ancora pronto (§3.1), l'app parte con gli account locali:
1. Lascia `LDAP_SERVER_URI=` vuota nel `.env`. All'avvio compare l'avviso `accounts.W001`:
   è atteso.
2. Crea il tuo account amministratore:
   ```bash
   ./manage.sh createsuperuser
   ```
3. Da Amministrazione → Utenti crea gli account dei colleghi:
   - **nome utente identico a quello di dominio** (il sAMAccountName, in minuscolo, es. `pverro`);
   - il gruppo **Admin**, **Editor** o **Reader**.
4. Quando LDAPS è pronto:
   1. imposta `LDAP_SERVER_URI=ldaps://<dc>:636` e le altre variabili `LDAP_*`;
   2. riavvia: `source comune.sh && compose restart web`;
   3. crea l'account di emergenza (§6, punto 1).

   Da quel momento si entra solo con le credenziali di dominio. Ogni account locale con lo
   stesso nome diventa l'utente di dominio, con il suo storico; il ruolo viene dai gruppi AD
   e la password locale non vale più. Gli account locali con nomi diversi non entrano più:
   disattivali da Amministrazione → Utenti (togli *Attivo*).

1. **Account di emergenza (break-glass)**: l'unico accesso locale ammesso con LDAP attivo. La
   password si digita, non passa da variabili; custodiscila come da procedura aziendale.
   ```bash
   ./manage.sh crea_breakglass
   ```
2. **Login con le credenziali di dominio**: entra con un utente di ciascun gruppo AD. Il ruolo
   compare in alto a destra (Admin, Editor, Reader). Chi non è in alcun gruppo non entra.
**Import dall'interfaccia (dalla v1.2).** Gli import dei passi 3, 4 e 5 si fanno anche dal
menu **Gestione → Import**, senza accedere al server: carichi il file, vedi l'anteprima (nulla
è scritto), poi confermi. Ogni scheda ha il suo modello XLSX da scaricare. Excel dei contratti,
date di emissione e quadratura li usano Admin ed Editor; il piano dei conti solo l'Admin. Ogni
file resta nel registro degli import, con chi l'ha caricato, l'anteprima e l'esito. I comandi
qui sotto restano per l'emergenza: fanno la stessa cosa con lo stesso codice.

3. **Piano dei conti**: prepara un CSV con le colonne `codice;descrizione;valido_dal` (e,
   facoltativa, `valido_al`; date `gg/mm/aaaa`), mettilo in
   `/appdata/gestione-contratti/import/` e caricalo:
   ```bash
   ./manage.sh import_conti /import/piano_conti.csv --dry-run
   ./manage.sh import_conti /import/piano_conti.csv
   ```
4. **Import degli Excel reali** (copia i file in `/appdata/gestione-contratti/import/`):
   ```bash
   ./manage.sh import_excel /import/<Contratti_IT.xlsx> --area IT --dry-run
   ./manage.sh import_excel /import/<Contratti_IT.xlsx> --area IT
   ./manage.sh import_excel /import/<Contratti_TLC.xlsx> --area TLC --dry-run
   ./manage.sh import_excel /import/<Contratti_TLC.xlsx> --area TLC
   ```
   Il report delle anomalie (`*_anomalie_import.csv`) compare accanto al file.
   **Date di emissione dei contratti**: gli Excel non le hanno. Estrai da SAP l'elenco dei
   contratti con numero e data di emissione, salvalo in CSV o XLSX con le colonne
   `numero_contratto` e `data_emissione` (date `gg/mm/aaaa`, `gg.mm.aaaa` o `aaaa-mm-gg`) e
   caricalo. Riempie solo le date vuote; le date diverse da quelle già registrate e i numeri
   non trovati sono elencati a video, senza modifiche:
   ```bash
   ./manage.sh import_date_contratti /import/date_contratti.csv --dry-run
   ./manage.sh import_date_contratti /import/date_contratti.csv
   ```
   Finché la data manca, l'"Ordinato" di quel contratto cade nell'anno di inizio del servizio.
5. **Quadratura con l'Excel**:
   ```bash
   ./manage.sh quadratura_excel /import/<Contratti_IT.xlsx> --area IT
   ```
   Produce `*_quadratura.xlsx` in `import/`.
6. **Proposte dell'import**: dall'app, menu "Proposte import", conferma o scarta i
   raggruppamenti e poi i predecessori.
7. **Configurazione** (admin dell'app): verifica soglie, lead time e parametri, che sono valori
   provvisori.
8. **Piani di fatturazione**: dall'app, menu "Piani da verificare". Le voci importate hanno il
   piano `Da verificare` e il loro fatturato è stimato a pro-rata: imposta modalità e
   periodicità reali partendo dalle voci più pesanti, poi genera lo scadenzario.

### 6.1 Struttura ICTDINN: cluster, responsabili, conti e WBS (dalla v1.5)

Si carica dall'app, solo come Admin: menu "Import" → "Struttura ICTDINN".

1. Scarica il modello dalla scheda ("Scarica il modello":
   `2026.10.02_PFE_Modello_import_struttura_ICTDINN_Rev00.xlsx`) e compila i fogli Cluster,
   Responsabili, Conti e WBS. La colonna «Controllo» deve essere vuota su tutte le righe.
2. Carica il file e leggi l'anteprima: conteggi e anomalie, nessuna scrittura. Poi conferma.
3. Verifica nel report:
   - `CONTO_SENZA_CLUSTER`: conti del registro che non sono nel foglio Conti;
   - `WBS_NON_IN_STRUTTURA`: WBS scritte a testo nelle voci, assenti dal foglio WBS;
   - `WBS_SU_OPEX`: voci OPEX con una WBS a testo, da correggere a mano.
4. Effetti:
   - dal primo responsabile caricato, ogni Editor modifica solo i fabbisogni dei suoi
     cluster (o di tutti con `TUTTI`), anche se in seguito le assegnazioni si archiviano.
     Prima del caricamento gli Editor modificano tutto;
   - dopo il caricamento ogni conto deve avere un cluster: le voci non accettano conti senza
     cluster (il report li elenca come `CONTO_SENZA_CLUSTER`);
   - un responsabile tolto dal foglio perde le assegnazioni, che restano archiviate. Se il
     foglio Responsabili è vuoto, le assegnazioni non cambiano;
   - le assegnazioni si correggono anche in "Amministrazione" → "Assegnazioni di cluster".

Rieseguire l'import con lo stesso file non cambia nulla. Conti e WBS non si cancellano:
per dismetterli compila `valido_al` (conti) o metti `No` in `attiva` (WBS).

## 7. Aggiornamento e rollback

**Aggiornamento**:

```bash
/appdata/gestione-contratti/app/deploy/deploy.sh v1.1
```

Prima di tutto fa un dump `..._pre_v1.1.dump` in `backup/`. Se un passo fallisce lo script si
ferma:
- se si ferma **prima delle migration** (controlli, download, build), nulla è cambiato e l'app
  continua con la versione precedente;
- se si ferma **dopo**, il database ha già il nuovo schema: correggi la causa e rilancia, oppure
  fai il rollback qui sotto.

**Rollback**:
- se la nuova versione **non** ha migration del database:
  `deploy.sh v1.0`;
- se le ha (indicato nella descrizione della PR o della release):
  1. ripristina il dump pre-aggiornamento (`deploy/restore.md` §2):
     ```bash
     /appdata/gestione-contratti/app/deploy/ripristina.sh <AAAA.MM.GG_HHMM_contratti_pre_v1.1.dump>
     ```
  2. reinstalla la versione precedente: `deploy.sh v1.0`.

  I dati inseriti dopo l'aggiornamento si perdono: annotali prima.

## 8. Backup

- **Automatico**: il container `gestione-contratti-backup-1` esegue ogni giorno alle
  `BACKUP_ORA` un `pg_dump`, lo verifica (`pg_restore --list`) e cancella i dump più vecchi di
  `BACKUP_GIORNI`. I file sono in `/appdata/gestione-contratti/backup/`.
- Perché anche il dump, oltre al backup della VM: copiare a caldo la cartella `postgres/` dà
  una copia coerente solo se lo snapshot è istantaneo su tutto il disco. Il dump è sempre
  coerente, e il backup della VM lo conserva nel tempo.
- **Manuale** (prima di operazioni rischiose):
  ```bash
  /appdata/gestione-contratti/app/deploy/backup.sh <etichetta>
  ```
- **Controllo**: `ls -lt /appdata/gestione-contratti/backup | head`. Gli errori del backup sono
  nel log:
  ```bash
  cd /appdata/gestione-contratti/app/deploy && source comune.sh && compose logs backup
  ```
- **Prova di ripristino** (consigliata ogni mese e dopo ogni aggiornamento importante):
  ```bash
  /appdata/gestione-contratti/app/deploy/verifica_ripristino.sh
  ```
  Ripristina l'ultimo dump in un database temporaneo e confronta i conteggi, senza toccare
  quello in uso.

## 9. Certificati

- **Certificato del sito** (nginx): controlla la scadenza:
  ```bash
  sudo openssl x509 -enddate -noout -in <PERCORSO_CERT>
  ```
  Per il rinnovo, nuova CSR come al §5.2. Sostituisci i file, poi
  `sudo nginx -t && sudo systemctl reload nginx`. L'app non va riavviata.
- **CA interna per LDAPS**: se la CA cambia, sostituisci
  `/appdata/gestione-contratti/config/certs/ca-interna.pem` e riavvia l'app:
  ```bash
  cd /appdata/gestione-contratti/app/deploy && source comune.sh && compose restart web
  ```
- **HSTS**: dopo il primo rinnovo del certificato andato a buon fine si può attivare con
  `DJANGO_SECURE_HSTS_SECONDS=31536000` nel `.env`, oppure con l'header in nginx, e riavviare
  `web`. Prima di allora no: un errore di certificato renderebbe il sito irraggiungibile dai
  browser per tutta la durata impostata.

## 10. Operazioni correnti

Tutti i comandi si danno da qui, dopo aver caricato le funzioni:

```bash
cd /appdata/gestione-contratti/app/deploy && source comune.sh
```

| Operazione | Comando |
|---|---|
| Stato | `compose ps` |
| Log dell'app (ultimi, poi in tempo reale) | `compose logs --tail 100 -f web` |
| Log dei login | `compose logs web \| grep accounts.auth` |
| Log del connettore MCP | `compose logs --tail 100 -f mcp` |
| Riavvio dell'app | `compose restart web` |
| Arresto (dati intatti) | `compose stop` |
| Riavvio dopo l'arresto | `compose start` |
| Versione installata | `git -C /appdata/gestione-contratti/app describe --tags` |

Il piè di pagina dell'app mostra la stessa versione. I container ripartono da soli dopo un
riavvio del server (`restart: unless-stopped`).

**Da non fare sul server condiviso**:
- `docker system prune`, `docker image prune -a`, `docker volume prune`: toccano gli altri
  applicativi;
- `docker compose down` senza `--project-name gestione-contratti`: usa sempre la funzione
  `compose` di `comune.sh`;
- modificare file in `app/`: il deploy successivo si rifiuta di partire;
- esporre la porta del database o mettere `APP_BIND=0.0.0.0` senza firewall.

## 11. Problemi frequenti

| Sintomo | Causa e rimedio |
|---|---|
| `deploy.sh`: "la porta … è già usata" | un altro servizio la usa: cambia `APP_PORT` nel `.env` e in nginx |
| Errore 400 Bad Request | il nome usato non è in `DJANGO_ALLOWED_HOSTS` |
| Errore 403 CSRF al login | `DJANGO_CSRF_TRUSTED_ORIGINS` deve essere `https://<NOME_DNS>`; nginx deve inviare `X-Forwarded-Proto https` |
| Errore 502 dal proxy | app ferma o indirizzo di inoltro errato (Forward Hostname/Port): `compose ps`, poi `curl -H "Host: <NOME_DNS>" http://<APP_BIND>:<APP_PORT>/healthz` dal server |
| Pagine senza stile (testo semplice) | il CSS non arriva: verifica del §5.3; il proxy deve inoltrare anche `/static/` all'app, senza regole proprie |
| L'app non parte, `accounts.E001` nel log | manca `config/certs/ca-interna.pem` |
| Login AD rifiutato a tutti | `compose logs web \| grep -i ldap`; per diagnosi `LDAP_LOG_LEVEL=DEBUG`, poi `compose restart web` |
| Emergenza senza AD | accesso con l'account break-glass (§6.1) |

## 12. Connettore MCP (F10, F10.1)

Claude interroga il registro attraverso il connettore MCP (`docs/SPEC_MCP.md`). È l'unica parte
dell'app esposta su Internet (deroga alla SPEC §8.2): un **host pubblico dedicato**, raggiungibile
solo dalla rete di uscita di Anthropic (`160.79.104.0/21`) e dalla rete interna, con quattro
endpoint. Login e consenso restano sull'host interno.

| Endpoint (host pubblico) | Chi lo chiama |
|---|---|
| `POST /mcp` | Claude (cloud Anthropic), Claude Code dal PC |
| `GET /.well-known/oauth-protected-resource` (anche `/mcp` in coda) | Claude |
| `GET /.well-known/oauth-authorization-server` | Claude |
| `POST /oauth/token/` | Claude, Claude Code |
| `GET/POST /oauth/authorize/` **sull'host interno** | browser dell'utente |

Il connettore gira in un container a parte (`mcp`), con le sole URL qui sopra e un utente
PostgreSQL limitato: legge tutto, scrive solo su token, registri e tabelle dei tool di scrittura
(§12.8), non cancella dati di dominio.

### 12.0 Attivazione passo per passo (aggiornamento dalla v1.6.0)

Sequenza completa per chi parte da un server con la v1.6.0 e il connettore mai attivato. I
paragrafi da 12.1 a 12.8 restano il riferimento per i dettagli; qui c'è l'ordine in cui farli.
Le fasi 1 e 2 sono indipendenti: la 2 si può fare prima, anche giorni prima.

Segnaposto usati sotto (annotali prima di iniziare):

| Segnaposto | Esempio | Dove si trova |
|---|---|---|
| `<NOME_DNS>` | `contratti.siciliacque.local` | primo valore di `DJANGO_ALLOWED_HOSTS` nel `.env` |
| `<MCP_HOST>` | `mcp-contratti.siciliacque.it` | nome nuovo, nel dominio **pubblico** |
| `<APP_BIND>` | `172.17.0.1` | `APP_BIND` nel `.env` |
| `<MCP_BIND>` | `172.17.0.1` | indirizzo su cui ascolta il connettore (fase 3) |
| `<MCP_PORT>` | `18472` | porta nuova, libera (fase 3) |
| `<IP_PUBBLICO>` | — | IP pubblico con cui il firewall pubblica il proxy |
| `<IP_INTERNO_PROXY>` | — | IP interno del server di Nginx Proxy Manager |

**Prima di iniziare**, serve:
- accesso al DNS pubblico del dominio e, per il certificato, le credenziali API del provider DNS
  supportate da Nginx Proxy Manager (*DNS Challenge*);
- accesso al DNS interno (AD) e al firewall perimetrale;
- il ruolo di Owner dell'organizzazione Claude;
- un PC della rete interna con `bash` e `curl` (Linux, macOS, WSL o Git Bash) e una connessione
  fuori dalla rete aziendale (hotspot del telefono) per le verifiche;
- una finestra di pochi minuti: ogni `deploy.sh` riavvia l'app.

#### Fase 1 — Aggiornamento alla v1.7.1, connettore spento

L'app si aggiorna senza toccare la rete: se qualcosa va storto si torna indietro come in §7.

1. **Tag su GitHub**: `v1.7.1` (il connettore della `v1.7.0` più questa procedura e la verifica
   esterna corretta). Si installa direttamente la `v1.7.1`, senza passare dalla `v1.7.0`.
2. Sul server, controlla versione e configurazione:
   ```bash
   git -C /appdata/gestione-contratti/app describe --tags        # atteso: v1.6.0 (o v1.7.0)
   grep '^MCP_' /appdata/gestione-contratti/config/.env || echo "nessuna variabile MCP"
   ```
   Non devono esserci variabili `MCP_` attive (al massimo righe commentate con `#`).
3. Aggiorna:
   ```bash
   /appdata/gestione-contratti/app/deploy/deploy.sh v1.7.1
   ```
   Righe attese, nell'ordine: `Backup pre-aggiornamento`, `Codice: v1.7.1`, `Build`
   (qualche minuto: c'è una dipendenza nuova), `Migration` con `contratti.0023`,
   `contratti.0024`, `oauth2_provider.*`, `connettore.0001`, `connettore.0002`, poi
   `Attesa di /healthz … ok` e `Installata la versione v1.7.1.` Nessuna riga sul connettore:
   è spento.
4. Verifica:
   ```bash
   cd /appdata/gestione-contratti/app/deploy && source comune.sh && compose ps
   ```
   `db`, `web` e `backup` `Up`, nessun container `mcp`. Dal browser: piè di pagina `v1.7.1`,
   login, cruscotto, budget come prima. In Amministrazione → Parametri compaiono
   `mcp_giorni_login`, `mcp_richieste_minuto`, `mcp_scrittura_attiva`, `mcp_minuti_operazione`.
   La voce di menu «Connettore MCP» non c'è ancora.
5. Se qualcosa non va: rollback di §7 con il dump `…_pre_v1.7.1.dump` e `deploy.sh v1.6.0`.
   Se partivi dalla `v1.7.0` le migration non hanno niente da applicare e basta
   `deploy.sh v1.7.0`, senza ripristino.

Qui ci si può fermare: l'app funziona come prima, il connettore è spento.

#### Fase 2 — DNS, firewall e certificato

1. **DNS pubblico**: record A `<MCP_HOST>` → `<IP_PUBBLICO>`.
2. **DNS interno** (split horizon): record A `<MCP_HOST>` → `<IP_INTERNO_PROXY>`. Da un PC
   interno `nslookup <MCP_HOST>` deve dare l'IP interno; `nslookup <MCP_HOST> 1.1.1.1` l'IP
   pubblico.
3. **Firewall perimetrale**: inoltro TCP 443 da `<IP_PUBBLICO>` al proxy pubblico. Due casi:
   - **IP pubblico dedicato al connettore**: ammetti solo l'origine `160.79.104.0/21`
     (intervallo aggiornato: <https://platform.claude.com/docs/en/api/ip-addresses>);
   - **IP e porta 443 condivisi con altri siti** (il caso di Siciliacque): il firewall non può
     filtrare per nome host, quindi l'unico filtro per IP è l'Access List del proxy (fase 4).

   In entrambi i casi:
   - nessun filtro geografico, IPS o reputazione IP deve scartare `160.79.104.0/21`: sono
     indirizzi negli Stati Uniti. Se c'è, serve un'eccezione per quell'intervallo. Sintomo:
     Claude «impossibile raggiungere» e nessuna riga da `160.79.x.x` nel log del proxy;
   - l'inoltro non deve cambiare l'IP di origine (nessun SNAT o *masquerade* in ingresso):
     l'Access List decide in base a quell'IP;
   - niente porta 80.
4. **Certificato** in Nginx Proxy Manager: SSL Certificates → Add SSL Certificate →
   *Let's Encrypt* → Domain Names `<MCP_HOST>`, *Use a DNS Challenge*, provider e credenziali API
   del DNS, email → Save. Deve comparire con scadenza a circa 90 giorni; NPM lo rinnova da solo.
   Se il provider DNS non è tra quelli di NPM: o si delega a un provider supportato il
   sottodominio, o si apre la porta 80 da Internet verso il proxy (rinnovo con *HTTP Challenge*,
   ogni 60 giorni circa). La seconda strada allarga l'esposizione: da decidere prima.

#### Fase 3 — Configurazione e avvio del container `mcp`

1. Porta libera:
   ```bash
   ss -ltn | grep -w 18472 || echo "libera"
   ```
2. Password dell'utente PostgreSQL del connettore:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(24))"
   ```
3. `nano /appdata/gestione-contratti/config/.env` e aggiungi in fondo (o togli il `#` dalle
   righe dell'esempio e compila):
   ```bash
   MCP_PORT=<MCP_PORT>
   MCP_BIND=<APP_BIND>
   MCP_HOST=<MCP_HOST>
   MCP_URL_PUBBLICO=https://<MCP_HOST>
   MCP_URL_INTERNO=https://<NOME_DNS>
   MCP_DATABASE_URL=postgres://contratti_mcp:<password del punto 2>@db:5432/<POSTGRES_DB>
   ```
   `<POSTGRES_DB>` è lo stesso nome di database di `DATABASE_URL`. `MCP_URL_PUBBLICO` senza `/`
   finale e senza percorso.
   - `MCP_HOST`: il nome **pubblico** nuovo (fase 2), senza `https://`.
   - `MCP_URL_INTERNO`: l'indirizzo con cui oggi si apre l'app dalla rete aziendale, **diverso**
     da `MCP_URL_PUBBLICO`: lì Claude manda il browser per login e consenso, che sull'host
     pubblico non esistono (404). `deploy.sh` lo controlla.
   - `MCP_BIND`: l'indirizzo del server Docker a cui il Proxy Host pubblico inoltra (Forward
     Hostname/IP della fase 4): lo stesso `APP_BIND` se il proxy pubblico è sullo stesso server
     e sulla stessa rete Docker del proxy interno; altrimenti l'IP con cui quel proxy raggiunge il
     server (controllo nella fase 4, punto 3).
4. Rilancia lo stesso deploy:
   ```bash
   /appdata/gestione-contratti/app/deploy/deploy.sh v1.7.1
   ```
   Rispetto alla fase 1 compaiono `Utente PostgreSQL del connettore MCP (privilegi limitati)` e
   `Attesa del connettore MCP su <MCP_BIND>:<MCP_PORT> … ok`. Il dump pre-aggiornamento viene
   rifatto, la build usa la cache, le migration non hanno niente da applicare. Se si ferma su
   una variabile, il messaggio dice quale.
5. Verifica:
   ```bash
   cd /appdata/gestione-contratti/app/deploy && source comune.sh && compose ps
   curl -s -H "Host: <MCP_HOST>" -H "X-Forwarded-Proto: https" http://<MCP_BIND>:<MCP_PORT>/healthz
   ```
   Compare `gestione-contratti-mcp-1` `Up`; `curl` risponde `{"status": "ok"}`. Nell'app, dal
   browser, compare la voce di menu «Connettore MCP».

#### Fase 4 — Host pubblico in Nginx Proxy Manager e verifica

Se ci sono due istanze di Nginx Proxy Manager, una per Internet (es. `NPM-WAN`) e una per la
rete interna, tutto quanto segue si fa sull'**istanza per Internet**: è lì che arrivano le
richieste di Claude. Il DNS interno di `<MCP_HOST>` (fase 2) deve puntare a un proxy che ha lo
stesso Proxy Host: l'istanza per Internet, se raggiungibile dalla rete interna, oppure una copia
del Proxy Host (stessa Access List e stesso filtro) sull'istanza interna.

1. **Access List** (Access Lists → Add Access List): nome `connettore-mcp`, *Satisfy Any*
   spento, nessun utente; nella scheda *Access*: `allow 160.79.104.0/21`, `allow <rete interna>`
   (le sottoreti dei PC, es. `10.0.0.0/8`), `deny all`.
2. **Proxy Host** (Hosts → Proxy Hosts → Add Proxy Host):
   - *Details*: Domain Names `<MCP_HOST>`; Scheme `http`; Forward Hostname/IP `<MCP_BIND>` (o
     l'indirizzo con cui questo proxy raggiunge il server, se è su un'altra macchina);
     Forward Port `<MCP_PORT>`; *Block Common Exploits* attivo; Access List `connettore-mcp`;
   - *SSL*: il certificato della fase 2, *Force SSL* e *HTTP/2 Support* attivi;
   - *Advanced*: il blocco di §12.3 (solo i percorsi del connettore, il resto 404).
3. **Il proxy raggiunge il connettore?** Dal server del proxy pubblico (`<NPM>` è il nome del suo
   container, `<FORWARD>` il Forward Hostname/IP appena scritto):
   ```bash
   docker exec <NPM> curl -s --max-time 5 -H "Host: <MCP_HOST>" -H "X-Forwarded-Proto: https" \
     http://<FORWARD>:<MCP_PORT>/healthz
   ```
   Atteso `{"status": "ok"}`. Se resta appeso o rifiuta, il connettore non ascolta su quell'indirizzo
   (`MCP_BIND`) o un firewall blocca il passaggio: Claude lo vede come «impossibile raggiungere» e
   nel log del proxy compaiono righe 499.
4. **Verifica da dentro**, da un PC della rete interna (non dal server: le connessioni che
   partono dal server verso il proxy sullo stesso host possono arrivare con un IP Docker non in
   allowlist). Lo script è in `deploy/verifica_mcp.sh` del repository (scaricalo da GitHub o
   copialo dal server con `scp`):
   ```bash
   bash verifica_mcp.sh https://<MCP_HOST> ammesso
   ```
   Atteso: «Verifica superata.» (certificato valido, metadati 200, `/mcp` senza token 401,
   altri percorsi 404).
5. **Verifica da fuori**, dallo stesso PC collegato all'hotspot del telefono:
   ```bash
   bash verifica_mcp.sh https://<MCP_HOST> esterno
   ```
   Atteso: «Verifica superata.», con 403 (Access List) o «nessuna risposta: bloccato dal
   firewall» (IP pubblico dedicato, fase 2). Ogni 200 o 401 da fuori vuol dire che l'host è
   aperto a tutti: spegni il proxy host e correggi firewall e Access List prima di andare avanti.

   Senza `bash`, su Windows: `curl.exe -s -o NUL -w "%{http_code}" https://<MCP_HOST>/.well-known/oauth-authorization-server`
   dà `200` da dentro e `403` o `000` (nessuna risposta) da fuori.

#### Fase 5 — Client OAuth

```bash
cd /appdata/gestione-contratti/app/deploy
./manage.sh crea_client_mcp claude
./manage.sh crea_client_mcp claude-code
```
Il primo stampa `client ID` e `client secret`: il secret non si rilegge più, tienilo aperto nel
terminale e incollalo direttamente nella fase 6 (non in email, chat o file). Il secondo stampa
solo il `client ID` (Claude Code non usa secret).

#### Fase 6 — Connettore nell'organizzazione Claude

Da Owner, su claude.ai (le voci dei menu possono cambiare):
1. Impostazioni dell'organizzazione → **Connettori** → Aggiungi connettore personalizzato.
2. Nome `Registro contratti`; URL `https://<MCP_HOST>/mcp`.
3. *Impostazioni avanzate*: OAuth Client ID e Client Secret del client `claude` → Aggiungi.

Il connettore compare a tutti i membri, ma ognuno deve collegarlo con le proprie credenziali.

#### Fase 7 — Primo collegamento

Dalla rete interna o da VPN:
1. claude.ai → Impostazioni → Connettori → `Registro contratti` → **Connetti**.
2. Si apre la pagina di login dell'app (`<NOME_DNS>`): login con l'account AD.
3. Pagina «Collega il connettore MCP»: spunta «Consenti anche la modifica» se vuoi provare la
   scrittura, poi **Autorizza**. Si torna su claude.ai con il connettore collegato.
4. In una chat nuova, con il connettore attivo: «Quali contratti dei miei cluster sono in
   alert?». Il risultato deve coincidere con il cruscotto.
5. Nell'app: menu «Connettore MCP» mostra il collegamento con i permessi; Amministrazione →
   Connettore MCP → Chiamate mostra le chiamate appena fatte.

Se al punto 2 la pagina non si apre o al punto 3 Claude dà errore: fermati, annota il
messaggio e le righe di Amministrazione → Connettore MCP → Chiamate, e vedi §12.9. Il login
sull'host interno è verificato (D8, 07/10/2026): se il browser apre l'host pubblico, il problema
è `MCP_URL_INTERNO`.

#### Fase 8 — Prova della scrittura

1. Chiedi a Claude una modifica reale che avresti fatto comunque (es. «registra la proroga di
   3 mesi del contratto X»). Claude mostra l'anteprima con le modifiche e gli effetti (date,
   alert, budget) e **non scrive niente**.
2. Controlla l'anteprima, poi rispondi di confermare: Claude chiama `conferma_operazione`.
3. Nell'app: la modifica c'è; nella storia dell'oggetto l'utente sei tu e il motivo inizia con
   `MCP registra_proroga`; Amministrazione → Connettore MCP → Operazioni la mostra confermata.

Per tenere la scrittura spenta all'inizio: Amministrazione → Parametri → `mcp_scrittura_attiva`
= 0 (validità da oggi). La lettura resta attiva; si riaccende con 1.

#### Fase 9 — Claude Code (facoltativo) e comunicazione agli utenti

- Claude Code, da un PC della rete interna, con l'ID del client `claude-code` (fase 5):
  ```bash
  claude mcp add --transport http --client-id <ID claude-code> registro-contratti https://<MCP_HOST>/mcp
  ```
  poi `/mcp` → `registro-contratti` → Authenticate (si apre il login dell'app).
- Agli utenti: il collegamento si fa dalla rete interna o da VPN; dopo, Claude funziona anche
  da fuori. Senza un login all'app per 7 giorni Claude chiede di ricollegarsi. Ognuno vede gli
  stessi dati dell'interfaccia; scrivono solo Editor e Admin che hanno spuntato la modifica.

**Per spegnere tutto** in caso di problemi: in NPM disattiva il proxy host di `<MCP_HOST>`
(effetto immediato), poi, se serve, `MCP_PORT=` vuota nel `.env` e `deploy.sh v1.7.1`.

### 12.1 Configurazione (`config/.env`)

```bash
MCP_PORT=18472                                   # porta libera; vuota = connettore spento
MCP_BIND=172.17.0.1                              # come APP_BIND (§5.1)
MCP_HOST=mcp-contratti.<dominio pubblico>
MCP_URL_PUBBLICO=https://mcp-contratti.<dominio pubblico>
MCP_URL_INTERNO=https://<NOME_DNS interno>       # lo stesso host dell'interfaccia
MCP_DATABASE_URL=postgres://contratti_mcp:<password esadecimale>@db:5432/contratti
```

La password si genera come le altre (`python3 -c "import secrets; print(secrets.token_hex(24))"`);
l'utente deve essere diverso da `POSTGRES_USER`. Poi `deploy.sh <versione>`: crea o aggiorna
l'utente PostgreSQL (`manage.py ruolo_db_mcp`), avvia il container `mcp` e aspetta il suo
`/healthz`. Lo stesso comando riallinea i privilegi dopo ogni migration e dopo un ripristino.

### 12.2 DNS, firewall e certificato

1. **DNS pubblico**: record A di `MCP_HOST` verso l'IP pubblico del proxy.
2. **DNS interno** (split horizon): lo stesso nome verso l'IP interno del proxy, così Claude Code
   usa lo stesso URL dalla rete aziendale.
3. **Firewall perimetrale**: 443 in ingresso verso il proxy pubblico; solo da `160.79.104.0/21`
   se l'IP pubblico è dedicato, altrimenti il filtro per IP è l'Access List (§12.3). Nessun
   filtro geografico o IPS deve bloccare `160.79.104.0/21` (intervallo aggiornato su
   <https://platform.claude.com/docs/en/api/ip-addresses>).
4. **Certificato di una CA pubblica** per `MCP_HOST` (Let's Encrypt da Nginx Proxy Manager): il
   cloud di Anthropic non si fida della CA interna. Con la porta 80 chiusa da Internet serve la
   verifica DNS (*DNS Challenge*) del provider DNS.

### 12.3 Nginx Proxy Manager

1. **Access Lists** → Add Access List `connettore-mcp`:
   - *Satisfy Any* spento, nessun utente;
   - **Access**: `allow 160.79.104.0/21`, `allow <rete interna>` (es. `10.0.0.0/8`), poi `deny all`.
2. **Hosts → Proxy Hosts** → Add Proxy Host:
   - **Details**: Domain Names `MCP_HOST`; Scheme `http`; Forward `MCP_BIND` : `MCP_PORT`;
     *Block Common Exploits* attivo; **Access List** `connettore-mcp`.
   - **SSL**: il certificato pubblico, *Force SSL* e *HTTP/2* attivi.
   - **Advanced**: solo i percorsi del connettore, tutto il resto 404:
     ```nginx
     if ($uri !~ "^/(mcp|\.well-known/oauth-protected-resource(/mcp)?|\.well-known/oauth-authorization-server|oauth/token/|\.well-known/acme-challenge/.*)$") {
         return 404;
     }
     client_max_body_size 1m;
     ```
3. Le stesse regole, per un nginx con file, sono in `deploy/nginx/connettore-mcp.conf.esempio`
   (la CI le usa per provare il connettore).

**Verifica** (dopo ogni deploy e ogni modifica del proxy):
```bash
# da un PC della rete interna (in allowlist), non dal server (§12.0, fase 4)
bash verifica_mcp.sh https://<MCP_HOST> ammesso
# da una rete fuori allowlist (es. hotspot del telefono)
bash verifica_mcp.sh https://<MCP_HOST> esterno
```
Esito atteso: «Verifica superata.» Da fuori, nessuna risposta (firewall) o 403; da dentro,
metadati 200, `/mcp` senza token 401 con `resource_metadata`, ogni altro percorso 404.

### 12.4 Client OAuth

Nessuna registrazione automatica: i client si creano a mano, una volta.
```bash
cd /appdata/gestione-contratti/app/deploy
./manage.sh crea_client_mcp claude        # claude.ai, Desktop, mobile, Cowork: ID e secret
./manage.sh crea_client_mcp claude-code   # Claude Code: solo ID (client pubblico)
```
Il secret si vede **una volta sola**: va subito nel connettore di Claude (§12.5), non altrove.
Per cambiarlo si crea un nuovo client e si elimina il vecchio da Amministrazione → Django OAuth
Toolkit → Applications.

### 12.5 Organizzazione Claude

Lo fa un Owner dell'organizzazione Claude di Siciliacque (le voci dei menu possono cambiare):
1. Impostazioni dell'organizzazione → **Connettori** → Aggiungi connettore personalizzato.
2. Nome `Registro contratti`, URL `https://<MCP_HOST>/mcp`.
3. **Impostazioni avanzate**: OAuth Client ID e Client Secret del client `claude` (§12.4).

Ogni utente poi, **dalla rete interna o da VPN**: Impostazioni → Connettori → Registro contratti →
Connetti. Si apre la pagina di login dell'app, poi «Collega il connettore MCP» → Autorizza.

Claude Code, dalla rete interna:
```bash
claude mcp add --transport http --client-id <ID del client claude-code> \
  registro-contratti https://<MCP_HOST>/mcp
```
poi `/mcp` in Claude Code → Authenticate.

### 12.6 Primo collegamento di un utente

Prova D8 superata in produzione il 07/10/2026: la pagina di login interna si apre e dopo
«Autorizza» Claude mostra il connettore collegato. Se a un utente non riesce, §12.9.

Poi, in una chat: «Quali contratti dei miei cluster sono in alert?». Il risultato deve coincidere
con il cruscotto dell'app.

### 12.7 Validità, revoca, registro

- Access token di 1 ora (`MCP_ACCESS_TOKEN_SECONDI`), rinnovato da Claude. Il rinnovo riesce
  solo se l'utente ha fatto login nell'app negli ultimi 7 giorni (parametro `mcp_giorni_login`):
  altrimenti Claude chiede di ricollegare il connettore, dalla rete interna.
- **Revoca da parte dell'utente**: menu «Connettore MCP» dell'app (`/connettore/`), con i propri
  collegamenti, la revoca e le ultime chiamate.
- **Revoca immediata** di un altro utente (Admin): Amministrazione → Django OAuth Toolkit →
  *Refresh tokens* e *Access tokens* → filtra per utente → elimina; oppure disattiva l'utente.
- **Spegnere il connettore**: `MCP_PORT=` vuota nel `.env` e `deploy.sh <versione>`, oppure
  disattivare il proxy host in Nginx Proxy Manager.
- **Registro**: Amministrazione → Connettore MCP → Chiamate (utente, tool, argomenti, esito,
  durata; mai i risultati né i token). Limite: 60 richieste al minuto per collegamento
  (parametro `mcp_richieste_minuto`) e 200 KB per risultato (`MCP_RISPOSTA_MAX_BYTES`): oltre,
  Claude riceve l'invito a restringere i filtri.
- **Tool** di lettura: `riferimenti`, `cerca`, `scadenze`, `contratto`, `fabbisogno`,
  `scadenzario`, `budget`, `piano_ordini`, `spese_wbs`; per Admin ed Editor anche `fornitore` e
  `piani_da_verificare`, come le pagine dell'interfaccia. Di scrittura: §12.8.

### 12.8 Scrittura (F10.1)

- **Chi**: solo Admin ed Editor, nei propri cluster, e solo se al collegamento hanno spuntato
  «Consenti anche la modifica» nella pagina di consenso. Il Reader non ottiene mai la scrittura.
  La colonna «Permessi» della pagina «Connettore MCP» dice se un collegamento può modificare.
- **Tool**: pratica (`avanza_pratica`), rate e scadenzario (`modifica_rata`,
  `genera_scadenzario`), fornitori e fabbisogni (`crea_*`, `modifica_*`), contratti
  (`crea_contratto` con le voci, `modifica_contratto`, `registra_rinnovo` anche senza
  contratto, `registra_proroga`, `crea_voce`, `modifica_voce`), `archivia` e `ripristina`, catena
  (`collega_rinnovo`, `scollega_predecessore`, `confluisci`, `togli_confluenza`). Solo
  dall'interfaccia: spostamento, accorpamento, doppioni, import, configurazione.
- **Come**: ogni tool di scrittura restituisce un'anteprima (modifiche campo per campo, effetti
  su date, alert, previsti e budget) e un codice; si esegue solo con `conferma_operazione`, entro
  15 minuti (parametro `mcp_minuti_operazione`) e solo se nel frattempo nessuno ha modificato gli
  stessi oggetti. Nella storia l'utente è la persona e il motivo inizia con `MCP <tool>`.
- **In Claude**: nelle impostazioni del connettore si può lasciare «chiedi sempre» solo su
  `conferma_operazione` (è l'unico tool marcato come distruttivo).
- **Spegnere la scrittura** senza deploy: Amministrazione → Parametri → `mcp_scrittura_attiva`
  = 0 (nuovo valore con validità da oggi). La lettura resta attiva.
- **Registro**: Amministrazione → Connettore MCP → Operazioni (anteprime, conferme, rifiuti con
  il motivo) e Chiamate.
- **Database**: l'utente `contratti_mcp` scrive solo sulle tabelle di dominio dei tool e sulle
  loro storie; cancella solo rate generate e token (`ruolo_db_mcp`, a ogni deploy).

### 12.9 Problemi frequenti

| Sintomo | Causa e rimedio |
|---|---|
| Claude: «Couldn't reach the MCP server» | firewall o Access List non ammettono `160.79.104.0/21`, certificato non pubblico, o `/.well-known/...` bloccati dall'Advanced del proxy: `verifica_mcp.sh ... ammesso` |
| Claude «impossibile raggiungere», nel log del proxy nessuna riga da `160.79.x.x` | il traffico non arriva al proxy: DNS pubblico o firewall (anche filtri geografici o IPS, gli IP di Anthropic sono negli USA) |
| Nel log del proxy righe **499** da `160.79.x.x` | il proxy non raggiunge il container `mcp` entro 5 secondi: Forward Hostname/IP diverso da `MCP_BIND` o firewall tra proxy e server (§12.0, fase 4, punto 3) |
| Il browser apre `https://<MCP_HOST>/oauth/authorize/…` e riceve 404 | `MCP_URL_INTERNO` uguale all'URL pubblico: va l'URL interno dell'app, poi `deploy.sh` e riconnessione del connettore in Claude |
| La pagina di login non si apre da casa | normale: login e consenso solo dalla rete interna o da VPN (§12.5) |
| «Authorization with the MCP server failed» | client ID/secret errati nel connettore, o redirect non registrato: ricrea il client (§12.4) |
| Claude chiede di ricollegarsi ogni settimana | regola dei 7 giorni: basta un login all'app nel frattempo |
| 403 con «Utente senza un ruolo» | l'utente non è più in un gruppo `GG_Contratti_*` o è disattivato |
| 429 | più di 60 richieste al minuto dallo stesso collegamento |
| `compose logs mcp`: `permission denied` | privilegi dell'utente PostgreSQL non allineati: `./manage.sh ruolo_db_mcp`, poi `compose restart mcp` |
