# Operazioni correnti

## Scopo

Questa guida raccoglie le attività ricorrenti dell'esercizio. Per installazione, configurazione, certificati, aggiornamento e scenari di guasto vedere il [RUNBOOK](RUNBOOK.md). Tutti i comandi di produzione devono essere eseguiti dalla directory `deploy/` o tramite gli script documentati.

## Controlli quotidiani

- verificare che l'applicazione risponda e che `/healthz` restituisca `200`;
- controllare lo stato dei container;
- esaminare errori applicativi o ripetuti tentativi di autenticazione;
- verificare la riuscita del backup pianificato;
- controllare eventuali import rimasti con anomalie non gestite.

Comandi di riferimento:

```bash
cd /appdata/gestione-contratti/app/deploy
source ./comune.sh
compose ps
compose logs --tail 100 web
compose logs --tail 100 backup
```

Se il profilo MCP è attivo:

```bash
compose logs --tail 100 mcp
```

## Import operativi

Eseguire sempre prima una simulazione con `--dry-run`, conservarne il report delle anomalie e procedere solo dopo la verifica.

Esempi:

```bash
deploy/manage.sh import_excel /import/<file.xlsx> --area IT --dry-run
deploy/manage.sh import_fatture /import/<file.xlsx> --dry-run
deploy/manage.sh import_tabelle_sap /import/<file.xlsx> --dry-run
deploy/manage.sh import_esecuzione /import/<file.xlsx> --dry-run
deploy/manage.sh import_riepilogo /import/<file.xlsx> --dry-run
```

### Struttura cluster/sottocluster (Rev25)

Due passi, in quest'ordine, ciascuno prima con `--dry-run`:

```bash
deploy/manage.sh import_struttura_budget /import/<struttura_ictdinn.xlsx> --dry-run   # cluster, sottocluster, conti, WBS
deploy/manage.sh migra_cluster --dry-run                                              # fabbisogni, RDA, WBS, conti, assegnazioni
```

Dopo il secondo: assegnare i sottocluster ai responsabili (amministrazione → assegnazioni di cluster; l'import segnala gli owner del file con `OWNER_DA_ASSEGNARE`), aprire un campione di fabbisogni e verificare le anomalie. I fabbisogni non spostati (`FABBISOGNO_CON_SOTTOCLUSTER_VECCHIO`, vecchi cluster senza corrispondenza) si sistemano a mano o dal connettore MCP (`modifica_fabbisogno`: cluster e sottocluster insieme).

Dopo l'import reale:

1. verificare quantità importate e anomalie;
2. aprire un campione di record nell'interfaccia;
3. verificare report e quadrature interessati;
4. archiviare il file secondo le regole aziendali, non nel repository.

## Backup

I dump giornalieri sono prodotti dal container `backup` e conservati secondo `BACKUP_GIORNI`. Verificare presenza, dimensione plausibile e log.

Backup manuale:

```bash
cd /appdata/gestione-contratti/app/deploy
./backup.sh manuale
```

La presenza di un dump non basta: la procedura di verifica del ripristino deve essere eseguita secondo il RUNBOOK.

## Aggiornamento

Gli aggiornamenti si eseguono solo da tag o commit approvati:

```bash
/appdata/gestione-contratti/app/deploy/deploy.sh <tag-o-commit>
```

Prima:

- leggere le note della release;
- controllare migration e prerequisiti;
- verificare lo spazio disponibile;
- concordare la finestra se l'aggiornamento interrompe il servizio;
- confermare il percorso di rollback.

Dopo:

- controllare container e `/healthz`;
- verificare login e una pagina protetta;
- eseguire gli smoke test indicati dalla release;
- controllare migration e versione nel piè di pagina;
- se MCP è attivo, eseguire le verifiche previste dal RUNBOOK.

## Account break-glass

L'account di emergenza deve essere creato o ruotato dalla console, mai tramite variabili d'ambiente:

```bash
deploy/manage.sh crea_breakglass
```

Ogni uso deve essere motivato, tracciato e seguito dal ripristino dell'accesso ordinario. La password non deve comparire in ticket, chat o log.

## Connettore MCP

Per lo stato ordinario:

- controllare il container `mcp`;
- verificare l'assenza di errori di autorizzazione o privilegi DB;
- usare `deploy/verifica_mcp.sh` come descritto nel RUNBOOK;
- revocare i token di un utente quando richiesto;
- mantenere separati host interno e host pubblico.

Modifiche a DNS, firewall, client OAuth o organizzazione del servizio esterno richiedono il ruolo amministrativo appropriato e la checklist del RUNBOOK.

## Incidenti e anomalie

1. Conservare i log rilevanti senza pubblicare dati sensibili.
2. Identificare versione, container e orario.
3. Limitare l'impatto senza alterare i dati.
4. Se necessario, disattivare il solo componente MCP.
5. Prima di un ripristino, seguire integralmente la procedura documentata.
6. Registrare causa, correzione e azioni preventive nel sistema interno previsto.

## Riferimenti

- [RUNBOOK](RUNBOOK.md)
- [Procedura di ripristino](../deploy/restore.md)
- [Sicurezza](SECURITY.md)
- [Processo di release](RELEASE.md)
