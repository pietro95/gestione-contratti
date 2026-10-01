# Runbook — Registro contratti IT/TLC in produzione

Installazione, aggiornamento ed esercizio sul **server Docker aziendale già in uso** (Ubuntu),
condiviso con altri applicativi di produzione. Ogni comando si può copiare così com'è; le parti
da adattare sono indicate come `<SEGNAPOSTO>`.

## 0. Principi

- **Tutto in una cartella**: `/appdata/gestione-contratti`. Fuori da lì si tocca solo la
  configurazione del reverse proxy nginx esistente (§5).
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
| `static/` | file statici, serviti da nginx |
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
mkdir -p config/certs postgres static backup import
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

Certificato della CA interna (serve per LDAPS):

```bash
cp <PERCORSO>/ca-interna.pem /appdata/gestione-contratti/config/certs/ca-interna.pem
```

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
6. pubblica i file statici in `static/`;
7. avvia app e backup;
8. attende che `/healthz` risponda.

Al termine stampa `Installata la versione v1.0.`

Verifica:

```bash
cd /appdata/gestione-contratti/app/deploy && source comune.sh && compose ps
```

Devono comparire `gestione-contratti-db-1`, `-web-1` e `-backup-1`, tutti `Up`, con `db` e
`web` `(healthy)`.

## 5. Reverse proxy nginx

1. **DNS**: record A per il nome scelto (es. `contratti.siciliacque.local`) verso il server.
2. **Certificato dalla CA interna**: richiesta con il nome nel SAN.
   ```bash
   openssl req -new -newkey rsa:3072 -nodes -keyout contratti.key -out contratti.csr \
     -subj "/CN=<NOME_DNS>" -addext "subjectAltName=DNS:<NOME_DNS>"
   ```
   Consegna `contratti.csr` alla CA; metti certificato e chiave dove nginx tiene gli altri
   (es. `/etc/nginx/ssl/`), con la chiave leggibile solo da root.
3. **Configurazione**: parti da `app/deploy/nginx/gestione-contratti.conf.esempio`.
   ```bash
   sudo cp /appdata/gestione-contratti/app/deploy/nginx/gestione-contratti.conf.esempio \
     /etc/nginx/sites-available/gestione-contratti.conf
   sudo nano /etc/nginx/sites-available/gestione-contratti.conf
   ```
   Sostituisci i segnaposto:

   | Segnaposto | Valore |
   |---|---|
   | `__SERVER_NAME__` | nome DNS |
   | `__APP_UPSTREAM__` | `APP_BIND:APP_PORT` |
   | `__STATIC_DIR__` | `/appdata/gestione-contratti/static` |
   | `__CERT__`, `__KEY__` | i percorsi del certificato e della chiave |

   Poi attiva il sito:
   ```bash
   sudo ln -s /etc/nginx/sites-available/gestione-contratti.conf /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```
   `nginx -t` verifica la sintassi **senza** toccare gli altri siti; il `reload` non interrompe le
   connessioni in corso.
   **Se nginx gira in un container**:
   - monta `/appdata/gestione-contratti/static` in sola lettura nello stesso percorso;
   - usa come `__APP_UPSTREAM__` l'indirizzo dell'host visto dal container;
   - ricarica con `docker exec <container-nginx> nginx -t && docker exec <container-nginx> nginx -s reload`.
4. **Verifica** da un PC della rete: `https://<NOME_DNS>/healthz` risponde `{"status": "ok"}` e
   `http://<NOME_DNS>` rimanda a `https://`.

## 6. Primo utilizzo

I comandi applicativi si lanciano con `deploy/manage.sh`, che li esegue nel container:

```bash
cd /appdata/gestione-contratti/app/deploy
```

1. **Account di emergenza (break-glass)**: l'unico accesso locale ammesso con LDAP attivo. La
   password si digita, non passa da variabili; custodiscila come da procedura aziendale.
   ```bash
   ./manage.sh crea_breakglass
   ```
2. **Login con le credenziali di dominio**: entra con un utente di ciascun gruppo AD. Il ruolo
   compare in alto a destra (Admin, Editor, Reader). Chi non è in alcun gruppo non entra.
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
5. **Quadratura con l'Excel**:
   ```bash
   ./manage.sh quadratura_excel /import/<Contratti_IT.xlsx> --area IT
   ```
   Produce `*_quadratura.xlsx` in `import/`.
6. **Proposte dell'import**: dall'app, menu "Proposte import", conferma o scarta i
   raggruppamenti e poi i predecessori.
7. **Configurazione** (admin dell'app): verifica soglie, lead time e parametri, che sono valori
   provvisori.

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
| Errore 502 da nginx | app ferma o `__APP_UPSTREAM__` errato: `compose ps`, poi `curl -H "Host: <NOME_DNS>" http://<APP_BIND>:<APP_PORT>/healthz` dal server |
| Pagine senza stile | `__STATIC_DIR__` errato o non leggibile da nginx (`ls -l /appdata/gestione-contratti/static`) |
| L'app non parte, `accounts.E001` nel log | manca `config/certs/ca-interna.pem` |
| Login AD rifiutato a tutti | `compose logs web \| grep -i ldap`; per diagnosi `LDAP_LOG_LEVEL=DEBUG`, poi `compose restart web` |
| Emergenza senza AD | accesso con l'account break-glass (§6.1) |
