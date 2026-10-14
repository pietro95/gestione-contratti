# Casi di test di riferimento

Ogni caso descrive: input, output atteso, regola della SPEC che verifica.

Allineato alla SPEC Rev02 (01/10/2026): TC-03 aggiornato alla regola di pagamento d.f.f.m. e senza la cassa per data di pagamento; aggiunto TC-10. SPEC Rev04: aggiunto TC-11. F9.3: aggiunto TC-12 (redatto su richiesta del responsabile del progetto del 02/10/2026). F9.4: aggiunto TC-13 (redatto su richiesta del responsabile del progetto del 05/10/2026). F9.5: aggiunto TC-14 (redatto su richiesta del responsabile del progetto del 05/10/2026, da approvare). SPEC Rev09: TC-14 riscritto per il rinnovo senza contratto (redatto su decisione del responsabile del progetto del 05/10/2026, da approvare). SPEC Rev11: aggiunti TC-15 e TC-16 (redatti su decisione del responsabile del progetto del 05/10/2026, bozza da approvare). SPEC Rev13: TC-15 riscritto sulle fasi della richiesta di RDA, aggiunto TC-17 (redatti su decisione del responsabile del progetto del 07/10/2026, bozza da approvare). SPEC Rev14: TC-15 (e) aggiornato ai tre passi della fattura (stessa origine, bozza da approvare). SPEC Rev15: aggiunto TC-18 (stessa origine, bozza da approvare).

I valori sono stati calcolati a mano e verificati con uno script indipendente. **Se un test non passa, l'errore è nel codice, non nel caso.** Un caso si modifica solo con l'approvazione del responsabile del progetto e insieme a una nuova revisione della SPEC.

Convenzioni valide per tutti i casi:
- importi in euro, IVA esclusa;
- arrotondamento `ROUND_HALF_UP` al centesimo, con il residuo sull'ultimo anno o sull'ultima rata;
- i giorni si contano estremi inclusi.

---

## TC-01 — Competenza pro-rata a giorni (correzione del bug Excel)

SPEC §5.2 (vista Competenza) e §2.1 (bug dei mesi).

Input:
- voce fissa 4.800,00 €;
- periodo di servizio dal 21/12/2025 al 20/12/2026 (12 mesi, 365 giorni).

Output atteso (competenza):

| Anno | Giorni | Importo |
|---|---|---|
| 2025 | 11 | 144,66 |
| 2026 | 354 | 4.655,34 |
| **Totale** | 365 | **4.800,00** |

Controllo negativo: il vecchio Excel dava 400,00 + 4.800,00 = 5.200,00 (108%). Il totale di competenza deve essere **sempre** uguale al valore del contratto.

## TC-02 — Pluriennale pagato in anticipo in un'unica soluzione

SPEC §5.2. Il caso è modellato su "AutoCAD LT 36 mesi, spesa liquidata nel 2023".

Input:
- voce fissa 21.990,06 €;
- servizio dal 24/03/2023 al 23/03/2026 (1.096 giorni);
- fatturazione `Una tantum`, anticipata, fattura il 24/03/2023;
- OdA emesso il 10/03/2023.

Output atteso:

| Anno | Impegno | Cassa (data fattura) | Competenza (giorni) |
|---|---|---|---|
| 2023 | 21.990,06 | 21.990,06 | 5.678,09 (283 gg) |
| 2024 | 0,00 | 0,00 | 7.343,40 (366 gg) |
| 2025 | 0,00 | 0,00 | 7.323,33 (365 gg) |
| 2026 | 0,00 | 0,00 | 1.645,24 (82 gg) |
| **Totale** | 21.990,06 | 21.990,06 | 21.990,06 |

## TC-03 — Posticipato trimestrale con pagamento a 60 giorni

SPEC §4 (Piano di fatturazione) e §5.2.

Input:
- canone fisso 24.000,00 € su 24 mesi, dal 01/07/2026 al 30/06/2028;
- fatturazione `Posticipata`, trimestrale, rate uguali;
- giorni di pagamento: 60 d.f.f.m. (data di pagamento = fine del mese di data fattura + 60 giorni). La data di pagamento è informativa e non entra nel budget (SPEC §5.2).

Scadenzario atteso (8 rate da 3.000,00):

