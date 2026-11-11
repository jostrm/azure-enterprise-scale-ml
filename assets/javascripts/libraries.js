// Search box and filter checkboxes of the code templates library and the Azure resource library.
// Without JavaScript every card stays visible, so the pages still work.
(function () {
  "use strict";

  function setUp(library) {
    var search = library.querySelector(".esaf-library__search");
    var boxes = Array.prototype.slice.call(library.querySelectorAll("input[type=checkbox][data-filter]"));
    var cards = Array.prototype.slice.call(library.querySelectorAll(".esaf-card"));
    var count = library.querySelector("[data-count]");
    var empty = library.querySelector(".esaf-library__empty");
    var clear = library.querySelector("[data-clear]");

    function selected() {
      var groups = {};
      boxes.forEach(function (box) {
        if (box.checked) {
          (groups[box.dataset.filter] = groups[box.dataset.filter] || []).push(box.dataset.value);
        }
      });
      return groups;
    }

    // A card shows when it has one of the checked values in every row that has a check, and every search word.
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

    boxes.forEach(function (box) { box.addEventListener("change", apply); });
    search.addEventListener("input", apply);
    clear.addEventListener("click", function () {
      boxes.forEach(function (box) { box.checked = false; });
      search.value = "";
      apply();
      search.focus();
    });

    // A link can open the library with filters already checked: ?service=Fabric&tag=rag&q=voice
    var query = new URLSearchParams(window.location.search);
    boxes.forEach(function (box) {
      box.checked = query.getAll(box.dataset.filter).indexOf(box.dataset.value) !== -1;
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
