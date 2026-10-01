from contratti import models as m


def navigazione(request):
    """Numero di proposte d'import da valutare, mostrato nella barra laterale."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    aperte = (
        m.PropostaRaggruppamento.objects.filter(stato="proposta").count()
        + m.PropostaPredecessore.objects.filter(stato="proposta").count()
    )
    return {"proposte_aperte": aperte}