| # | Data fattura | Data pagamento stimata |
|---|---|---|
| 1 | 30/09/2026 | 30/11/2026 |
| 2 | 31/12/2026 | 31/03/2027 |
| 3 | 31/03/2027 | 31/05/2027 |
| 4 | 30/06/2027 | 31/08/2027 |
| 5 | 30/09/2027 | 30/11/2027 |
| 6 | 31/12/2027 | 29/02/2028 |
| 7 | 31/03/2028 | 31/05/2028 |
| 8 | 30/06/2028 | 31/08/2028 |

Aggregati attesi:

| Anno | Cassa (data fattura) | Competenza |
|---|---|---|
| 2026 | 6.000,00 | 6.041,04 (184 gg) |
| 2027 | 12.000,00 | 11.983,58 (365 gg) |
| 2028 | 6.000,00 | 5.975,38 (182 gg) |

## TC-04 — Anticipato annuale su tre anni

Input:
- 3.000,00 € su 36 mesi, dal 03/03/2026 al 02/03/2029;
- fatturazione `Anticipata`, annuale.

Scadenzario atteso: 3 rate da 1.000,00 €, con data fattura 03/03/2026, 03/03/2027 e 03/03/2028.

Cassa per data fattura: 2026 = 1.000,00; 2027 = 1.000,00; 2028 = 1.000,00; 2029 = 0,00.

## TC-05 — Quota variabile: fisso / probabile / massimo

SPEC §5.2 (livelli). Il caso è modellato su "Reperibilità ICT".

Input:
- fisso 6.000,00 €;
- massimale variabile 14.000,00 €;
- stima di consumo del variabile 30%.

Output atteso (valore contrattuale):

| Livello | Importo |
|---|---|
| Fisso | 6.000,00 |
| Probabile | 10.200,00 |
| Massimo | 20.000,00 |

Vincoli:
- la stima di consumo deve essere compresa tra 0% e 100%;
- il livello massimo non può mai essere inferiore al probabile.

## TC-06 — Data limite di avvio e alert

SPEC §5.1.

Parametri:
- lead time: affidamento diretto = 4 mesi, procedura negoziata = 9 mesi;
- finestra 🟡 = 3 mesi.

Base comune: data di fine 31/12/2026, decisione del fabbisogno `Rinnovare`.

| # | Procedura | Oggi | Stato pratica | Successore | Data limite attesa | Alert atteso |
|---|---|---|---|---|---|---|
| a | diretto | 30/09/2026 | Non avviata | no | 31/08/2026 | 🟠 |
| b | diretto | 15/06/2026 | Non avviata | no | 31/08/2026 | 🟡 |
| c | diretto | 15/01/2026 | Non avviata | no | 31/08/2026 | 🟢 |
| d | diretto | 30/09/2026 | RDA predisposta | no | 31/08/2026 | 🟡 (pratica avanzata oltre `Offerta richiesta`: resta 🟡 fino alla scadenza) |
| e | diretto | 05/01/2027 | RDA predisposta | no | 31/08/2026 | 🔴 |
| f | diretto | 05/01/2027 | — | sì, attivo dal 01/01/2027 | — | nessuno |
| g | negoziata | 30/06/2026 | Non avviata | no | 31/03/2026 | 🟠 |

La sottrazione dei mesi segue la logica di fine mese (SPEC §5.1): una data di fine mese resta a fine mese. 31/12 − 4 mesi = 31/08; 31/12 − 9 mesi = 31/03; 30/06 − 4 mesi = 28/02 (29/02 negli anni bisestili); 30/11 − 3 mesi = 31/08.

Con decisione `Dismettere` l'alert non si calcola mai.

Il caso (d) è una regola esplicita: una pratica avviata oltre la data limite non è 🟠 ma 🟡, perché qualcuno ci sta già lavorando.

## TC-07 — Rinnovi previsti ricorsivi

SPEC §5.3.

Input:
- fabbisogno con decisione `Rinnovare`;
- contratto attivo dal 01/01/2026 al 31/12/2026, 10.000,00 € fissi, `Anticipata` annuale;
- adeguamento 3%;
- orizzonte al 31/12/2028;
- nessuna stima manuale.

Contratti previsti attesi:

| # | Periodo | Importo | Rata (data fattura) |
|---|---|---|---|
| P1 | 01/01/2027–31/12/2027 | 10.300,00 | 01/01/2027 |
| P2 | 01/01/2028–31/12/2028 | 10.609,00 | 01/01/2028 |

Nessun P3 (fuori orizzonte).

