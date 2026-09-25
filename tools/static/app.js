// Client-side filtering only. The site is static; nothing is fetched at runtime.
(function () {
  "use strict";

  function rowsOf(selector) {
    var rows = [];
    document.querySelectorAll(selector + " tbody tr").forEach(function (row) {
      rows.push(row);
    });
    return rows;
  }

  document.querySelectorAll("[data-filter-target]").forEach(function (input) {
    var rows = rowsOf(input.getAttribute("data-filter-target"));
    input.addEventListener("input", function () {
      var needle = input.value.trim().toLowerCase();
      rows.forEach(function (row) {
        var haystack = (row.getAttribute("data-search") || row.textContent).toLowerCase();
        row.hidden = needle.length > 0 && haystack.indexOf(needle) === -1;
      });
      document.querySelectorAll(".status-group").forEach(function (group) {
        var visible = group.querySelectorAll("tbody tr:not([hidden])").length;
        group.hidden = visible === 0 && needle.length > 0;
      });
    });
  });

  var LEVELS = { all: 0, warning: 1, error: 2 };
  var RANK = { information: 0, warning: 1, error: 2, fatal: 2 };

  document.querySelectorAll("[data-severity-target]").forEach(function (select) {
    var rows = rowsOf(select.getAttribute("data-severity-target"));
    select.addEventListener("change", function () {
      var minimum = LEVELS[select.value] || 0;
      rows.forEach(function (row) {
        var severity = row.getAttribute("data-severity") || "information";
        row.hidden = (RANK[severity] || 0) < minimum;
      });
    });
  });
})();
