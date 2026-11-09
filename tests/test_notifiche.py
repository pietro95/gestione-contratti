"""Notifiche per email (SPEC §5.10, Rev39): destinatari, eventi, promemoria, import."""

import datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from accounts.roles import ADDETTO_AMMINISTRATIVO, ADDETTO_RILASCIO, EDITOR, READER
from contratti import acquisti, fatture, notifiche, promemoria
from contratti import models as m

from . import factories as f
from .test_tc18_fatture import file_tc18

pytestmark = pytest.mark.django_db
D = datetime.date
Tipo = m.DocumentoEsecuzione.Tipo
Funzione = m.FunzioneUtente.Funzione


@pytest.fixture
def utenti(make_user):
    from django.contrib.auth.models import Group

    u = {
        "amm": make_user("amm", role=EDITOR, email="amm@esempio.test"),
        "ril": make_user("ril", role=EDITOR, email="ril@esempio.test"),
        "ref": make_user("ref", role=EDITOR, email="ref@esempio.test"),
        "altro": make_user("altro", role=EDITOR, email="altro@esempio.test"),
        "lettore": make_user("lettore", role=READER, email="lettore@esempio.test"),
        "senza_mail": make_user("senzamail", role=EDITOR),
    }
    # L'addetto amministrativo dal gruppo AD, quello al rilascio dall'assegnazione locale.
    u["amm"].groups.add(Group.objects.get(name=ADDETTO_AMMINISTRATIVO))
    m.FunzioneUtente.objects.create(username="ril", funzione=Funzione.RILASCIO_SAP)
    return u


def destinatari():
    return sorted(a for msg in mail.outbox for a in msg.to)


def test_destinatari_per_funzione(utenti):
    assert [x.username for x in notifiche.addetti_amministrativi()] == ["amm"]
    assert [x.username for x in notifiche.addetti_al_rilascio()] == ["ril"]
    # «Tutti»: Admin ed Editor, non il Reader; l'indirizzo si risolve all'invio.
    assert {x.username for x in notifiche.utenti_operativi()} == {
        "amm", "ril", "ref", "altro", "senzamail",
    }  # fmt: skip
    assert ADDETTO_RILASCIO != ADDETTO_AMMINISTRATIVO


def test_funzione_locale_e_gruppo_non_duplicano(utenti):
    m.FunzioneUtente.objects.create(username="AMM", funzione=Funzione.AMMINISTRAZIONE_ACQUISTI)
    assert [x.username for x in notifiche.addetti_amministrativi()] == ["amm"]


def test_notifiche_spente_senza_server(settings, utenti):
    settings.NOTIFICHE_EMAIL_ATTIVE = False
    assert notifiche.fatture_nuove(3) == 0
    assert mail.outbox == [] and not m.InvioEmail.objects.exists()


def test_errore_di_spedizione_registrato_e_non_blocca(utenti, monkeypatch):
    def guasto(self, fail_silently=False):
        raise OSError("SMTP irraggiungibile")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", guasto)
    assert notifiche.fatture_nuove(2) == 0
    righe = m.InvioEmail.objects.all()
    assert righe and all(r.esito == "errore" and "SMTP" in r.errore for r in righe)


def test_chi_agisce_non_riceve_la_propria_email(utenti):
    notifiche.fatture_nuove(2, utente=utenti["amm"])
    assert "amm@esempio.test" not in destinatari()
    assert len(mail.outbox) == 3


def _rda(utenti, **kw):
    kw.setdefault("cluster", f.cluster("IT"))
    kw.setdefault("descrizione", "Licenze di prova")
    kw.setdefault("intestazione", "Licenze di prova")
    kw.setdefault("origine", m.RichiestaAcquisto.Origine.PORTALE)
    kw.setdefault("referente_utente", utenti["ref"])
    kw.setdefault("fabbisogno", f.fabbisogno("Fabbisogno di prova"))
    kw.setdefault("scopo", "primo_acquisto")
    rda = m.RichiestaAcquisto.objects.create(**kw)
    m.PosizioneRDA.objects.create(
        rda=rda, numero=1, descrizione_breve="Posizione", quantita=1,
        importo_unitario=Decimal("100.00"), gruppo_merci=None,
    )  # fmt: skip
    return rda


def test_rda_inviata_va_all_addetto_amministrativo(utenti, django_capture_on_commit_callbacks):
    rda = _rda(utenti)
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.invia(rda, utenti["ref"])
    assert destinatari() == ["amm@esempio.test"]
    assert "Nuova RDA da inserire" in mail.outbox[0].subject
    assert "https://contratti.esempio.test" + reverse("contratti:rda", args=[rda.pk]) in (
        mail.outbox[0].body
    )
    assert m.InvioEmail.objects.get().tipo == "rda_inviata"


