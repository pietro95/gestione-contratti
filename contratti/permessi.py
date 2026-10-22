"""Permessi e visibilità per cluster (F9.2, ROADMAP «Permessi»).

- Admin: modifica tutto. Editor: modifica solo i fabbisogni (e i loro contratti) dei cluster
  assegnati, o di tutti con l'assegnazione TUTTI. Reader: legge tutto, non modifica.
- Rev25: un'assegnazione può essere limitata a un sottocluster: l'Editor modifica solo i
  fabbisogni di quel sottocluster. Un'assegnazione senza sottocluster vale per tutto il
  cluster. La visibilità resta per cluster.
- Transizione: finché non è mai stata registrata un'assegnazione (struttura non ancora
  caricata), gli Editor modificano tutto, come prima della F9.2. Dalla prima assegnazione
  valgono le regole per cluster, anche se poi le assegnazioni si archiviano (SPEC §8.1).
- Visibilità: di default ognuno vede i propri cluster; gli altri a richiesta (``?area=tutti``).
  Chi non ha cluster assegnati (o ha TUTTI) vede tutto.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

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


def sottocluster_assegnati(user) -> frozenset[int]:
    """Pk dei sottocluster assegnati singolarmente (assegnazioni limitate a un sottocluster)."""
    return frozenset(a.sottocluster_id for a in _assegnazioni(user) if a.sottocluster_id)


def _cluster_interi(user) -> frozenset[int]:
    return frozenset(
        a.cluster_id for a in _assegnazioni(user) if a.cluster_id and not a.sottocluster_id
    )


def struttura_caricata() -> bool:
    """È mai stata registrata un'assegnazione di cluster? (anche archiviata)"""
    return m.AssegnazioneCluster.objects.exists()


def conti_per_cluster() -> bool:
    """Il piano dei conti ha i cluster (struttura caricata): da qui il cluster è obbligatorio."""
    return m.ContoCoge.objects.filter(clusters__isnull=False).exists()


def cluster_modificabili(user) -> frozenset[int] | None:
    """Cluster in cui l'utente può modificare qualcosa; ``None`` = tutti, vuoto = nessuno.

    Comprende i cluster di cui ha solo dei sottocluster: il dettaglio per fabbisogno è in
    ``puo_modificare_fabbisogno``.
    """
    ruolo = role_of(user)
    if ruolo not in WRITE_ROLES:
        return frozenset()
    if ruolo == ADMIN or not struttura_caricata():
        return None
    return cluster_assegnati(user)


def puo_modificare_in(user, cluster_id, sottocluster_id=None) -> bool:
    """L'utente può modificare i fabbisogni di questo cluster e sottocluster?"""
    ruolo = role_of(user)
    if ruolo not in WRITE_ROLES:
        return False
    if ruolo == ADMIN or not struttura_caricata():
        return True
    if cluster_assegnati(user) is None:  # TUTTI
        return True
    if cluster_id in _cluster_interi(user):
        return True
    return sottocluster_id is not None and sottocluster_id in sottocluster_assegnati(user)


def puo_modificare(user, *cluster_ids) -> bool:
    """L'utente può modificare in tutti i cluster dati?"""
    ammessi = cluster_modificabili(user)
    if ammessi is None:
        return True
    return all(c in ammessi for c in cluster_ids) if cluster_ids else bool(ammessi)


def verifica(user, *cluster_ids) -> None:
    """403 se l'utente non può modificare in uno dei cluster dati (anche solo in parte)."""
    if not puo_modificare(user, *cluster_ids):
        raise PermissionDenied("Fabbisogno di un cluster che non ti è assegnato.")


def fabbisogno_del(oggetto) -> m.Fabbisogno:
    """Fabbisogno di un fabbisogno, contratto, voce, rata, stanziamento, proroga o competenza."""
    if isinstance(oggetto, m.Fabbisogno):
        return oggetto
    if isinstance(oggetto, m.CompetenzaDichiarata):
        return oggetto.fabbisogno
    if isinstance(oggetto, m.Contratto):
        return oggetto.fabbisogno
    if isinstance(oggetto, m.VoceContratto | m.Proroga | m.OpzioneContratto):
        return oggetto.contratto.fabbisogno
    if isinstance(oggetto, m.Rata):
        return oggetto.piano.voce.contratto.fabbisogno
    if isinstance(oggetto, m.Stanziamento):
        return oggetto.voce.contratto.fabbisogno
    raise TypeError(f"Oggetto senza fabbisogno: {type(oggetto).__name__}")


def puo_modificare_fabbisogno(user, fabbisogno) -> bool:
    return puo_modificare_in(user, fabbisogno.cluster_id, fabbisogno.sottocluster_id)


def ambito_del(oggetto) -> tuple[int, int | None]:
    """(cluster, sottocluster) di un oggetto con permessi per sottocluster: anche una RDA."""
    if isinstance(oggetto, m.RichiestaAcquisto):
        return oggetto.cluster_id, oggetto.sottocluster_id
    f = fabbisogno_del(oggetto)
    return f.cluster_id, f.sottocluster_id


