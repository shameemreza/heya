// Heya landing page. Vanilla JS, no dependencies.
// Everything degrades: with JS off or reduced motion on, the page shows its
// full static content. JS only adds the terminal reveal, the copy button, and
// the example tabs.
(function () {
  "use strict";

  // Copy button on the install command.
  document.querySelectorAll(".install").forEach(function (box) {
    var btn = box.querySelector(".copy-btn");
    if (!btn || !navigator.clipboard) return;
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(box.getAttribute("data-copy") || "").then(function () {
        btn.textContent = "Copied";
        btn.classList.add("copied");
        setTimeout(function () {
          btn.textContent = "Copy";
          btn.classList.remove("copied");
        }, 1600);
      });
    });
  });

  // Example tabs. The panels all start visible in the HTML, so with JS off the
  // three examples stack and stay readable. On load, hide all but the first.
  document.querySelectorAll(".panel").forEach(function (p, idx) {
    if (idx !== 0) {
      p.classList.add("is-hidden");
      p.hidden = true;
    }
  });

  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) {
        t.classList.remove("is-active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("is-active");
      tab.setAttribute("aria-selected", "true");
      document.querySelectorAll(".panel").forEach(function (p) {
        p.classList.add("is-hidden");
        p.hidden = true;
      });
      var panel = document.getElementById(tab.getAttribute("aria-controls"));
      if (panel) {
        panel.classList.remove("is-hidden");
        panel.hidden = false;
      }
    });
  });

  // Hero terminal reveal: stream the lines in, leave a blinking cursor at rest.
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var pre = document.querySelector("#hero-term .term-body");
  if (!pre || reduce) return;

  var lines = splitTopLevelLines(pre.innerHTML);
  var cursor = '<span class="term-cursor"></span>';
  var acc = "";
  var i = 0;
  pre.innerHTML = "";

  (function step() {
    if (i >= lines.length) {
      pre.innerHTML = acc + cursor;
      return;
    }
    acc += (i > 0 ? "\n" : "") + lines[i];
    pre.innerHTML = acc + cursor;
    i += 1;
    var delay = i === 1 ? 240 : 150 + Math.random() * 180;
    setTimeout(step, delay);
  })();

  // Split an HTML string on newlines that sit outside any <span>, so a
  // multi-line span (the banner art) stays as a single chunk.
  function splitTopLevelLines(s) {
    var out = [];
    var depth = 0;
    var cur = "";
    for (var k = 0; k < s.length; k += 1) {
      if (s.substr(k, 5) === "<span") depth += 1;
      else if (s.substr(k, 7) === "</span>") depth = Math.max(0, depth - 1);
      if (s[k] === "\n" && depth === 0) {
        out.push(cur);
        cur = "";
      } else {
        cur += s[k];
      }
    }
    out.push(cur);
    return out;
  }
})();