Varianti:
- con stima manuale sul fabbisogno di 12.000,00 € → P1 = 12.000,00 e P2 = 12.360,00 (l'adeguamento parte dalla stima);
- con decisione `Dismettere` → nessun contratto previsto;
- se un contratto reale successore viene registrato, P1 e P2 vengono sostituiti e non si sommano al reale.

Impegno (default: anno di inizio del servizio): 2027 = 10.300,00; 2028 = 10.609,00.

## TC-08 — Normalizzazione in import

SPEC §7.

| Input grezzo | Campo | Atteso |
|---|---|---|
| `"﻿5800005402"` | numero OdA | `"5800005402"` |
| `"﻿B8A520EED4"` | CIG | `"B8A520EED4"` |
| `"n/a"`, `"N/A"`, `"n/d"`, `""`, `None` | qualsiasi campo codice | `NULL` |
| `"  POSDATA S.r.l. "` | fornitore | `"POSDATA S.r.l."` (trim) |
| `"B941B595B"` | CIG | valore conservato + anomalia `CIG_LUNGHEZZA` nel report |
| `580006042` | numero OdA | valore conservato + anomalia `ODA_FORMATO` |
| `62700` | conto COGE | valore conservato + anomalia `CONTO_SCONOSCIUTO` (non presente nel piano dei conti) |
| data di attivazione vuota con durata valorizzata | contratto | importato con data `NULL`, anomalia `DATA_MANCANTE`, escluso dai calcoli di budget e segnalato |
| due righe con stesso OdA e stesso CIG e stesso periodo | contratto | un solo contratto con due voci |
| due righe con stesso OdA e stesso CIG ma periodi diversi | contratto | due contratti distinti + anomalia `ODA_RIUSATO` |

L'import con `--dry-run` non scrive nulla sul database e produce lo stesso report. Rieseguire l'import sugli stessi file non crea duplicati: l'import è idempotente.

Il file `tests/fixtures/contratti_it_sample.xlsx` riproduce tutte queste anomalie (nomi e importi falsi).

## TC-09 — Autenticazione LDAP e ruoli

SPEC §8.1. I test girano contro un server LDAP di test (OpenLDAP via `slapdtest` di python-ldap, oppure un mock), mai contro l'AD reale.

| Utente di test | Gruppi | Atteso |
|---|---|---|
| `mrossi` | `GG_Contratti_Editor` | login ok; può creare e modificare |
| `lbianchi` | `GG_Contratti_Reader` | login ok; sola lettura; 403 sulle viste di modifica |
| `gverdi` | gruppo annidato dentro `GG_Contratti_Admin` | login ok; amministratore |
| `nnessuno` | nessun gruppo applicativo | login rifiutato |
| `mrossi` | password errata | login rifiutato + riga nel log |
| LDAP non raggiungibile | — | messaggio d'errore generico, nessun dettaglio tecnico all'utente; l'account break-glass locale funziona |

## TC-10 — Proroghe esercitate più volte

SPEC §4 (Proroga), §5.1 (data di fine effettiva), §5.2 (impegno e competenza delle voci di proroga).

Parametri: lead time affidamento diretto = 4 mesi.

Input:
- contratto in affidamento diretto, OdA emesso il 15/03/2025, dal 01/04/2025, 12 mesi (data di fine 31/03/2026);
- voce base: fisso 12.000,00 €, `Anticipata` annuale;
- proroga 1: atto del 10/02/2026, nuova data di fine 30/09/2026; voce di proroga 6.000,00 €, `Una tantum`, anticipata;
- proroga 2: atto del 01/09/2026, nuova data di fine 31/03/2027; voce di proroga 6.300,00 €, `Una tantum`, anticipata.

Date attese:
- data di fine effettiva: 31/03/2027 (la più lontana tra le proroghe);
- data limite di avvio: 30/11/2026 (31/03/2027 − 4 mesi);
- periodo di servizio della voce di proroga 1: 01/04/2026–30/09/2026 (183 gg); della proroga 2: 01/10/2026–31/03/2027 (182 gg).

Scadenzario atteso (data fattura): voce base 01/04/2025 = 12.000,00; proroga 1 01/04/2026 = 6.000,00; proroga 2 01/10/2026 = 6.300,00.

Output atteso:

| Anno | Impegno | Cassa (data fattura) | Competenza |
|---|---|---|---|
| 2025 | 12.000,00 | 12.000,00 | 9.041,10 (voce base, 275 gg) |
| 2026 | 12.300,00 | 12.300,00 | 12.143,52 (base 2.958,90 su 90 gg + proroga 1 6.000,00 + proroga 2 3.184,62 su 92 gg) |
| 2027 | 0,00 | 0,00 | 3.115,38 (proroga 2, 90 gg) |
| **Totale** | 24.300,00 | 24.300,00 | 24.300,00 |

Alert con decisione `Rinnovare` e pratica `Non avviata`, senza successore:
- oggi 15/12/2026 → 🟠 (oltre la data limite);
- oggi 15/07/2026 → 🟢 (inizio della finestra gialla: 30/11/2026 − 3 mesi = 31/08/2026, fine mese su fine mese, non ancora raggiunto);
- oggi 15/04/2027 → 🔴.

Il rinnovo previsto (TC-07) parte il 01/04/2027 con la durata originale di 12 mesi e la sola voce base (12.000,00 × (1 + adeguamento)); le voci di proroga non si replicano.

## TC-11 — Importi diversi per periodo (quote annuali)

SPEC §4 (Quota per periodo) e §5.2 (competenza per quota).

Input:
- voce fissa 31.500,00 €, servizio dal 01/07/2026 al 30/06/2029, `Anticipata` annuale, OdA nel 2026;
- quote per periodo:
  - 01/07/2026–30/06/2027: 10.000,00 (365 gg);
  - 01/07/2027–30/06/2028: 10.500,00 (366 gg);
  - 01/07/2028–30/06/2029: 11.000,00 (365 gg).

Scadenzario atteso: 3 rate, ciascuna pari alla sua quota: 01/07/2026 = 10.000,00; 01/07/2027 = 10.500,00; 01/07/2028 = 11.000,00.

Output atteso:

| Anno | Impegno | Cassa (data fattura) | Competenza |
|---|---|---|---|
| 2026 | 31.500,00 | 10.000,00 | 5.041,10 (quota 1, 184 gg) |
| 2027 | 0,00 | 10.500,00 | 10.237,59 (quota 1 4.958,90 su 181 gg + quota 2 5.278,69 su 184 gg) |
| 2028 | 0,00 | 11.000,00 | 10.766,52 (quota 2 5.221,31 su 182 gg + quota 3 5.545,21 su 184 gg) |
| 2029 | 0,00 | 0,00 | 5.454,79 (quota 3, 181 gg) |
| **Totale** | 31.500,00 | 31.500,00 | 31.500,00 |

Controllo: senza quote, la stessa voce darebbe in competenza 5.288,32 / 10.490,42 / 10.519,16 / 5.202,10 (pro-rata uniforme sul totale).

Quote incoerenti (non contigue, fuori dal periodo della voce o con somma diversa dal fisso): si ignorano, il calcolo usa l'intera voce e segnala l'anomalia `QUOTE_INCOERENTI`.

## TC-12 — Un contratto che rinnova più contratti (SIM voce e SIM M2M)

ROADMAP F9.3; SPEC §5.1 (alert) e §5.3 (previsti).

Parametri: adeguamento 3%; affidamento diretto, lead time 4 mesi; finestra 🟡 = 3 mesi.

Input:
- fabbisogno A «SIM voce», decisione `Rinnovare`: contratto V dal 01/01/2025, 24 mesi (fine
  31/12/2026), 4.800,00 € fissi, `Anticipata` annuale;
- fabbisogno B «SIM M2M», decisione `Rinnovare`: contratto M dal 01/11/2025, 12 mesi (fine
  31/10/2026), 1.200,00 € fissi, `Anticipata` annuale;
- nessuna pratica avviata, nessuna stima manuale.

**Prima** (oggi 15/11/2026, orizzonte 31/12/2027):

| Contratto | Data limite | Alert | Previsti |
|---|---|---|---|
| V | 31/08/2026 | 🟠 | P1 01/01/2027–31/12/2028: 4.944,00 |
| M | 30/06/2026 | 🔴 (scaduto senza rinnovo) | P1 01/11/2026–31/10/2027: 1.236,00; P2 01/11/2027–31/10/2028: 1.273,08 |

**Operazioni**:
1. B si accorpa in A («Accorpa in…»): M passa ad A, B si archivia;
2. si registra il rinnovo di V: contratto N «SIM voce e M2M» dal 01/01/2027, 24 mesi (fine
   31/12/2028), 9.600,00 € fissi, `Anticipata` annuale, che **sostituisce anche** M.

**Dopo** (oggi 15/11/2026, orizzonte 31/12/2029):
- predecessori di N: V (rinnovo) e M (confluito); successore di V e di M: N;
- alert di V e di M: nessuno (hanno un successore); alert di N: 🟢 (data limite 31/08/2028);
- previsti del fabbisogno A: solo P1 01/01/2029–31/12/2030: 9.888,00 (9.600,00 × 1,03),
  rata 01/01/2029. Nessun previsto parte da V o da M;
- scadenzario di N: 01/01/2027 = 4.800,00; 01/01/2028 = 4.800,00;
- impegno di N (senza data di emissione: anno di inizio): 2027 = 9.600,00.

Cassa per anno del fabbisogno A dopo l'accorpamento (solo contratti reali):

| Anno | V | M | N | Totale |
|---|---|---|---|---|
| 2025 | 2.400,00 | 1.200,00 | — | 3.600,00 |
| 2026 | 2.400,00 | — | — | 2.400,00 |
| 2027 | — | — | 4.800,00 | 4.800,00 |
| 2028 | — | — | 4.800,00 | 4.800,00 |

Regole:
- un contratto ha al massimo un successore: M confluito in N non può essere anche predecessore
  di un altro contratto, né confluire in un secondo;
- si confluisce solo in un contratto dello stesso fabbisogno (prima si accorpa) che inizia dopo
  l'inizio del contratto confluito;
- togliere il collegamento (M non più confluito in N) riporta M senza successore: 🔴.

## TC-13 — Quota OPEX e quota CAPEX nello stesso contratto

SPEC §4 (natura e WBS sulla voce), §5.2 (OPEX e CAPEX mai sommati, CAPEX per WBS), §5.3
(classificazione dei previsti), §5.4 (previsto misto).

Parametri: adeguamento 3%.

Input:
- fabbisogno «Piattaforma di virtualizzazione», cluster IT, decisione `Rinnovare`;
- contratto C dal 01/01/2026, 12 mesi (fine 31/12/2026), senza data di emissione, con due voci:
  - V1 «Supporto annuale»: OPEX, conto O, 6.000,00 € fissi, `Anticipata` annuale;
  - V2 «Licenze perpetue»: CAPEX, WBS di cluster W (cluster IT), conto K, 10.000,00 € fissi,
    `Una tantum`;
- natura del contratto: `OPEX e CAPEX` (si ricava dalle voci).

**Budget 2026** (contratto reale, livello fisso):

| Sezione | Raggruppamento | Fatturato | Ordinato | Competenza |
|---|---|---|---|---|
| OPEX | conto O | 6.000,00 | 6.000,00 | 6.000,00 |
| CAPEX | WBS W → conto K | 10.000,00 | 10.000,00 | 10.000,00 |

Le due sezioni non si sommano: nessun totale di 16.000,00 compare nel budget.

**Previsto P1** (01/01/2027–31/12/2027), due varianti:

(a) senza classificazione dei rinnovi: ogni voce resta com'è.

| Voce prevista | Natura | Conto / WBS | Importo |
|---|---|---|---|
| da V1 | OPEX | conto O | 6.180,00 |
| da V2 | CAPEX | WBS W, conto K | 10.300,00 |

- budget 2027, previsionale, fatturato: OPEX 6.180,00 (rata 01/01/2027); CAPEX 10.300,00
  (rata 01/01/2027);
- piano ordini 2026 (data limite di avvio nel 2026, SPEC Rev16): una riga, natura `OPEX e CAPEX`, quote OPEX 6.180,00 e CAPEX 10.300,00;
  totali per natura: OPEX 6.180,00, CAPEX 10.300,00; filtro CAPEX: la riga resta (è un unico
  ordine) e il totale è solo CAPEX, 10.300,00.

(b) V2 con «natura nei rinnovi» OPEX e «conto nei rinnovi» O2 (licenze rinnovate come
abbonamento):

| Voce prevista | Natura | Conto / WBS | Importo |
|---|---|---|---|
| da V1 | OPEX | conto O | 6.180,00 |
| da V2 | OPEX | conto O2, nessuna WBS | 10.300,00 |

- budget 2027, previsionale, fatturato: OPEX 16.480,00 (conto O 6.180,00, conto O2
  10.300,00); CAPEX 0,00;
- piano ordini 2026: una riga, natura `OPEX`, 16.480,00;
- il contratto reale C resta `OPEX e CAPEX`: nel budget 2026 nulla cambia.

## TC-14 — Rinnovo senza contratto (dominio)

SPEC §4 (contratto «senza contratto»), §5.1, §5.2, §5.3, §5.4, §5.6.

Parametri: procedura `Affidamento diretto`, lead time 2 mesi; finestra dell'alert giallo 3
mesi.

Input: fabbisogno «Dominio di prova», decisione `Rinnovare`. Contratto C1 dal 15/03/2024, 12
mesi (fine 14/03/2025), voce 300,00 € `Anticipata` annuale. Rinnovo senza contratto C2
registrato da C1: inizio 15/03/2025, 12 mesi, voce riportata con importo 25,00 €.

**Catena e scadenza**: C2 ha C1 come predecessore e nessun numero di contratto; fine 14/03/2026,
data limite 14/01/2026. C1 non ha alert; la sua pratica passa a «Contratto attivo».

**Alert di C2** (pratica non avviata):

| Oggi | Alert |
|---|---|
| 13/10/2025 | 🟢 |
| 14/10/2025 | 🟡 (data limite − 3 mesi) |
| 14/01/2026 | 🟡 |
| 15/01/2026 | 🟠 (data limite superata) |
| 14/03/2026 | 🟠 |
| 15/03/2026 | 🔴 (scaduto senza rinnovo) |

**Budget** (al 01/06/2025, consolidato, OPEX):

| Anno | Fatturato | Ordinato | Competenza |
|---|---|---|---|
| 2024 | 300,00 (C1) | | |
| 2025 | 25,00 (C2) | 25,00 (C2) | 80,00 = 60,00 (C1, 73/365 di 300,00) + 20,00 (C2, 292/365 di 25,00) |
| 2026 | | | 5,00 (C2, 73/365 di 25,00) |

Il rinnovo previsto dal 15/03/2026 entra nel budget 2026 come previsionale.

**Piano ordini 2026**: vuoto (C2 e i suoi previsti sono senza contratto). Controllo: con C2
registrato come contratto, il piano 2026 ha una riga con avvio 15/03/2026.

## TC-15 — Stato della pratica ricavato dalla RDA

SPEC §4 (stato pratica, RDA), §5.1, §5.7. Rev11, riscritto in Rev13; bozza da approvare.

Parametri: procedura `Affidamento diretto`, lead time 4 mesi; finestra dell'alert giallo 3
mesi; RDA ferma dopo 30 giorni, fattura ferma dopo 15 giorni.

Input: fabbisogno «Servizio di prova», decisione `Rinnovare`. Contratto C1 con fine
31/12/2026: data limite 31/08/2026, giallo dal 31/05/2026. Passaggio registrato a mano:
`Offerta ricevuta` il 01/06/2026. RDA R1 collegata alla pratica di C1, referente U1:
creata (bozza) l'08/06/2026, inviata all'addetto il 10/06/2026, rimandata al referente
l'11/06/2026, inviata di nuovo il 12/06/2026, inserita in SAP il 15/06/2026 (numero di 10
cifre), ultimo rilascio il 01/07/2026. Contratto C2, successore di C1 con RDA d'origine R1:
emesso il 20/07/2026, inizio 01/01/2027.

