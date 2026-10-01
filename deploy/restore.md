# Ripristino del database

Tre casi, dal più frequente al più raro. I dump sono in `/appdata/gestione-contratti/backup/`,
con nome `AAAA.MM.GG_HHMM_contratti[_etichetta].dump`. I dump con etichetta `pre_<versione>`
sono quelli fatti da `deploy.sh` prima di un aggiornamento.

## 1. Prova di ripristino (senza toccare i dati)

Da fare una volta al mese e dopo ogni aggiornamento importante:

```bash
/appdata/gestione-contratti/app/deploy/verifica_ripristino.sh            # ultimo dump
/appdata/gestione-contratti/app/deploy/verifica_ripristino.sh <file.dump> # un dump preciso
```

Ripristina il dump in un database temporaneo (`verifica_ripristino`), stampa per le tabelle
principali il numero di righe del database in uso e di quello ripristinato, poi elimina il
database temporaneo. Esito atteso: `Ripristino riuscito`.

Sul dump più recente i conteggi coincidono. Su un dump più vecchio sono diversi, e
la differenza corrisponde alle modifiche fatte dopo.

## 2. Ripristino in produzione (dati sbagliati, rollback di un aggiornamento)

1. Scegli il dump:
   ```bash
   ls -lt /appdata/gestione-contratti/backup | head -20
   ```
2. Avvisa gli utenti: l'app resta ferma per circa un minuto.
3. Ripristina:
   ```bash
   /appdata/gestione-contratti/app/deploy/ripristina.sh <AAAA.MM.GG_HHMM_contratti….dump>
   ```
   Lo script chiede di digitare `RIPRISTINA`, poi:
   1. fa un dump di sicurezza dei dati attuali (`…_prima_del_ripristino.dump`);
   2. ferma l'app;
   3. ricrea il database vuoto;
   4. ripristina il dump scelto;
   5. riavvia l'app e controlla `/healthz`.
4. Se ripristini per un **rollback**, reinstalla la versione precedente:
   `deploy.sh <versione precedente>`
   (RUNBOOK §7).
5. Verifica dall'app gli ultimi dati attesi: ultimi contratti inseriti, storico delle modifiche.

Se hai sbagliato dump, ripeti il punto 3 con il dump `…_prima_del_ripristino.dump`.

## 3. Server perso (ripristino da zero)

**Via 1 — dal backup della VM** (la più semplice):
1. ripristina la cartella `/appdata/gestione-contratti` completa e la configurazione nginx;
2. se la copia della VM non è uno snapshot istantaneo, la cartella `postgres/` potrebbe essere
   incoerente. In quel caso:
   1. sposta la cartella da parte:
      ```bash
      mv postgres postgres.da_verificare && mkdir postgres
      ```
   2. segui la via 2 dal punto 3, usando l'ultimo dump presente in `backup/`.
3. Avvia:
   ```bash
   /appdata/gestione-contratti/app/deploy/deploy.sh <versione installata>
   ```

**Via 2 — nuovo server**:
1. RUNBOOK §1–§3: prerequisiti, codice, configurazione. Recupera `config/.env` e
   `config/certs/` dal backup della VM: contengono password e certificati.
2. Copia il dump in `/appdata/gestione-contratti/backup/`.
3. Installa la **stessa versione** che girava quando è stato fatto il dump:
   ```bash
   /appdata/gestione-contratti/app/deploy/deploy.sh <versione>
   ```
4. Ripristina:
   ```bash
   /appdata/gestione-contratti/app/deploy/ripristina.sh <file.dump>
   ```
5. Configura nginx (RUNBOOK §5) e controlla `https://<NOME_DNS>/healthz`.
