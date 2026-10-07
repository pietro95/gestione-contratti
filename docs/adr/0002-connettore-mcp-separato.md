# ADR-0002 — Connettore MCP separato con OAuth

- **Stato:** accettato
- **Data:** 2026-10-07

## Contesto

L'applicazione ordinaria deve restare accessibile solo dalla rete interna, mentre i client MCP operano attraverso un servizio cloud. È necessario conservare identità, ruolo, cluster e tracciabilità dell'utente.

## Decisione

Eseguire il connettore MCP come processo Django separato, su host dedicato e con URLconf limitato. Usare OAuth con PKCE, scope distinti per lettura e scrittura, un utente PostgreSQL a privilegi ridotti e scritture in due fasi con anteprima e conferma.

## Conseguenze

- login e interfaccia restano interni;
- solo gli endpoint strettamente necessari sono pubblici;
- la configurazione di rete e OAuth è più complessa;
- i privilegi PostgreSQL devono essere aggiornati e testati quando cambia il dominio;
- il componente può essere disattivato indipendentemente dall'applicazione principale;
- dati restituiti dai tool transitano nel servizio del fornitore del modello.
