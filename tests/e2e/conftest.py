"""Test end-to-end nel browser (F7): Playwright + Chromium contro il live server di Django.

In CI (``CI=true``) devono girare: se il browser manca falliscono. In locale, senza browser
installato, si saltano. Nessuna risorsa esterna: axe-core è in ``tests/e2e/vendor``.
"""

import datetime
import glob
import os
from decimal import Decimal
from pathlib import Path

import pytest

from accounts.roles import EDITOR, READER

from .. import factories as f

# Playwright sincrono tiene un event loop nel thread dei test: l'ORM lo scambierebbe per
# contesto asincrono. I test sono sequenziali, quindi è sicuro.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

AXE = Path(__file__).parent / "vendor" / "axe-core-4.13.0" / "axe.min.js"
PASSWORD = "password-locale-di-prova"
D = datetime.date


def _in_ci():
    return os.environ.get("CI", "").lower() in {"1", "true", "yes"}


# Contenuto del database di test serializzato da Django dopo le migration (configurazione,
# gruppi, permessi): i test transazionali lo ripristinano prima di ogni test.
_SERIALIZZATO: dict[str, str] = {}


@pytest.fixture(scope="session")
def browser(django_db_setup):
    from django.db import connections

    # Va letto prima di avviare Playwright: dopo, il codice dei test gira in un altro
    # contesto (greenlet) e Django vi apre connessioni nuove, senza questo attributo.
    contenuto = getattr(connections["default"], "_test_serialized_contents", None)
    if contenuto:
        _SERIALIZZATO["default"] = contenuto
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        pytest.fail("playwright non installato") if _in_ci() else pytest.skip("playwright assente")
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as errore:
            # Ambienti con un Chromium già presente ma di versione diversa da quella attesa.
            candidati = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
            if not candidati:
                if _in_ci():
                    raise
                pytest.skip(f"Chromium non disponibile: {errore}")
            b = p.chromium.launch(executable_path=candidati[-1])
        yield b
        b.close()


@pytest.fixture(autouse=True)
def _serializzazione_nel_contesto_dei_test(browser):
    from django.db import connections

    connessione = connections["default"]
    if "default" in _SERIALIZZATO and not hasattr(connessione, "_test_serialized_contents"):
        connessione._test_serialized_contents = _SERIALIZZATO["default"]


@pytest.fixture
def dati(transactional_db):
    """Un contratto con voce e piano, un previsto manuale, molti fornitori (Tom Select)."""
    fornitori = [f.fornitore(f"Fornitore di prova {i:02d} S.r.l.") for i in range(15)]
    fab = f.fabbisogno("Licenze gestionale di prova", decisione="rinnovare")
    c = f.contratto(
        fabbisogno=fab,
        fornitore=fornitori[0],
        data_inizio=D(2026, 1, 1),
        durata_mesi=12,
        numero_contratto="5800000001",
    )
    v = f.voce(c, importo_fisso=Decimal("10000.00"))
    f.piano(v, modalita="anticipata", periodicita="annuale")
    f.fabbisogno(
        "Nuovo servizio di prova",
        previsto_data_avvio=D(2027, 7, 1),
        previsto_durata_mesi=12,
        stima_prossimo_importo=Decimal("5000.00"),
    )
    return {"contratto": c, "voce": v, "fornitori": fornitori, "fabbisogno": fab}


@pytest.fixture
def pagina(browser, live_server, make_user, dati):
    """Pagina del browser con un Editor autenticato e raccolta degli errori JavaScript."""
    make_user("e2e_editor", role=EDITOR)
    make_user("e2e_reader", role=READER)
    contesto = browser.new_context(viewport={"width": 1366, "height": 900}, locale="it-IT")
    pg = contesto.new_page()
    pg.errori = []
    pg.on("pageerror", lambda e: pg.errori.append(str(e)))
    pg.on("console", lambda msg: pg.errori.append(msg.text) if msg.type == "error" else None)
    pg.base = live_server.url
    pg.goto(f"{live_server.url}/accounts/login/")
    pg.fill("#id_username", "e2e_editor")
    pg.fill("#id_password", PASSWORD)
    pg.click("button[type=submit]")
    pg.wait_for_url(f"{live_server.url}/")
    yield pg
    contesto.close()


def violazioni_axe(pg) -> list[dict]:
    """Violazioni WCAG 2.1 A/AA di impatto grave o critico nella pagina corrente.

    Prima si aspetta la fine della dissolvenza delle notifiche: a metà animazione il testo è
    semitrasparente e axe misura un contrasto che non è quello reale.
    """
    pg.wait_for_function(
        """() => [...document.querySelectorAll('.toast')].every(t => {
            const s = getComputedStyle(t);
            return s.display === 'none' || s.opacity === '1';
        })"""
    )
    pg.add_script_tag(path=str(AXE))
    risultato = pg.evaluate(
        """async () => await axe.run(document, {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
        })"""
    )
    return [
        {
            "regola": v["id"],
            "impatto": v["impact"],
            "descrizione": v["help"],
            "elementi": [n["target"] for n in v["nodes"]][:5],
        }
        for v in risultato["violations"]
        if v["impact"] in ("serious", "critical")
    ]
