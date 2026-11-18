"""Costi accessori previsti di una voce (SPEC §5.2, Rev53).

Contratti con professionisti: in fattura, oltre al valore base prelevato dal contratto, ci sono il
rimborso INPS riconosciuto da contratto, gli oneri previdenziali e le spese vive (Rev42). Non
consumano il contratto ma gravano sul budget. Per non sottostimare la previsione, ogni importo
**previsto** (rata non ancora fatturata, variabile, residuo di un SAL, rinnovo) porta con sé:

- rimborso INPS = importo × % rimborso INPS;
- oneri = (importo + rimborso INPS) × % oneri, come in fattura («ribaltamento», Rev42);
- spese vive: la stima forfettaria della voce, ripartita sugli importi previsti in proporzione
  al loro peso sul totale della voce.

Ogni parte si arrotonda ROUND_HALF_UP al centesimo. Quando una fattura o uno stanziamento prende
il posto di una rata, ne prende il posto per intero, accessori compresi: la fattura porta i suoi
importi reali. Le maggiorazioni non entrano nell'impegno (valore della voce).
"""

from collections.abc import Sequence
from decimal import Decimal

from contratti.engine.importi import ZERO, arrotonda, ripartisci
from contratti.engine.tipi import Voce

CENTO = Decimal(100)


def ha_accessori(voce: Voce) -> bool:
    return bool(voce.rimborso_inps_pct or voce.oneri_pct or voce.spese_vive_stimate)


def maggiorazione(voce: Voce, importo: Decimal) -> Decimal:
    """Rimborso INPS e oneri previdenziali previsti su un importo previsto."""
    if not (voce.rimborso_inps_pct or voce.oneri_pct) or not importo:
        return ZERO
    rimborso = arrotonda(importo * voce.rimborso_inps_pct / CENTO)
    oneri = arrotonda((importo + rimborso) * voce.oneri_pct / CENTO)
    return rimborso + oneri


def spese_vive(voce: Voce, pesi: Sequence[Decimal], totale_voce: Decimal) -> list[Decimal]:
    """Quota delle spese vive stimate per ciascun importo previsto (``pesi``).

    La stima vale per l'intera voce (``totale_voce``, il fisso): agli importi previsti va la
    parte proporzionale al loro peso sul totale; senza totale, tutta la stima sugli importi.
    """
    stima = arrotonda(voce.spese_vive_stimate or ZERO)
    if not stima or not pesi:
        return [ZERO] * len(pesi)
    somma = sum(pesi, ZERO)
    if totale_voce and somma < totale_voce:
        stima = arrotonda(stima * somma / totale_voce)
    return ripartisci(stima, list(pesi))


def per_rate(voce: Voce, importi: Sequence[Decimal]) -> list[Decimal]:
    """Accessori previsti di ogni rata: maggiorazione della rata più la sua quota di spese vive.

    Le spese vive si ripartiscono su tutte le rate della voce (consuntivate o no), in
    proporzione agli importi; se sono tutti zero, in parti uguali.
    """
    if not importi:
        return []
    quote_spese = spese_vive(voce, importi, ZERO)
    return [maggiorazione(voce, i) + s for i, s in zip(importi, quote_spese, strict=True)]