**(a) Percorso ordinario**

| Oggi | Fase di R1 | Stato della pratica (data) | Alert di C1 | R1 nel cruscotto dell'addetto | R1 in «Le mie RDA» di U1 |
|---|---|---|---|---|---|
| 05/06/2026 | — (R1 non esiste) | Offerta ricevuta (01/06/2026, passaggio) | 🟡 | — | — |
| 09/06/2026 | Bozza | Offerta ricevuta (01/06/2026) | 🟡 | no | sì, in evidenza |
| 10/06/2026 | Inviata | RDA richiesta (10/06/2026) | 🟡 | da inserire in SAP | sì |
| 11/06/2026 | Da correggere | Offerta ricevuta (01/06/2026) | 🟡 | no | sì, in evidenza |
| 13/06/2026 | Inviata | RDA richiesta (12/06/2026) | 🟡 | da inserire in SAP | sì |
| 20/06/2026 | Inserita | RDA predisposta (15/06/2026) | 🟡 | da sollecitare per il rilascio | sì |
| 05/07/2026 | Rilasciata | RDA approvata (01/07/2026) | 🟡 | da sollecitare al Procurement | sì |
| 25/07/2026 | Contratto emesso | Contratto emesso (20/07/2026) | nessuno (successore registrato) | no | sì |
| 05/01/2027 | Contratto emesso | Contratto attivo (01/01/2027) | nessuno | no | sì |

