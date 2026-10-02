# Runbook — Registro contratti IT/TLC in produzione

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
