// Earshot customer profile: the buyer drawn as a seal, with the pains people voiced radiating from it.
// Every string in `data` is untrusted (model / GitHub output): text goes in via textContent only.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var memory = new WeakMap(); // container -> { played: profile key, choices: { segment: action } }
  var uid = 0;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function svg(tag, attrs, text) {
    var n = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = String(text);
    return n;
  }
  function arr(x) { return Array.isArray(x) ? x : []; }
  function num(c) { var v = Number(c); return isFinite(v) ? Math.max(0, Math.min(1, v)) : 0; }
  // How firmly something is drawn: firm (solid), drawn (dashed), faint (dotted, low contrast).
  function firmness(c) { c = num(c); return c >= 0.75 ? "firm" : c >= 0.5 ? "drawn" : "faint"; }
  function conf(c) { return el("span", "eprof-conf", num(c).toFixed(2)); }
  function hash(s) {
    var h = 2166136261;
    s = String(s);
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0) / 4294967295;
  }
  function who(l) { return String(l.name || l.login || "Someone"); }

  // pain text -> { people: [lead], best: { lead, signal } }, people ordered by score.
  function voices(pains, leads) {
    var out = {};
    pains.forEach(function (p) { out[p] = { people: [], best: null }; });
    leads.slice().sort(function (a, b) { return (Number(b.score) || 0) - (Number(a.score) || 0); }).forEach(function (l) {
      var seen = {};
      arr(l.signals).forEach(function (s) {
        var v = out[s && s.pain];
        if (!v) return;
        if (!seen[s.pain]) { seen[s.pain] = 1; v.people.push(l); }
        if (!v.best || (Number(s.match) || 0) > (Number(v.best.signal.match) || 0)) v.best = { lead: l, signal: s };
      });
    });
    return out;
  }

  function section(cls, title, note) {
    var s = el("section", "eprof-sec " + cls);
    var h = el("header", "eprof-sec-head");
    h.appendChild(el("h3", "eprof-sec-title", title));
    if (note) h.appendChild(el("p", "eprof-sec-note", note));
    s.appendChild(h);
    return s;
  }

  // --- The seal -------------------------------------------------------------

  function ring(g, id, r, text, c, fs) {
    var circ = 2 * Math.PI * r;
    g.appendChild(svg("circle", { r: r, class: "eprof-ring eprof-" + firmness(c), pathLength: 1 }));
    var tr = r + 8;
    g.appendChild(svg("path", { id: id, d: "M0," + (-tr) + " a" + tr + "," + tr + " 0 1,1 0," + 2 * tr + " a" + tr + "," + tr + " 0 1,1 0," + (-2 * tr), fill: "none" }));
    var unit = (text || "Unknown").toUpperCase() + "  ·  ";
    var room = (2 * Math.PI * tr) / (fs * 0.72);
    var reps = Math.max(1, Math.floor(room / unit.length));
    var t = svg("text", { class: "eprof-ring-text eprof-" + firmness(c), "font-size": fs });
    var tp = svg("textPath", { href: "#" + id, textLength: (2 * Math.PI * tr - fs).toFixed(1), lengthAdjust: "spacing" }, new Array(reps + 1).join(unit));
    t.appendChild(tp);
    g.appendChild(t);
    return circ;
  }

  function seal(icp, pains, v, empty) {
    var id = "eprof-" + (++uid);
    var box = el("figure", "eprof-seal");
    var s = svg("svg", { viewBox: "-200 -200 400 400", role: "img", "aria-label": empty ? "An empty portrait waiting for a product" : "Portrait of the buyer: " + pains.length + " pains radiating from the product, each as long as the number of people who voiced it" });
    var g = svg("g", {});
    [60, 96, 132].forEach(function (r) { g.appendChild(svg("circle", { r: r, class: "eprof-guide" })); });
    if (empty) {
      ring(g, id + "-a", 170, "Who buys it", 0.2, 11);
      ring(g, id + "-b", 146, "Where they work", 0.2, 10);
      for (var k = 0; k < 5; k++) {
        var a = (-90 + k * 72) * Math.PI / 180;
        g.appendChild(svg("line", { x1: (44 * Math.cos(a)).toFixed(1), y1: (44 * Math.sin(a)).toFixed(1), x2: (110 * Math.cos(a)).toFixed(1), y2: (110 * Math.sin(a)).toFixed(1), class: "eprof-strand eprof-faint" }));
      }
      g.appendChild(svg("circle", { r: 36, class: "eprof-core eprof-faint" }));
      g.appendChild(svg("text", { class: "eprof-core-text", y: 5 }, "?"));
      s.appendChild(g);
      box.appendChild(s);
      return box;
    }
    var personas = icp.personas || {}, industries = icp.industries || {};
    ring(g, id + "-a", 170, arr(personas.values).join("  ·  "), personas.confidence, 11);
    ring(g, id + "-b", 146, arr(industries.values).join("  ·  "), industries.confidence, 10);

    var max = 1;
    pains.forEach(function (p) { max = Math.max(max, v[p].people.length); });
    var n = Math.max(1, pains.length);
    pains.forEach(function (p, i) {
      var people = v[p].people;
      var h = hash(p);
      var ang = (-90 + i * 360 / n + (h - 0.5) * 14) * Math.PI / 180;
      var r0 = 40, r1 = people.length ? 70 + 62 * people.length / max : 58;
      var bend = (h > 0.5 ? 1 : -1) * (0.16 + h * 0.18);
      var x0 = r0 * Math.cos(ang), y0 = r0 * Math.sin(ang);
      var x1 = r1 * Math.cos(ang), y1 = r1 * Math.sin(ang);
      var rm = (r0 + r1) / 2, cx = rm * Math.cos(ang + bend), cy = rm * Math.sin(ang + bend);
      var w = people.length ? Math.min(7, 1.25 + people.length * 1.1) : 1;
      var path = svg("path", { d: "M" + x0.toFixed(1) + "," + y0.toFixed(1) + " Q" + cx.toFixed(1) + "," + cy.toFixed(1) + " " + x1.toFixed(1) + "," + y1.toFixed(1), class: "eprof-strand" + (people.length ? "" : " eprof-faint"), "stroke-width": w, pathLength: 1, style: "--i:" + i });
      g.appendChild(path);
      people.forEach(function (l, k) {
        var t = (k + 1) / (people.length + 1) * 0.85 + 0.15;
        var px = (1 - t) * (1 - t) * x0 + 2 * (1 - t) * t * cx + t * t * x1;
        var py = (1 - t) * (1 - t) * y0 + 2 * (1 - t) * t * cy + t * t * y1;
        var dot = svg("circle", { cx: px.toFixed(1), cy: py.toFixed(1), r: 3.2, class: "eprof-dot", style: "--i:" + i });
        dot.appendChild(svg("title", {}, who(l)));
        g.appendChild(dot);
      });
      var lx = (r1 + 12) * Math.cos(ang), ly = (r1 + 12) * Math.sin(ang);
      g.appendChild(svg("text", { x: lx.toFixed(1), y: (ly + 4).toFixed(1), class: "eprof-strand-num", style: "--i:" + i }, String(i + 1)));
    });
    g.appendChild(svg("circle", { r: 34, class: "eprof-core" }));
    var name = String(icp.product || "Product");
    g.appendChild(svg("text", { class: "eprof-core-text", y: 5, "font-size": name.length > 10 ? 12 : 16 }, name.length > 16 ? name.slice(0, 15) + "…" : name));
    s.appendChild(g);
    box.appendChild(s);
    return box;
  }

  // --- Portrait head --------------------------------------------------------

  function fragment(scored, fallback) {
    scored = scored || {};
    var f = el("span", "eprof-frag-wrap");
    f.appendChild(el("span", "eprof-frag eprof-" + firmness(scored.confidence), arr(scored.values)[0] || fallback));
    f.appendChild(conf(scored.confidence));
    return f;
  }

  function facet(label, scored) {
    scored = scored || {};
    var d = el("div", "eprof-facet");
    var h = el("p", "eprof-facet-label", label + " ");
    h.appendChild(conf(scored.confidence));
    d.appendChild(h);
    var ul = el("ul", "eprof-facet-values eprof-" + firmness(scored.confidence));
    arr(scored.values).forEach(function (x) { ul.appendChild(el("li", null, x)); });
    d.appendChild(ul);
    return d;
  }

  function portrait(icp, pains, v) {
    var wrap = el("div", "eprof-portrait");
    var text = el("div", "eprof-portrait-text");
    text.appendChild(el("p", "eprof-eyebrow", "Who buys " + (icp.product || "your product")));
    var h = el("h2", "eprof-headline");
    h.appendChild(fragment(icp.personas, "A buyer"));
    h.appendChild(document.createTextNode(", at "));
    h.appendChild(fragment(icp.company_size, "a company"));
    h.appendChild(document.createTextNode(" in "));
    h.appendChild(fragment(icp.industries, "an industry"));
    h.appendChild(document.createTextNode("."));
    text.appendChild(h);
    var voiced = {};
    pains.forEach(function (p) { v[p].people.forEach(function (l) { voiced[l.login] = 1; }); });
    var count = Object.keys(voiced).length;
    text.appendChild(el("p", "eprof-lede", count
      ? "Drawn from " + count + " " + (count === 1 ? "person" : "people") + " who described these problems in public. Solid lines are what the description states plainly; dashed and dotted lines are inference."
      : "No one has been heard yet. Solid lines are what the description states plainly; dashed and dotted lines are inference."));
    var facets = el("div", "eprof-facets");
    facets.appendChild(facet("Buyers", icp.personas));
    facets.appendChild(facet("Company size", icp.company_size));
    facets.appendChild(facet("Industries", icp.industries));
    text.appendChild(facets);
    if (icp.tracker_fit !== false && icp.tracker_fit_reason) text.appendChild(el("p", "eprof-why", icp.tracker_fit_reason));
    wrap.appendChild(text);
    wrap.appendChild(seal(icp, pains, v, false));
    return wrap;
  }

  // --- Pains as strands -----------------------------------------------------

  function strandRow(p, i, info) {
    var people = info.people;
    var row = el("li", "eprof-pain" + (people.length ? "" : " is-quiet"));
    var head = el("div", "eprof-pain-head");
    head.appendChild(el("span", "eprof-pain-num", String(i + 1)));
    head.appendChild(el("p", "eprof-pain-text", p));
    head.appendChild(el("span", "eprof-pain-count", people.length ? people.length + (people.length === 1 ? " person" : " people") : "No one yet"));
    row.appendChild(head);

    var h = hash(p), a = 6 + h * 12, b = 5 + (1 - h) * 12;
    var line = svg("svg", { class: "eprof-pain-line", viewBox: "0 0 1000 48", preserveAspectRatio: "none", "aria-hidden": "true" });
    line.appendChild(svg("path", {
      d: "M0,24 C166," + (24 - a).toFixed(1) + " 333," + (24 + a).toFixed(1) + " 500,24 S833," + (24 + b).toFixed(1) + " 1000,24",
      class: "eprof-strand" + (people.length ? "" : " eprof-faint"), "stroke-width": people.length ? Math.min(9, 1 + people.length * 1.5) : 1,
      pathLength: 1, style: "--i:" + i,
    }));
    row.appendChild(line);

    if (people.length) {
      var names = el("ul", "eprof-names");
      people.forEach(function (l) {
        var li = el("li", "eprof-name", who(l));
        if (l.company) li.appendChild(el("span", "eprof-name-co", l.company));
        names.appendChild(li);
      });
      row.appendChild(names);
    }
    if (info.best && info.best.signal.title) {
      var q = el("figure", "eprof-quote");
      q.appendChild(el("blockquote", null, "“" + info.best.signal.title + "”"));
      var cap = el("figcaption", null, who(info.best.lead));
      if (info.best.signal.repo) cap.appendChild(el("span", "eprof-mono", " in " + info.best.signal.repo));
      cap.appendChild(el("span", "eprof-mono", " · match " + num(info.best.signal.match).toFixed(2)));
      q.appendChild(cap);
      row.appendChild(q);
    }
    return row;
  }

  // --- The rest -------------------------------------------------------------

  function triggers(t) {
    t = t || {};
    var s = section("eprof-triggers", "When they start looking", null);
    s.querySelector(".eprof-sec-head").appendChild(conf(t.confidence));
    var ol = el("ol", "eprof-moments eprof-" + firmness(t.confidence));
    arr(t.values).forEach(function (x) { ol.appendChild(el("li", "eprof-moment", x)); });
    s.appendChild(ol);
    return s;
  }

  var LISTEN = "M6 1.5a4.5 4.5 0 1 1 0 9a4.5 4.5 0 1 1 0-9M6 4a2 2 0 1 1 0 4a2 2 0 1 1 0-4";
  function competitors(list) {
    var s = section("eprof-comp", "Who else they look at", "Where a public tracker exists, Earshot reads it for people already asking for help.");
    var groups = {}, order = ["direct", "indirect", "alternative"];
    list.forEach(function (c) {
      var k = String(c.category || "other").toLowerCase();
      if (!groups[k]) { groups[k] = []; if (order.indexOf(k) < 0) order.push(k); }
      groups[k].push(c);
    });
    var grid = el("div", "eprof-comp-grid");
    order.forEach(function (k) {
      if (!groups[k]) return;
      var col = el("div", "eprof-comp-col");
      col.appendChild(el("p", "eprof-comp-cat", k));
      groups[k].forEach(function (c) {
        var item = el("div", "eprof-comp-item");
        item.appendChild(el("p", "eprof-comp-name", c.name));
        if (c.positioning) item.appendChild(el("p", "eprof-comp-pos", c.positioning));
        if (c.github_repo) {
          var m = el("p", "eprof-comp-read");
          var ic = svg("svg", { viewBox: "0 0 12 12", class: "eprof-listen", "aria-hidden": "true" });
          ic.appendChild(svg("path", { d: LISTEN }));
          m.appendChild(ic);
          m.appendChild(el("span", null, "Reading "));
          m.appendChild(el("span", "eprof-mono", c.github_repo));
          item.appendChild(m);
        }
        col.appendChild(item);
      });
      grid.appendChild(col);
    });
    s.appendChild(grid);
    return s;
  }

  function avoids(list) {
    var s = section("eprof-avoid", "What Earshot steers clear of", "Anyone who matches these is dropped before a message is written.");
    var ul = el("ul", "eprof-struck");
    list.forEach(function (x) { ul.appendChild(el("li", null, x)); });
    s.appendChild(ul);
    return s;
  }

  function expansionCard(e, state, container) {
    var seg = String(e.segment || "");
    var choice = state.choices[seg];
    var card = el("li", "eprof-exp" + (choice ? " is-" + choice : ""));
    card.appendChild(el("p", "eprof-exp-seg", seg));
    card.appendChild(el("p", "eprof-exp-why", e.reasoning));
    var foot = el("div", "eprof-exp-foot");
    if (choice) {
      foot.appendChild(el("p", "eprof-exp-made", choice === "accept" ? "Accepted. Earshot will search this segment next." : "Dismissed. Earshot will leave it alone."));
    } else {
      [["accept", "Accept"], ["dismiss", "Dismiss"]].forEach(function (pair) {
        var b = el("button", "eprof-btn eprof-btn-" + pair[0], pair[1]);
        b.type = "button";
        b.setAttribute("aria-label", pair[1] + " " + seg);
        b.addEventListener("click", function () {
          state.choices[seg] = pair[0];
          container.dispatchEvent(new CustomEvent("earshot:expansion", { bubbles: true, detail: { segment: seg, action: pair[0] } }));
          var next = expansionCard(e, state, container);
          card.replaceWith(next);
          var made = next.querySelector(".eprof-exp-made");
          if (made) { made.tabIndex = -1; made.focus(); }
        });
        foot.appendChild(b);
      });
    }
    card.appendChild(foot);
    return card;
  }

  function expansion(list, state, container) {
    var s = section("eprof-expansion", "Where it could reach next", "Suggestions. Nothing changes until you rule on them.");
    var ul = el("ul", "eprof-exp-list");
    list.forEach(function (e) { ul.appendChild(expansionCard(e, state, container)); });
    s.appendChild(ul);
    return s;
  }

  function declined(icp) {
    var d = el("section", "eprof-declined");
    d.setAttribute("role", "status");
    d.appendChild(el("p", "eprof-eyebrow", "Declined"));
    d.appendChild(el("h2", "eprof-declined-title", "Earshot will not hunt for these buyers."));
    d.appendChild(el("p", "eprof-declined-why", icp.tracker_fit_reason || "Its buyers do not describe this problem in public trackers."));
    d.appendChild(el("p", "eprof-declined-note", "No messages will be drafted. Saying no to a bad job is part of the work."));
    return d;
  }

  function empty() {
    var root = el("div", "eprof eprof-empty");
    var wrap = el("div", "eprof-portrait");
    var text = el("div", "eprof-portrait-text");
    text.appendChild(el("p", "eprof-eyebrow", "Customer profile"));
    text.appendChild(el("h2", "eprof-headline", "Describe your product and Earshot will draw who buys it."));
    text.appendChild(el("p", "eprof-lede", "From a paragraph about what you sell, it infers the buyer, the five pains they would write about, the moments they start looking and the tools they compare. Then it listens in public trackers, and each pain grows a strand for every real person heard saying it."));
    wrap.appendChild(text);
    wrap.appendChild(seal(null, [], {}, true));
    root.appendChild(wrap);
    return root;
  }

  function render(container, data) {
    if (!container) return;
    data = data || {};
    var state = memory.get(container);
    if (!state) { state = { played: null, choices: {} }; memory.set(container, state); }
    var icp = data.icp;
    if (!icp) { container.replaceChildren(empty()); return; }

    var leads = arr(data.leads);
    var pains = arr(icp.pains).map(String);
    var v = voices(pains, leads);
    var key = String(icp.product) + "|" + pains.join("|");
    var root = el("div", "eprof");
    if (state.played !== key) { state.played = key; root.classList.add("is-assembling"); }
    if (icp.tracker_fit === false) { root.classList.add("is-declined"); root.appendChild(declined(icp)); }

    root.appendChild(portrait(icp, pains, v));

    var ps = section("eprof-pains", "What they say, in their own words", "Each strand is a pain Earshot searched for. Its weight is the number of people who said it.");
    var ul = el("ol", "eprof-pain-list");
    pains.forEach(function (p, i) { ul.appendChild(strandRow(p, i, v[p])); });
    ps.appendChild(ul);
    root.appendChild(ps);

    var grid = el("div", "eprof-pair");
    grid.appendChild(triggers(icp.triggers));
    grid.appendChild(avoids(arr(icp.negative_signals)));
    root.appendChild(grid);
    if (arr(icp.competitors).length) root.appendChild(competitors(arr(icp.competitors)));
    if (arr(icp.expansion).length) root.appendChild(expansion(arr(icp.expansion), state, container));
    container.replaceChildren(root);
  }

  window.EarshotProfile = { render: render };
})();
