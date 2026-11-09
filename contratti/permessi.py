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

from accounts.roles import (
    ADDETTO_AMMINISTRATIVO,
    ADDETTO_RILASCIO,
    ADMIN,
    WRITE_ROLES,
    ha_funzione,
    role_of,
)
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
    """Pk dei cluster assegnati all'utente; ``None`` = tutti (assegnazione TUTTI, o funzione
    «Amministrazione acquisti», Rev39)."""
    if e_addetto(user):
        return None
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
    """Il piano dei conti ha i sottocluster (struttura caricata): da qui sono obbligatori."""
    return m.ContoCoge.objects.filter(sottocluster__isnull=False).exists()


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
        cluster = oggetto.sottocluster.cluster_id if oggetto.sottocluster_id else oggetto.cluster_id
        return cluster, oggetto.sottocluster_id
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


# --- Filtro per sottocluster (Rev36) ---------------------------------------------------


def sottocluster_propri(user) -> list[m.Sottocluster]:
    """I sottocluster attivi dell'utente: la selezione di default dei filtri.

    Un'assegnazione al cluster intero li dà tutti; una limitata a un sottocluster, solo quello.
    Chi non ha assegnazioni (o ha TUTTI) li vede tutti.
    """
    attivi = m.Sottocluster.objects.filter(archiviato=False).select_related("cluster")
    if user is None or cluster_assegnati(user) is None or not _assegnazioni(user):
        return list(attivi)
    propri = list(
        attivi.filter(
            Q(cluster_id__in=_cluster_interi(user)) | Q(pk__in=sottocluster_assegnati(user))
        )
    )
    return propri or list(attivi)


def _id_validi(valori) -> list[int]:
    visti: dict[int, None] = {}
    for valore in valori or []:
        try:
            visti[int(valore)] = None
        except (TypeError, ValueError):
            continue
    return list(visti)


def selezione_sottocluster(user, valori) -> list[int]:
    """Id dei sottocluster scelti nel filtro; nessun valore valido = i propri (default).

    «tutti» (anche tra altri valori) sceglie tutti i sottocluster attivi.
    """
    valori = [v for v in (valori or []) if v not in (None, "")]
    if TUTTI in valori:
        return [s.pk for s in m.Sottocluster.objects.filter(archiviato=False)]
    return _id_validi(valori) or [s.pk for s in sottocluster_propri(user)]


def filtro_sottocluster(user, valori) -> tuple[int, ...]:
    """Id da usare nelle query; vuoto = nessun filtro (sono scelti tutti i sottocluster attivi).

    Così i dati senza sottocluster (WBS a progetto) e quelli di sottocluster archiviati restano
    visibili quando non si restringe niente.
    """
    scelti = selezione_sottocluster(user, valori)
    attivi = set(m.Sottocluster.objects.filter(archiviato=False).values_list("pk", flat=True))
    return () if attivi <= set(scelti) else tuple(sorted(scelti))


def albero_sottocluster(user, valori) -> list[dict]:
    """I cluster con i loro sottocluster e cosa è scelto, per la tendina ad albero."""
    scelti = set(selezione_sottocluster(user, valori))
    per_cluster: dict[int, dict] = {}
    for s in m.Sottocluster.objects.filter(
        archiviato=False, cluster__archiviato=False
    ).select_related("cluster"):
        nodo = per_cluster.setdefault(s.cluster_id, {"cluster": s.cluster, "sottocluster": []})
        nodo["sottocluster"].append({"pk": s.pk, "nome": s.nome, "scelto": s.pk in scelti})
    albero = sorted(per_cluster.values(), key=lambda n: n["cluster"].codice)
    for nodo in albero:
        nodo["sottocluster"].sort(key=lambda x: x["nome"].lower())
        n_scelti = sum(x["scelto"] for x in nodo["sottocluster"])
        nodo["n_scelti"] = n_scelti
        nodo["tutti"] = n_scelti == len(nodo["sottocluster"])
        nodo["alcuni"] = 0 < n_scelti < len(nodo["sottocluster"])
    return albero


