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
        var div = document.createElement("div");
        div.innerHTML = html.replace("Posizione </legend>", "Posizione " + (indice + 1) + "</legend>");
        var nuovo = div.firstElementChild;
        contenitore.appendChild(nuovo);
        totale.value = String(indice + 1);
        inizializza(nuovo);
        var primo = nuovo.querySelector("input:not([type=hidden]), select, textarea");
        if (primo) primo.focus();
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
  }

  document.addEventListener("DOMContentLoaded", function () {
    inizializza(document);
    conferme();
    notifiche();
    schede();
  });
  document.addEventListener("htmx:afterSwap", function (e) { inizializza(e.target); });
})();
