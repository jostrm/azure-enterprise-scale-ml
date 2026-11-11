// Search box and filter chips of the code templates library and the Azure resource library.
// Without JavaScript every card stays visible, so the pages still work.
(function () {
  "use strict";

  function setUp(library) {
    var search = library.querySelector(".esaf-library__search");
    var chips = Array.prototype.slice.call(library.querySelectorAll(".esaf-chip"));
    var cards = Array.prototype.slice.call(library.querySelectorAll(".esaf-card"));
    var count = library.querySelector("[data-count]");
    var empty = library.querySelector(".esaf-library__empty");
    var clear = library.querySelector("[data-clear]");

    function selected() {
      var groups = {};
      chips.forEach(function (chip) {
        if (chip.getAttribute("aria-pressed") === "true") {
          (groups[chip.dataset.filter] = groups[chip.dataset.filter] || []).push(chip.dataset.value);
        }
      });
      return groups;
    }

    // A card shows when it has one of the chosen values in every group that has a choice, and every search word.
    function apply() {
      var groups = selected();
      var words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      cards.forEach(function (card) {
        var matches = Object.keys(groups).every(function (group) {
          var values = (card.dataset[group] || "").split("|");
          return groups[group].some(function (value) { return values.indexOf(value) !== -1; });
        }) && words.every(function (word) { return card.dataset.text.indexOf(word) !== -1; });
        card.hidden = !matches;
        shown += matches ? 1 : 0;
      });
      count.textContent = shown;
      empty.hidden = shown !== 0;
      clear.hidden = !words.length && !Object.keys(groups).length;
    }

    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        chip.setAttribute("aria-pressed", chip.getAttribute("aria-pressed") === "true" ? "false" : "true");
        apply();
      });
    });
    search.addEventListener("input", apply);
    clear.addEventListener("click", function () {
      chips.forEach(function (chip) { chip.setAttribute("aria-pressed", "false"); });
      search.value = "";
      apply();
      search.focus();
    });

    // A link can open the library with filters already chosen: ?service=Fabric&tag=rag&q=voice
    var query = new URLSearchParams(window.location.search);
    chips.forEach(function (chip) {
      if (query.getAll(chip.dataset.filter).indexOf(chip.dataset.value) !== -1) {
        chip.setAttribute("aria-pressed", "true");
      }
    });
    search.value = query.get("q") || "";
    apply();
  }

  function start() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-library]"), function (library) {
      if (!library.dataset.ready) {
        library.dataset.ready = "true";
        setUp(library);
      }
    });
  }

  if (window.document$ && window.document$.subscribe) {
    window.document$.subscribe(start);  // Material for MkDocs: runs on every page it shows
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