Registrare C2 con «Registra contratto da RDA» (o «Registra rinnovo») non scrive il passaggio
`Contratto attivo` (la pratica ha una RDA). Senza documenti di esecuzione né fatture R1 resta
`Contratto emesso`.

**(b) RDA annullata**: R1 annullata il 10/07/2026, C2 non esiste.

| Oggi | Fase di R1 | Stato della pratica | Alert di C1 |
|---|---|---|---|
| 15/07/2026 | Annullata | Offerta ricevuta (ultimo passaggio) | 🟡 |
| 15/09/2026 | Annullata | Offerta ricevuta | 🟡 (oltre la data limite con pratica più avanzata di `Offerta richiesta`) |

Nuova RDA R2 inviata il 20/09/2026: al 25/09/2026 lo stato è `RDA richiesta` (20/09/2026).

**(c) Passaggio successivo meno avanzato**: come (a); il 06/07/2026 si registra a mano
`Offerta richiesta`. Al 07/07/2026 lo stato resta `RDA approvata` (vale il più avanzato).

**(d) Dati precedenti alla 2.0**: pratica senza RDA con il passaggio `RDA predisposta`
importato il 01/10/2026. Al 02/10/2026 lo stato è `RDA predisposta`.

**(e) Ferme**: R1 inserita il 15/06/2026, senza rilascio, non è ferma al 15/07/2026 (30
giorni) ed è ferma al 16/07/2026 (31 giorni).

