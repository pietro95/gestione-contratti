# Processo di release

## Principi

Una release identifica uno stato verificato e distribuibile. Il tag deve puntare esattamente al commit approvato; il deploy non deve dipendere da branch mobili.

Il versionamento segue `vMAJOR.MINOR.PATCH`:

- **MAJOR**: cambi incompatibili o trasformazioni sostanziali del processo;
- **MINOR**: nuove funzioni compatibili;
- **PATCH**: correzioni e aggiornamenti documentali o operativi compatibili.

## Preparazione

La pull request di release deve indicare:

- obiettivo e perimetro;
- funzionalità e correzioni;
- revisioni di SPEC, ROADMAP e casi di test;
- dipendenze aggiunte o aggiornate;
- migration e trasformazioni dati;
- impatto su configurazione e infrastruttura;
- procedura di rollback;
- verifiche successive al deploy;
- decisioni ancora aperte, che devono essere chiuse o rinviate esplicitamente.

## Controlli prima del merge

```bash
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check
uv run pytest
```

Inoltre:

- [ ] CI verde sul commit da unire.
- [ ] Test di permessi presenti per ogni nuova scrittura.
- [ ] Fixture prive di dati reali.
- [ ] `.env.example` aggiornato.
- [ ] RUNBOOK e OPERATIONS aggiornati se cambia l'esercizio.
- [ ] SPEC e TEST_CASES aggiornati se cambia il comportamento.
- [ ] Migration nuove, senza modifica di migration già confluite.
- [ ] Backup e rollback provati quando cambia il database.
- [ ] Test MCP e privilegi dell'utente DB limitato verificati quando applicabile.

## Merge e tag

1. Unire la pull request con il metodo previsto dalle regole della repository.
2. Verificare che `main` sia verde.
3. Creare un tag annotato `vMAJOR.MINOR.PATCH` sul commit di `main`.
4. Pubblicare una GitHub Release usando il testo approvato.
5. Non spostare o riutilizzare un tag pubblicato.

## Struttura delle note

### Titolo

`vX.Y.Z — descrizione sintetica`

### Corpo

- **Novità**
- **Correzioni**
- **Database e configurazione**
- **Sicurezza**
- **Rollback**
- **Verifiche dopo il deploy**
- **Problemi noti o decisioni rinviate**

Le note devono essere comprensibili senza leggere la cronologia dei commit.

## Deploy

Il deploy viene eseguito con:

```bash
deploy/deploy.sh <tag>
```

Il responsabile del rilascio verifica il backup preventivo, lo stato dei container, le migration, `/healthz`, il login e gli smoke test elencati nelle note.

## Rollback

Se la release include migration o modifica dati:

1. fermare le scritture;
2. conservare un backup dello stato corrente;
3. ripristinare il dump indicato nelle note;
4. distribuire il tag precedente compatibile;
5. eseguire le verifiche funzionali;
6. documentare l'eventuale perdita dei dati inseriti dopo il backup.

La procedura concreta è nel [RUNBOOK](RUNBOOK.md) e in [`deploy/restore.md`](../deploy/restore.md).

## Dopo il rilascio

- confermare versione e stato;
- registrare esito e orario;
- eliminare i branch già uniti;
- aprire issue per attività rinviate;
- aggiornare la roadmap;
- verificare che la release GitHub riporti il confronto corretto con la precedente.