def puo_modificare_oggetto(user, oggetto) -> bool:
    return puo_modificare_in(user, *ambito_del(oggetto))


def verifica_oggetto(user, oggetto) -> None:
    """403 se l'utente non può modificare l'oggetto (cluster e sottocluster)."""
    if not puo_modificare_oggetto(user, oggetto):
        raise PermissionDenied("Appartiene a un cluster o sottocluster che non ti è assegnato.")


def fabbisogni_modificabili(user, qs=None):
    """I fabbisogni in cui l'utente può modificare (tendine dei form)."""
    qs = m.Fabbisogno.objects.all() if qs is None else qs
    ammessi = cluster_modificabili(user)
    if ammessi is None:
        return qs
    return qs.filter(
        Q(cluster_id__in=_cluster_interi(user))
        | Q(sottocluster_id__in=sottocluster_assegnati(user))
    )


def sottocluster_modificabili(user, qs=None):
    """I sottocluster in cui l'utente può modificare (tendina del fabbisogno)."""
    qs = m.Sottocluster.objects.all() if qs is None else qs
    if cluster_modificabili(user) is None:
        return qs
    return qs.filter(
        Q(cluster_id__in=_cluster_interi(user)) | Q(pk__in=sottocluster_assegnati(user))
    )


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


def selezione_filtro(user, valori: list[str]) -> list[str]:
    """Valori selezionati nella tendina «Cluster», anche più di uno.

    Nessun valore: i miei cluster (o tutti, per chi non ne ha). «tutti» prevale sul resto.
    """
    valori = [v for v in valori if v]
    if not valori:
        return [MIEI if cluster_propri(user) else TUTTI]
    if TUTTI in valori:
        return [TUTTI]
    return list(dict.fromkeys(valori))


def id_sottocluster(valore) -> int | None:
    """Il parametro «sottocluster» dei filtri: id intero, oppure ``None`` (vuoto o non valido)."""
    try:
        return int(valore) if valore not in (None, "") else None
    except (TypeError, ValueError):
        return None


def descrivi_sottocluster(valore) -> str:
    """«Sottocluster: ICT · IT» o «Sottocluster: tutti», per intestazioni ed export."""
    sottocluster = id_sottocluster(valore)
    trovato = (
        m.Sottocluster.objects.select_related("cluster").filter(pk=sottocluster).first()
        if sottocluster
        else None
    )
    return f"Sottocluster: {trovato}" if trovato else "Sottocluster: tutti"


def descrivi_filtro(codici) -> str:
    """«Cluster: IT (nome), TLC (nome)» o «Cluster: tutti», per intestazioni ed export."""
    if not codici:
        return "Cluster: tutti"
    nomi = dict(m.Cluster.objects.filter(codice__in=codici).values_list("codice", "nome"))
    return "Cluster: " + ", ".join(f"{c} ({nomi[c]})" if nomi.get(c, c) != c else c for c in codici)


def scelte_filtro(user) -> list[tuple[str, str]]:
    """Opzioni della tendina «Cluster»: i miei, tutti, poi ciascun cluster."""
    propri = cluster_propri(user)
    scelte = []
    if propri:
        scelte.append((MIEI, "I miei cluster (" + ", ".join(c.codice for c in propri) + ")"))
    scelte.append((TUTTI, "Tutti i cluster"))
    return scelte + m.scelte_cluster()


def _ha_funzione(user, funzione: str, cache_attr: str) -> bool:
    cache = getattr(user, cache_attr, None)
    if cache is None:
        nome = (getattr(user, "username", "") or "").strip().lower()
        cache = m.FunzioneUtente.objects.filter(
            username__iexact=nome, funzione=funzione, archiviato=False
        ).exists()
        setattr(user, cache_attr, cache)
    return cache


def e_addetto(user) -> bool:
    """Ha la funzione «Amministrazione acquisti» (SPEC §8.1, Rev13)? Non dà permessi da sola."""
    return _ha_funzione(user, m.FunzioneUtente.Funzione.AMMINISTRAZIONE_ACQUISTI, "_e_addetto")


def e_addetto_rilascio(user) -> bool:
    """Ha la funzione «Addetto al rilascio» (RdC, MAP e MIGO su SAP)? Non dà permessi da sola."""
    return _ha_funzione(user, m.FunzioneUtente.Funzione.RILASCIO_SAP, "_e_addetto_rilascio")


def puo_rilasciare(user) -> bool:
    """Rilascia su SAP RDA, RdC, MAP e MIGO: solo chi ha la funzione «Addetto al rilascio» e
    può scrivere (nemmeno l'Admin senza la funzione; il Reader mai)."""
    return role_of(user) in WRITE_ROLES and e_addetto_rilascio(user)