Fattura FA-1 di un contratto di **servizi**, registrata il 01/03/2026, già presa in carico, assegnata al contratto e convalidata dal referente lo stesso giorno (Rev14, Rev15):

| Oggi | Documenti collegati, trasferimento | Passo da fare | Ferma (15 giorni) |
|---|---|---|---|
| 02/03/2026 | — | RdC | no |
| 06/03/2026 | RdC del 05/03/2026 | MAP (proposto; MIGO per una fornitura) | no |
| 16/03/2026 | RdC | MAP | no (15 giorni) |
| 17/03/2026 | RdC | MAP | sì (16 giorni) |
| 19/03/2026 | RdC, MAP del 18/03/2026 | trasferimento | sì |
| 21/03/2026 | RdC, MAP, trasferita il 20/03/2026 | — (trasferita) | no |

Fuori ordine: con il solo MAP registrato (senza RdC) il passo da fare è la RdC.

**(f) RDA registrata a mano, scollegata, poi collegata**: R3 registrata il 03/02/2026 con
numero SAP e data di inserimento 02/02/2026, senza storico di invio, senza fabbisogno né
contratto: fase `Inserita`, nessuna pratica cambia, nel cruscotto dell'addetto «da sollecitare
per il rilascio». Il 10/02/2026 R3 si collega al contratto in scadenza C5 (pratica `Non
avviata`): dal 10/02/2026 la pratica di C5 è `RDA predisposta` (02/02/2026).