def test_rda_rimandata_va_al_referente(utenti, django_capture_on_commit_callbacks):
    rda = _rda(utenti)
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.invia(rda, utenti["ref"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.rimanda(rda, "Manca il CIG", utenti["amm"])
    assert destinatari() == ["ref@esempio.test"]
    assert "Manca il CIG" in mail.outbox[0].body


def test_rda_inserita_in_sap_va_all_addetto_al_rilascio(utenti, django_capture_on_commit_callbacks):
    rda = _rda(utenti)
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.invia(rda, utenti["ref"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.aggiorna_dati_sap(rda, "5100000099", D(2026, 11, 9), utenti["amm"])
    assert destinatari() == ["ril@esempio.test"]
    assert "5100000099" in mail.outbox[0].subject
    # Una correzione successiva dei dati SAP non rimanda l'avviso.
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        acquisti.aggiorna_dati_sap(rda, "5100000099", D(2026, 11, 10), utenti["amm"])
    assert mail.outbox == []


@pytest.fixture
def fattura_in_lavorazione(utenti):
    contratto = f.contratto(fornitore=f.fornitore("Fornitore Prova S.r.l."))
    f.voce(contratto)
    return m.Fattura.objects.create(
        fornitore=contratto.fornitore,
        contratto=contratto,
        numero="F-1/2026",
        data=D(2026, 10, 30),
        importo_documento=Decimal("100.00"),
        referente=utenti["ref"],
        data_presa_in_carico=D(2026, 11, 2),
    )


def test_fattura_convalidata_avvisa_l_addetto_una_volta(
    utenti, fattura_in_lavorazione, django_capture_on_commit_callbacks
):
    fa = fattura_in_lavorazione
    with django_capture_on_commit_callbacks(execute=True):
        fatture.convalida(fa, "convalidabile", utente=utenti["ref"])
    assert destinatari() == ["amm@esempio.test"]
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        fatture.convalida(fa, "convalidabile", "ancora", utente=utenti["ref"])
        fatture.convalida(fa, "in_attesa", "aspetto", utente=utenti["ref"])
    assert mail.outbox == []


def test_documento_da_rilasciare_avvisa_l_addetto_al_rilascio(
    utenti, fattura_in_lavorazione, django_capture_on_commit_callbacks
):
    fa = fattura_in_lavorazione
    with django_capture_on_commit_callbacks(execute=True):
        fatture.registra_documento(fa, Tipo.ODA, "4600000001", D(2026, 11, 3), utente=utenti["amm"])
    assert destinatari() == ["ril@esempio.test"]
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        fatture.registra_documento(
            fa, Tipo.MIGO, "5000000001", D(2026, 11, 4), utente=utenti["amm"]
        )
    assert mail.outbox == []  # il MIGO non si rilascia


def test_riassegnazione_avvisa_il_nuovo_referente(
    utenti, fattura_in_lavorazione, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        fatture.riassegna(fattura_in_lavorazione, utenti["altro"], utenti["amm"])
    assert destinatari() == ["altro@esempio.test"]


# --- Import delle fatture: avviso con spunta ---------------------------------------------


@pytest.fixture
def import_fatture_pronto(utenti, tmp_path, client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    f.fornitore("Fornitore Prova A S.r.l.")
    f.fornitore("Studio Prova", nome_breve="STUDIOP")
    client.force_login(utenti["amm"])
    percorso = file_tc18(tmp_path)
    risposta = client.post(
        reverse("contratti:importazione_carica", args=["fatture"]),
        {"fatture-file": SimpleUploadedFile("estrazione.xlsx", percorso.read_bytes())},
    )
    assert risposta.status_code == 302, risposta.content[:300]
    return client, risposta.url


def test_anteprima_import_propone_l_avviso(import_fatture_pronto):
    client, url = import_fatture_pronto
    pagina = client.get(url).content.decode()
    assert 'name="avvisa"' in pagina and "nuove fatture da prendere in carico" in pagina


def test_conferma_con_avviso_scrive_a_tutti_gli_operativi(import_fatture_pronto):
    client, url = import_fatture_pronto
    client.post(url + "conferma/", {"avvisa": "1"})
    # Tutti gli operativi con la mail tranne chi ha caricato.
    assert destinatari() == ["altro@esempio.test", "ref@esempio.test", "ril@esempio.test"]
    assert "nuove fatture da prendere in carico" in mail.outbox[0].subject


def test_conferma_senza_spunta_non_invia_nulla(import_fatture_pronto):
    client, url = import_fatture_pronto
    client.post(url + "conferma/", {})
    assert m.Fattura.objects.exists() and mail.outbox == []


def test_import_senza_fatture_nuove_non_invia(import_fatture_pronto, tmp_path):
    client, url = import_fatture_pronto
    client.post(url + "conferma/", {"avvisa": "1"})
    mail.outbox.clear()
    from django.core.files.uploadedfile import SimpleUploadedFile

    percorso = file_tc18(tmp_path, nome="di_nuovo.xlsx")
    ripetuto = client.post(
        reverse("contratti:importazione_carica", args=["fatture"]),
        {"fatture-file": SimpleUploadedFile("di_nuovo.xlsx", percorso.read_bytes())},
    )
    client.post(ripetuto.url + "conferma/", {"avvisa": "1"})
    assert mail.outbox == []


# --- Promemoria periodici ------------------------------------------------------------------


def test_promemoria_rilasci_solo_se_ce_qualcosa(utenti, fattura_in_lavorazione):
    oggi = D(2026, 11, 9)
    assert promemoria.messaggi_rilasci(oggi) == []
    fatture.registra_documento(fattura_in_lavorazione, Tipo.ODA, "4600000001", D(2026, 11, 2))
    [msg] = promemoria.messaggi_rilasci(oggi)
    assert "4600000001" in msg.corpo and msg.chiave == "2026-11-09"
    out = StringIO()
    call_command("invia_promemoria", "--tipo", "rilasci", "--oggi", "2026-11-09", stdout=out)
    assert destinatari() == ["ril@esempio.test"]
    # Stesso giorno: non si rimanda. Il giorno dopo sì.
    call_command("invia_promemoria", "--tipo", "rilasci", "--oggi", "2026-11-09", stdout=out)
    assert len(mail.outbox) == 1
    call_command("invia_promemoria", "--tipo", "rilasci", "--oggi", "2026-11-10", stdout=out)
    assert len(mail.outbox) == 2


def test_promemoria_nel_fine_settimana_e_dry_run(utenti, fattura_in_lavorazione):
    fatture.registra_documento(fattura_in_lavorazione, Tipo.ODA, "4600000001", D(2026, 11, 2))
    out = StringIO()
    call_command("invia_promemoria", "--oggi", "2026-11-14", stdout=out)  # sabato
    assert mail.outbox == [] and "Fine settimana" in out.getvalue()
    out = StringIO()
    call_command("invia_promemoria", "--oggi", "2026-11-09", "--dry-run", stdout=out)
    assert mail.outbox == [] and "4600000001" in out.getvalue()


def test_promemoria_scadenze_un_messaggio_per_referente(utenti):
    ref, altro = utenti["ref"], utenti["altro"]
    scaduto = f.contratto(
        fabbisogno=f.fabbisogno("Servizio scaduto", referente_utente=ref),
        numero_contratto="5800000001",
        data_inizio=D(2024, 1, 1),
        durata_mesi=12,
    )
    f.voce(scaduto)
    f.contratto(
        fabbisogno=f.fabbisogno("Servizio senza referente utente", referente="Mario Rossi"),
        data_inizio=D(2024, 1, 1),
        durata_mesi=12,
    )
    lontano = f.contratto(
        fabbisogno=f.fabbisogno("Servizio lontano", referente_utente=altro),
        data_inizio=D(2026, 10, 1),
        durata_mesi=36,
    )
    f.voce(lontano)
    messaggi = promemoria.messaggi_scadenze(D(2026, 11, 9))
    assert [[u.username for u in msg.destinatari] for msg in messaggi] == [["ref"]]
    assert "5800000001" in messaggi[0].corpo and "Scaduti senza rinnovo" in messaggi[0].corpo
    assert messaggi[0].chiave == "2026-W46"
    out = StringIO()
    call_command("invia_promemoria", "--tipo", "scadenze", "--oggi", "2026-11-09", stdout=out)
    call_command("invia_promemoria", "--tipo", "scadenze", "--oggi", "2026-11-13", stdout=out)
    assert destinatari() == ["ref@esempio.test"]  # una sola volta nella settimana


def test_comando_con_notifiche_spente_fallisce(settings):
    from django.core.management.base import CommandError

    settings.NOTIFICHE_EMAIL_ATTIVE = False
    with pytest.raises(CommandError):
        call_command("invia_promemoria", "--oggi", "2026-11-09")


def test_registro_email_in_sola_lettura_nell_admin(admin_client, utenti):
    from django.contrib import admin

    notifiche.fatture_nuove(1)
    riga = m.InvioEmail.objects.first()
    ammin = admin.site._registry[m.InvioEmail]
    assert admin_client.get(reverse("admin:contratti_invioemail_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:contratti_invioemail_add")).status_code == 403
    assert (
        admin_client.get(reverse("admin:contratti_invioemail_delete", args=[riga.pk])).status_code
        == 403
    )
    assert not ammin.has_change_permission(None)


def test_senza_indirizzo_non_riceve_niente(utenti):
    assert notifiche.fatture_nuove(1) == 4
    assert "senzamail" not in {r.destinatario for r in m.InvioEmail.objects.all()}
