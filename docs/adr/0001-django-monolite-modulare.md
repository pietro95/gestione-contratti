# ADR-0001 — Applicazione Django monolitica modulare

- **Stato:** accettato
- **Data:** 2026-10-07

## Contesto

Il Registro contratti condivide regole, autorizzazioni e transazioni tra gestione contratti, processo d'acquisto, report e import. Il team operativo è contenuto e l'ambiente di produzione è un singolo stack Docker interno.

## Decisione

Mantenere un'applicazione Django monolitica, suddivisa in moduli applicativi e con un motore di calcolo puro separato dall'ORM. PostgreSQL è l'unico archivio transazionale.

## Conseguenze

- deploy, backup e transazioni restano semplici;
- web, report e MCP riutilizzano gli stessi servizi;
- i confini fra moduli devono essere mantenuti esplicitamente;
- i file troppo grandi vanno separati per area funzionale senza introdurre microservizi;
- una futura separazione richiederà un nuovo ADR.
