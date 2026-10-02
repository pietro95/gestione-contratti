from contratti import models as m
from contratti import selettori


def navigazione(request):
    """Conteggi della barra laterale: proposte d'import e piani di fatturazione da verificare."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    aperte = (
        m.PropostaRaggruppamento.objects.filter(stato="proposta").count()
        + m.PropostaPredecessore.objects.filter(stato="proposta").count()
    )
    return {
        "proposte_aperte": aperte,
        "piani_da_verificare": selettori.voci_piano_da_verificare().count(),
    }
