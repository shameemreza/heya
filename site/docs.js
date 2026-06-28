// Docs search. Loads the prebuilt index and filters pages as you type.
// No dependencies; if the fetch fails, the nav still works.
(function () {
  "use strict";
  var input = document.getElementById("docs-search");
  var results = document.getElementById("search-results");
  var nav = document.querySelector(".docs-nav");
  if (!input || !results) return;

  var index = [];
  fetch("search-index.json")
    .then(function (r) { return r.json(); })
    .then(function (data) { index = data; })
    .catch(function () {});

  function escapeHtml(s) {
    return s.split("&").join("&amp;")
            .split("<").join("&lt;")
            .split(">").join("&gt;")
            .split('"').join("&quot;")
            .split("'").join("&#39;");
  }

  function snippet(text, q) {
    var i = text.toLowerCase().indexOf(q);
    if (i === -1) return text.slice(0, 110);
    var start = Math.max(0, i - 40);
    return (start > 0 ? "... " : "") + text.slice(start, i + q.length + 70) + " ...";
  }

  function search(q) {
    q = q.trim().toLowerCase();
    if (!q) {
      results.hidden = true;
      results.innerHTML = "";
      if (nav) nav.hidden = false;
      return;
    }
    var hits = index.filter(function (p) {
      return (p.title + " " + p.text).toLowerCase().indexOf(q) !== -1;
    });
    if (nav) nav.hidden = true;
    if (!hits.length) {
      results.innerHTML = '<li class="no-hit">No matches.</li>';
    } else {
      results.innerHTML = hits.map(function (p) {
        return '<li><a href="' + escapeHtml(p.url) + '">' +
               '<span class="r-title">' + escapeHtml(p.title) + '</span>' +
               '<span class="r-snip">' + escapeHtml(snippet(p.text, q)) + '</span>' +
               '</a></li>';
      }).join("");
    }
    results.hidden = false;
  }

  input.addEventListener("input", function () { search(input.value); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { input.value = ""; search(""); input.blur(); }
  });
})();