## TC-16 — Esecuzione, residuo e chiusura di un contratto una tantum

SPEC §4 (una tantum, documento di esecuzione, fattura, chiusura), §5.1, §5.3, §5.4, §5.7,
§5.8. Rev11, bozza da approvare.

Input: fabbisogno «Forniture di prova», decisione `Rinnovare`. RDA R1 con contratto F1
**una tantum**: emesso e iniziato il 02/03/2026, durata 1 mese (fine 01/04/2026); voce OPEX,
fisso 10.000,00 €, massimale 2.000,00 €; fatturazione `Una tantum`, rata unica di 10.000,00
con data fattura 02/03/2026.

**Una tantum**: nessun alert (anche dopo il 01/04/2026), nessun contratto previsto, nessuna
riga nel piano ordini 2026 e 2027; il fabbisogno non segnala la catena interrotta.

**Budget 2026** (OPEX, fisso): fatturato 10.000,00; ordinato 10.000,00; competenza 10.000,00
(02/03–01/04/2026, 31 giorni, tutti nel 2026).

**Esecuzione**, eventi in ordine:

| Data | Evento |
|---|---|
| 10/03/2026 | DDT |
| 15/03/2026 | fattura FA-1, 4.000,00 |
| 20/04/2026 | fattura FA-2, 5.000,00, abbinata alla rata (la rata diventa consuntivo, importo 10.000,00 invariato) |
| 28/04/2026 | modello di ricezione materiale, finale |
| 05/05/2026 | fattura FA-3, 3.500,00 |
| 10/05/2026 | chiusura del contratto |

Situazione alle date di controllo:

