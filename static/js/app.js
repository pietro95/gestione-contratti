/* Registro contratti IT/TLC — comportamenti dell'interfaccia. Nessuna dipendenza esterna:
 * Bootstrap, htmx, Tom Select e flatpickr sono serviti da static/vendor. Senza JavaScript le
 * pagine restano utilizzabili (le date si scrivono gg/mm/aaaa, le tendine sono normali). */
(function () {
  "use strict";

  // Tendine lunghe (fornitori, fabbisogni, conti): ricerca mentre si scrive.
  var SOGLIA_RICERCA = 12;
  function tendine(radice) {
    if (typeof TomSelect === "undefined") return;
    radice.querySelectorAll("select:not([multiple]):not(.no-cerca)").forEach(function (el) {
      if (el.tomselect || (el.options.length < SOGLIA_RICERCA && !el.classList.contains("js-cerca"))) return;
      // La select originale resta nell'albero di accessibilità: le serve un nome proprio.
      var etichetta = el.id && document.querySelector('label[for="' + el.id + '"]');
      if (etichetta && !el.getAttribute("aria-label")) el.setAttribute("aria-label", etichetta.textContent.replace("*", "").trim());
      new TomSelect(el, {
        allowEmptyOption: true,
        maxOptions: 500,
        placeholder: "Scrivi per cercare…",
        // Tom Select aggiorna la select originale e ne emette "change": i filtri htmx funzionano.
        render: { no_results: function () { return '<div class="no-results">Nessun risultato</div>'; } },
      });
    });
  }

  // Filtro «Cluster»: più cluster insieme. «I miei cluster» e «Tutti i cluster» escludono il
  // resto; scegliendo un cluster si tolgono. Senza JavaScript resta una select multipla.
  var SPECIALI = ["miei", "tutti"];
  function cluster(radice) {
    if (typeof TomSelect === "undefined") return;
    radice.querySelectorAll("select.js-cluster[multiple]").forEach(function (el) {
      if (el.tomselect) return;
      var etichetta = el.id && document.querySelector('label[for="' + el.id + '"]');
      if (etichetta && !el.getAttribute("aria-label")) el.setAttribute("aria-label", etichetta.textContent.trim());
      var ts = new TomSelect(el, {
        plugins: { remove_button: { title: "Togli" } },
        placeholder: "Tutti i cluster",
        hidePlaceholder: true,
        onItemAdd: function (valore) {
          var altri = ts.items.filter(function (v) { return v !== valore; });
          var via = SPECIALI.indexOf(valore) >= 0 ? altri
            : altri.filter(function (v) { return SPECIALI.indexOf(v) >= 0; });
          via.forEach(function (v) { ts.removeItem(v, true); });
          // Chiusa e senza fuoco: il controllo non cambia altezza al clic successivo (su
          // «Aggiorna» il pulsante si spostava tra pressione e rilascio e il clic andava perso).
          ts.close();
          ts.blur();
        },
      });
    });
  }

  // Date: calendario italiano, valore gg/mm/aaaa (il server accetta anche aaaa-mm-gg).
  function date(radice) {
    if (typeof flatpickr === "undefined") return;
    radice.querySelectorAll("input.js-data").forEach(function (el) {
      if (el._flatpickr) return;
      flatpickr(el, { locale: "it", dateFormat: "d/m/Y", allowInput: true, disableMobile: true });
    });
  }

  // Righe cliccabili: tutta la riga apre il dettaglio (il link resta per tastiera e lettori).
  function righe(radice) {
    radice.querySelectorAll("tr[data-href]").forEach(function (tr) {
      if (tr._link) return;
      tr._link = true;
      tr.classList.add("riga-link");
      tr.addEventListener("click", function (e) {
        if (e.target.closest("a, button, input, select, label, form")) return;
        window.location = tr.dataset.href;
      });
    });
  }

  // Conferma in una finestra modale per i form con data-conferma="testo".
  function conferme() {
    var modale = document.getElementById("modale-conferma");
    if (!modale || typeof bootstrap === "undefined") return;
    var istanza = bootstrap.Modal.getOrCreateInstance(modale);
    var inAttesa = null;
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form.dataset.conferma || form._confermato) return;
      e.preventDefault();
      inAttesa = form;
      modale.querySelector(".modal-body").textContent = form.dataset.conferma;
      var bottone = modale.querySelector("[data-conferma-ok]");
      bottone.textContent = form.dataset.confermaEtichetta || "Conferma";
      bottone.className = "btn " + (form.dataset.confermaStile || "btn-primary");
      istanza.show();
    });
    modale.querySelector("[data-conferma-ok]").addEventListener("click", function () {
      if (!inAttesa) return;
      inAttesa._confermato = true;
      istanza.hide();
      inAttesa.requestSubmit ? inAttesa.requestSubmit() : inAttesa.submit();
    });
  }

  // Notifiche: le conferme spariscono da sole, gli errori restano finché non si chiudono.
  function notifiche() {
    if (typeof bootstrap === "undefined") return;
    document.querySelectorAll(".toast").forEach(function (t) {
      bootstrap.Toast.getOrCreateInstance(t, { autohide: t.dataset.autohide !== "false", delay: 6000 }).show();
    });
  }

  // Schede: la scheda aperta si ricorda nell'indirizzo (#voci, #storico, …).
  function schede() {
    if (typeof bootstrap === "undefined") return;
    var hash = window.location.hash;
    if (hash) {
      var bottone = document.querySelector('[data-bs-toggle="tab"][data-bs-target="' + hash + '"]');
      if (bottone) bootstrap.Tab.getOrCreateInstance(bottone).show();
    }
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(function (b) {
      b.addEventListener("shown.bs.tab", function () {
        history.replaceState(null, "", b.dataset.bsTarget);
      });
    });
  }

  // Tabelle larghe con scorrimento orizzontale: raggiungibili da tastiera (WCAG 2.1.1).
  function scorrimenti(radice) {
    radice.querySelectorAll(".table-responsive").forEach(function (el) {
      if (el.scrollWidth > el.clientWidth + 1 && !el.hasAttribute("tabindex")) {
        el.setAttribute("tabindex", "0");
        el.setAttribute("role", "region");
        el.setAttribute("aria-label", "Tabella con scorrimento orizzontale");
      }
    });
  }

  // «Copia»: il valore negli appunti (scheda SAP). data-copia-testo = testo da copiare,
  // data-copia = id dell'elemento (textarea o testo) da copiare. Senza API degli appunti
  // (pagina non HTTPS) si usa la selezione con execCommand.
  function copia(testo) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(testo);
    return new Promise(function (ok, ko) {
      var area = document.createElement("textarea");
      area.value = testo;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var riuscito = false;
      try { riuscito = document.execCommand("copy"); } catch (e) { riuscito = false; }
      document.body.removeChild(area);
      riuscito ? ok() : ko();
    });
  }
  function copie(radice) {
    radice.querySelectorAll("[data-copia], [data-copia-testo]").forEach(function (b) {
      if (b._copia) return;
      b._copia = true;
      b.addEventListener("click", function () {
        var testo = b.dataset.copiaTesto;
        if (testo === undefined) {
          var origine = document.getElementById(b.dataset.copia);
          testo = origine ? (origine.value !== undefined ? origine.value : origine.textContent) : "";
        }
        var prima = b.innerHTML;
        copia(testo).then(function () {
          b.innerHTML = '<i class="bi bi-check-lg" aria-hidden="true"></i> Copiato';
          b.classList.add("copiato");
        }, function () {
          b.innerHTML = "Copia non riuscita: seleziona il testo";
        });
        setTimeout(function () { b.innerHTML = prima; b.classList.remove("copiato"); }, 1800);
      });
    });
  }

  // Formset: «Aggiungi …» clona il modello <template id="<prefisso>-vuota"> nel contenitore
  // <prefisso>-forms e aggiorna TOTAL_FORMS. Senza JavaScript resta la riga vuota in fondo.
  // Il modello può essere una riga di tabella (<tr>): si interpreta dentro un <template>.
  // Gli elementi con data-numero-riga mostrano il numero d'ordine della riga.
  // «Rimuovi» (data-rimuovi-form) toglie una riga non ancora salvata: la svuota e la nasconde,
  // così gli indici restano contigui e Django la ignora come riga vuota.
  function formset(radice) {
    radice.querySelectorAll("[data-aggiungi-form]").forEach(function (b) {
      if (b._formset) return;
      b._formset = true;
      b.addEventListener("click", function () {
        var prefisso = b.dataset.aggiungiForm;
        var totale = document.getElementById("id_" + prefisso + "-TOTAL_FORMS");
        var modello = document.getElementById(prefisso + "-vuota");
        var contenitore = document.getElementById(prefisso + "-forms");
        if (!totale || !modello || !contenitore) return;
        var indice = parseInt(totale.value, 10);
        var html = modello.innerHTML.replace(/__prefix__/g, String(indice));
        var tmp = document.createElement("template");
        tmp.innerHTML = html.replace("Posizione </legend>", "Posizione " + (indice + 1) + "</legend>");
        var nuovo = tmp.content.firstElementChild;
        nuovo.querySelectorAll("[data-numero-riga]").forEach(function (el) {
          el.textContent = String(indice + 1);
        });
        contenitore.appendChild(nuovo);
        totale.value = String(indice + 1);
        inizializza(nuovo);
        var primo = nuovo.querySelector("input:not([type=hidden]), select, textarea");
        if (primo) primo.focus();
      });
    });
    radice.querySelectorAll("[data-rimuovi-form]").forEach(function (b) {
      if (b._rimuovi) return;
      b._rimuovi = true;
      b.addEventListener("click", function () {
        var riga = b.closest("[data-riga-form]");
        if (!riga) return;
        riga.querySelectorAll("input, select, textarea").forEach(function (campo) {
          if (campo.type === "hidden" || campo.type === "checkbox") return;
          if (campo._flatpickr) campo._flatpickr.clear();
          campo.value = "";
          campo.classList.remove("is-invalid");
        });
        riga.querySelectorAll(".invalid-feedback").forEach(function (e) { e.remove(); });
        riga.hidden = true;
        var successiva = document.querySelector("[data-aggiungi-form]");
        if (successiva) successiva.focus();
      });
    });
  }

  // Selezione multipla (fatture): la casella data-seleziona-tutte="nome" spunta o toglie
  // tutte le caselle con quel nome; il contatore data-selezionate="nome" mostra quante sono.
  function selezioni(radice) {
    radice.querySelectorAll("[data-seleziona-tutte]").forEach(function (tutte) {
      if (tutte._selezione) return;
      tutte._selezione = true;
      var nome = tutte.dataset.selezionaTutte;
      var caselle = function () { return document.querySelectorAll('input[type=checkbox][name="' + nome + '"]'); };
      var aggiorna = function () {
        var n = Array.prototype.filter.call(caselle(), function (c) { return c.checked; }).length;
        document.querySelectorAll('[data-selezionate="' + nome + '"]').forEach(function (el) {
          el.textContent = n === 1 ? "1 selezionata" : n + " selezionate";
        });
        tutte.checked = n > 0 && n === caselle().length;
        tutte.indeterminate = n > 0 && n < caselle().length;
      };
      tutte.addEventListener("change", function () {
        caselle().forEach(function (c) { c.checked = tutte.checked; });
        aggiorna();
      });
      caselle().forEach(function (c) { c.addEventListener("change", aggiorna); });
      aggiorna();
    });
  }

  // Richiesta di RDA: scegliendo il richiedente si propone il gruppo acquisti della sua unità
  // (data-gruppi-acquisti: richiedente → gruppo; data-gruppo-target: id della tendina).
  function gruppiDalRichiedente(radice) {
    radice.querySelectorAll("select[data-gruppi-acquisti]").forEach(function (el) {
      if (el._gruppi) return;
      el._gruppi = true;
      var coppie = JSON.parse(el.dataset.gruppiAcquisti);
      el.addEventListener("change", function () {
        var gruppo = coppie[el.value];
        var bersaglio = document.getElementById(el.dataset.gruppoTarget);
        if (!gruppo || !bersaglio) return;
        if (bersaglio.tomselect) bersaglio.tomselect.setValue(String(gruppo));
        else bersaglio.value = String(gruppo);
      });
    });
  }

  // Campi SAP con limite di lunghezza (data-contatore="40"): caratteri usati sotto il campo.
  function contatori(radice) {
    radice.querySelectorAll("input[data-contatore]").forEach(function (el) {
      if (el._contatore) return;
      el._contatore = true;
      var limite = parseInt(el.dataset.contatore, 10);
      el.setAttribute("maxlength", String(limite));
      var nota = document.createElement("div");
      nota.className = "form-text contatore";
      nota.id = (el.id || el.name) + "-contatore";
      el.setAttribute("aria-describedby", ((el.getAttribute("aria-describedby") || "") + " " + nota.id).trim());
      el.insertAdjacentElement("afterend", nota);
      var aggiorna = function () {
        var n = el.value.length;
        nota.textContent = n + "/" + limite + " caratteri (limite SAP)";
        nota.classList.toggle("text-danger", n > limite);
      };
      el.addEventListener("input", aggiorna);
      aggiorna();
    });
  }

  // Fattura → contratto: la tendina della voce mostra solo le voci del contratto scelto
  // (data-voci: contratto → [[id, nome], …]; data-voci-target: id della tendina della voce).
  function vociDelContratto(radice) {
    radice.querySelectorAll("select[data-voci]").forEach(function (el) {
      if (el._voci) return;
      el._voci = true;
      var voci = JSON.parse(el.dataset.voci);
      el.addEventListener("change", function () {
        var bersaglio = document.getElementById(el.dataset.vociTarget);
        if (!bersaglio) return;
        var righe = voci[el.value] || [];
        if (bersaglio.tomselect) {
          var ts = bersaglio.tomselect;
          ts.clear(true);
          ts.clearOptions();
          righe.forEach(function (r) { ts.addOption({ value: String(r[0]), text: r[1] }); });
          ts.refreshOptions(false);
          return;
        }
        bersaglio.innerHTML = "";
        bersaglio.add(new Option("---------", ""));
        righe.forEach(function (r) { bersaglio.add(new Option(r[1], String(r[0]))); });
      });
    });
  }

  function inizializza(radice) {
    tendine(radice);
    cluster(radice);
    date(radice);
    righe(radice);
    scorrimenti(radice);
    copie(radice);
    formset(radice);
    selezioni(radice);
    gruppiDalRichiedente(radice);
    contatori(radice);
    vociDelContratto(radice);
  }

  document.addEventListener("DOMContentLoaded", function () {
    inizializza(document);
    conferme();
    notifiche();
    schede();
  });
  document.addEventListener("htmx:afterSwap", function (e) { inizializza(e.target); });
})();
