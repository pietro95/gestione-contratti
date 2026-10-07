# Documentazione

## Orientamento

| Esigenza | Documento |
|---|---|
| Comprendere scopo e avvio rapido | [README principale](../README.md) |
| Conoscere requisiti e regole di dominio | [SPEC](SPEC.md) |
| Consultare esempi normativi | [TEST_CASES](TEST_CASES.md) |
| Vedere fasi e stato del lavoro | [ROADMAP](ROADMAP.md) |
| Comprendere componenti e dipendenze | [ARCHITECTURE](ARCHITECTURE.md) |
| Orientarsi fra le entità | [DATA_MODEL](DATA_MODEL.md) |
| Installare o amministrare la produzione | [RUNBOOK](RUNBOOK.md) |
| Eseguire attività ricorrenti | [OPERATIONS](OPERATIONS.md) |
| Preparare e distribuire una versione | [RELEASE](RELEASE.md) |
| Valutare sicurezza e trattamento dati | [SECURITY](SECURITY.md) |
| Integrare il connettore | [SPEC_MCP](SPEC_MCP.md) |
| Contribuire al codice o ai documenti | [CONTRIBUTING](../CONTRIBUTING.md) |
| Consultare decisioni tecniche | [ADR](adr/README.md) |

## Autorità dei documenti

In caso di incoerenza:

1. la SPEC definisce il comportamento richiesto;
2. TEST_CASES definisce gli esempi normativi verificabili;
3. il codice e le migration descrivono lo stato implementato;
4. ROADMAP descrive pianificazione e stato, non sostituisce la SPEC;
5. ARCHITECTURE e DATA_MODEL spiegano la struttura senza ridefinire le regole;
6. RUNBOOK e OPERATIONS descrivono l'esercizio;
7. gli ADR spiegano perché è stata adottata una decisione tecnica.

Un conflitto va risolto esplicitamente nella pull request: non si correggono i test o la documentazione in silenzio per adattarli al codice.

## Regole editoriali

- Usare ruoli e responsabilità, non nomi di persone.
- Indicare stato e data delle revisioni.
- Evitare la duplicazione di procedure: inserire un rimando al documento autorevole.
- Aggiornare i link nello stesso commit che sposta o rinomina un file.
- Non inserire dati reali, segreti o dettagli operativi sensibili.
- Scrivere in italiano, con termini di dominio coerenti con la SPEC.