| Oggi | Fatturato | Residuo sul fisso | Residuo sul massimo | Avanzamento | Da chiudere | Anomalie | Fase di R1 |
|---|---|---|---|---|---|---|---|
| 05/03/2026 | 0,00 | 10.000,00 | 12.000,00 | 0% | — (non finito) | — | Contratto emesso |
| 25/04/2026 | 9.000,00 | 1.000,00 | 3.000,00 | 90% | Attestazione mancante | — | In esecuzione |
| 30/04/2026 | 9.000,00 | 1.000,00 | 3.000,00 | 90% | Fatture mancanti | — | In esecuzione |
| 06/05/2026 | 12.500,00 | −2.500,00 | −500,00 | 125% | Pronto da chiudere | `FATTURATO_OLTRE_MASSIMO` | In esecuzione |
| 11/05/2026 | 12.500,00 | −2.500,00 | −500,00 | 125% | — (chiuso) | `FATTURATO_OLTRE_MASSIMO` | Chiusa |

Il budget non cambia con le fatture: il fatturato del budget 2026 resta 10.000,00 (rata).
Controllo: un import con una fattura per F1 datata 15/05/2026 scarta la riga
(`FATTURA_DOPO_CHIUSURA`); la stessa fattura FA-1 importata di nuovo non si duplica.

## TC-17 — Piano ordini: da avviare, da concludere, ritardi

SPEC §5.4 (Rev16, Rev17), bozza da approvare.

Parametri: procedura `Affidamento diretto`, lead time 4 mesi.

Input: fabbisogno «Servizio di prova», decisione `Rinnovare`. Contratto C dal 01/03/2026, 12
mesi (fine 28/02/2027), 1.200,00 € fissi. Previsto P1 dal 01/03/2027 al 29/02/2028 (2028
bisestile); data limite 28/02/2027 − 4 mesi = 31/10/2026 (fine mese resta fine mese).

- **Da avviare**: al 12/10/2026, piano ordini 2026: P1 da avviare, non in ritardo; il totale
  fisso del piano comprende 1.200,00.
- **Da concludere**: al 12/10/2026, piano ordini 2027: P1 da concludere (avvio 01/03/2027),
  fuori dai totali (totale fisso 0,00); non in ritardo (anno non in corso).
- **Ritardo**: al 15/01/2027, pratica di C `Non avviata`. Piano 2027: P1 da concludere e in
  ritardo (data limite 31/10/2026 passata). Con pratica `Offerta richiesta`: da concludere,
  non in ritardo.
- **Pratica conclusa**: al 15/01/2027, pratica di C `Contratto emesso`: P1 non è nel piano 2027.
- **Servizio già partito**: al 15/04/2027, pratica `Offerta ricevuta`: piano 2027 con P1 da
  concludere e in ritardo (avvio 01/03/2027 passato). Piano 2028 alla stessa data: P1 non c'è.

## TC-19 — Contratto extra budget autorizzato dall'AD

SPEC §4, §5.2, §5.5 bis (Rev19), bozza da approvare.

Input: cluster IT. Contratto ordinario dal 01/01/2026, 12 mesi, canone OPEX 1.200,00 €
anticipato annuale. Autorizzazione AD «EB-2026-01», cluster IT, importo autorizzato 5.000,00 €.
Contratto una tantum dal 01/04/2026, 1 mese, con due voci collegate all'autorizzazione,
fatturazione una tantum: voce OPEX 3.000,00 €; voce CAPEX su WBS di cluster 2.000,00 € fissi +
500,00 € di massimale variabile.

Atteso, budget 2026, cassa, livello fisso:
- OPEX: 1.200,00 (extra budget escluso di default); con extra budget incluso 4.200,00; solo
  extra budget 3.000,00.
- CAPEX: 0,00; solo extra budget 2.000,00.
- Il contratto una tantum si dice «extra budget»; l'ordinario «ordinario».
- Consumato dell'autorizzazione: 3.000,00 + 2.000,00 + 500,00 = 5.500,00; residuo −500,00;
  avviso di sforamento di 500,00 €. Con importo autorizzato 5.500,00: nessun avviso.
- Spese extra budget, cassa, livello fisso: totale 5.000,00.
- Il contratto non compare nel piano ordini.
- Collegare l'autorizzazione a una voce di un contratto non una tantum, o togliere «una
  tantum» a un contratto con voci extra budget: errore di validazione. Autorizzazione di un
  altro cluster: errore.
