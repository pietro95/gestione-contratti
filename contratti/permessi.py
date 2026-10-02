"""Permessi e visibilità per cluster (F9.2, ROADMAP «Permessi»).

- Admin: modifica tutto. Editor: modifica solo i fabbisogni (e i loro contratti) dei cluster
  assegnati, o di tutti con l'assegnazione TUTTI. Reader: legge tutto, non modifica.
- Transizione: finché non esiste alcuna assegnazione (struttura non ancora caricata), gli
  Editor modificano tutto, come prima della F9.2.
- Visibilità: di default ognuno vede i propri cluster; gli altri a richiesta (``?area=tutti``).
  Chi non ha cluster assegnati (o ha TUTTI) vede tutto.
"""

from django.core.exceptions import PermissionDenied

from accounts.roles import ADMIN, WRITE_ROLES, role_of
from contratti import models as m

# Valori speciali del parametro ``area`` nei filtri.
MIEI = "miei"
TUTTI = "tutti"


def _assegnazioni(user) -> list[m.AssegnazioneCluster]:
    cache = getattr(user, "_assegnazioni_cluster", None)
    if cache is None:
        nome = (getattr(user, "username", "") or "").strip().lower()
        cache = list(
            m.AssegnazioneCluster.objects.filter(username=nome, archiviato=False).select_related(
                "cluster"
            )
        )
        user._assegnazioni_cluster = cache
    return cache


def cluster_assegnati(user) -> frozenset[int] | None:
    """Pk dei cluster assegnati all'utente; ``None`` = tutti (assegnazione TUTTI)."""
    assegnazioni = _assegnazioni(user)
    if any(a.cluster_id is None for a in assegnazioni):
        return None
    return frozenset(a.cluster_id for a in assegnazioni)


def cluster_modificabili(user) -> frozenset[int] | None:
    """Cluster in cui l'utente può modificare; ``None`` = tutti, vuoto = nessuno."""
    ruolo = role_of(user)
    if ruolo not in WRITE_ROLES:
        return frozenset()
    if ruolo == ADMIN or not m.AssegnazioneCluster.objects.filter(archiviato=False).exists():
        return None
    return cluster_assegnati(user)


def puo_modificare(user, *cluster_ids) -> bool:
    """L'utente può modificare in tutti i cluster dati?"""
    ammessi = cluster_modificabili(user)
    if ammessi is None:
        return True
    return all(c in ammessi for c in cluster_ids) if cluster_ids else bool(ammessi)


def verifica(user, *cluster_ids) -> None:
    """403 se l'utente non può modificare in uno dei cluster dati."""
    if not puo_modificare(user, *cluster_ids):
        raise PermissionDenied("Fabbisogno di un cluster che non ti è assegnato.")


def cluster_del(oggetto) -> int:
    """Cluster di un fabbisogno, contratto, voce, rata o proroga."""
    if isinstance(oggetto, m.Fabbisogno):
        return oggetto.cluster_id
    if isinstance(oggetto, m.Contratto):
        return oggetto.fabbisogno.cluster_id
    if isinstance(oggetto, m.VoceContratto | m.Proroga | m.OpzioneContratto):
        return oggetto.contratto.fabbisogno.cluster_id
    if isinstance(oggetto, m.Rata):
        return oggetto.piano.voce.contratto.fabbisogno.cluster_id
    raise TypeError(f"Oggetto senza cluster: {type(oggetto).__name__}")


def verifica_oggetto(user, oggetto) -> None:
    verifica(user, cluster_del(oggetto))


def fabbisogni_modificabili(user, qs=None):
    """I fabbisogni in cui l'utente può modificare (tendine dei form)."""
    qs = m.Fabbisogno.objects.all() if qs is None else qs
    ammessi = cluster_modificabili(user)
    return qs if ammessi is None else qs.filter(cluster_id__in=ammessi)


def cluster_propri(user) -> list[m.Cluster]:
    """I cluster dell'utente per la vista di default; vuoto = vede tutto."""
    if cluster_assegnati(user) is None:
        return []
    return sorted(
        (a.cluster for a in _assegnazioni(user) if not a.cluster.archiviato),
        key=lambda c: c.codice,
    )


def codici_filtro(user, valori: list[str]) -> list[str]:
    """Codici di cluster da filtrare per il parametro ``area``; vuoto = tutti.

    Nessun valore o «miei»: i cluster dell'utente. «tutti»: nessun filtro. Altrimenti i
    codici indicati (anche più di uno).
    """
    valori = [v for v in valori if v]
    if TUTTI in valori:
        return []
    if not valori or MIEI in valori:
        return [c.codice for c in cluster_propri(user)]
    return valori


def scelta_filtro(user, valori: list[str]) -> str:
    """Valore selezionato nella tendina «Cluster»."""
    valori = [v for v in valori if v]
    if not valori:
        return MIEI if cluster_propri(user) else TUTTI
    return valori[0] if len(valori) == 1 else MIEI


def scelte_filtro(user) -> list[tuple[str, str]]:
    """Opzioni della tendina «Cluster»: i miei, tutti, poi ciascun cluster."""
    propri = cluster_propri(user)
    scelte = []
    if propri:
        scelte.append((MIEI, "I miei cluster (" + ", ".join(c.codice for c in propri) + ")"))
    scelte.append((TUTTI, "Tutti i cluster"))
    return scelte + m.scelte_cluster()