def contesto_filtro_sottocluster(user, valori) -> dict:
    """Contesto del partial ``_filtro_sottocluster.html`` (anche per i form dei report)."""
    albero = albero_sottocluster(user, valori)
    totale = sum(len(n["sottocluster"]) for n in albero)
    scelti = sum(n["n_scelti"] for n in albero)
    if totale and scelti == totale:
        etichetta = "Tutti i sottocluster"
    elif scelti == 1:
        etichetta = next(
            f"{n['cluster'].codice} · {x['nome']}"
            for n in albero
            for x in n["sottocluster"]
            if x["scelto"]
        )
    else:
        etichetta = f"{scelti} sottocluster su {totale}"
    propri = {s.pk for s in sottocluster_propri(user)}
    return {
        "albero": albero,
        "etichetta": etichetta,
        "n_scelti": scelti,
        "n_totali": totale,
        # I «miei»: si mostra la scorciatoia solo se differiscono da «tutti».
        "propri_ids": propri if len(propri) < totale else set(),
    }


def descrivi_sottocluster_scelti(ids) -> str:
    """«Sottocluster: ICT (tutti), OT · Reti» o «Sottocluster: tutti», per le intestazioni."""
    if not ids:
        return "Sottocluster: tutti"
    scelti = set(ids)
    per_cluster: dict[str, list[m.Sottocluster]] = {}
    for s in m.Sottocluster.objects.filter(pk__in=scelti).select_related("cluster"):
        per_cluster.setdefault(s.cluster.codice, []).append(s)
    parti = []
    for codice in sorted(per_cluster):
        attivi = m.Sottocluster.objects.filter(cluster__codice=codice, archiviato=False)
        tutti = {s.pk for s in attivi}
        if tutti and tutti <= scelti:
            parti.append(f"{codice} (tutti)")
        else:
            parti += [str(s) for s in sorted(per_cluster[codice], key=lambda x: x.nome.lower())]
    return "Sottocluster: " + ", ".join(parti)


def ids_sottocluster(valore) -> tuple[int, ...]:
    """Il filtro per sottocluster: un id, più id o niente (= tutti), sempre come tupla."""
    if not valore:
        return ()
    if isinstance(valore, int):
        return (valore,)
    return tuple(int(v) for v in valore if v)


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


def _ha_funzione(user, funzione: str, gruppo: str, cache_attr: str) -> bool:
    """La funzione viene dal gruppo AD (gruppo Django omonimo, Rev39) oppure dall'assegnazione
    locale in amministrazione (sviluppo, senza AD)."""
    cache = getattr(user, cache_attr, None)
    if cache is None:
        nome = (getattr(user, "username", "") or "").strip().lower()
        cache = ha_funzione(user, gruppo) or (
            bool(nome)
            and m.FunzioneUtente.objects.filter(
                username__iexact=nome, funzione=funzione, archiviato=False
            ).exists()
        )
        setattr(user, cache_attr, cache)
    return cache


def e_addetto(user) -> bool:
    """Ha la funzione «Amministrazione acquisti» (SPEC §8.1, Rev13, Rev39)? Dal gruppo AD
    «Addetto amministrativo» o dall'assegnazione locale. Non dà il ruolo di scrittura da sola
    (lo dà il login con il gruppo AD), ma vale come assegnazione a tutti i cluster."""
    return _ha_funzione(
        user,
        m.FunzioneUtente.Funzione.AMMINISTRAZIONE_ACQUISTI,
        ADDETTO_AMMINISTRATIVO,
        "_e_addetto",
    )


def e_addetto_rilascio(user) -> bool:
    """Ha la funzione «Addetto al rilascio» (RdC e MAP su SAP)? Dal gruppo AD o
    dall'assegnazione locale. Non dà permessi da sola."""
    return _ha_funzione(
        user, m.FunzioneUtente.Funzione.RILASCIO_SAP, ADDETTO_RILASCIO, "_e_addetto_rilascio"
    )


def puo_rilasciare(user) -> bool:
    """Rilascia su SAP RDA, RdC e MAP: solo chi ha la funzione «Addetto al rilascio» e
    può scrivere (nemmeno l'Admin senza la funzione; il Reader mai)."""
    return role_of(user) in WRITE_ROLES and e_addetto_rilascio(user)
