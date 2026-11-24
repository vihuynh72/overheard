// Earshot Floor: the seven-agent line drawn as an engineer's track schematic, then the trust ladder,
// the inbox, the lessons and the proving ground. Every string in `data` is untrusted: textContent only.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var LEVELS = ["shadow", "supervised", "autopilot"]; // mirrors app/trust.py
  var LAYERS = [
    { key: "enforced", title: "Enforced in code", note: "The system cannot do the wrong thing." },
    { key: "checked", title: "Checked every run", note: "The system proves its work before it moves on." },
    { key: "advised", title: "Advised", note: "Rules it has been told." },
  ];

  // Drawing geometry in SVG user units; factory.css owns type and colour.
  var W = 1400;
  var TRACK = 158;        // y of the main line
  var POLICY_X = 56;      // terminus where the human's policy enters
  var FIRST = 214;        // first station
  var STEP = 158;         // station spacing
  var GATE_ROOM = 170;    // extra length of the Reviewer to Sender run, where the checkpoints stand
  var LOOP_TOP = 44;      // apex of the return loop
  var SIDING_Y = 300;     // the exceptions siding runs along here
  var H = 336;

  var lastShown = new WeakMap(); // container -> ts of the newest handoff already drawn

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
  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }
  function pct(v) { var n = num(v); return Math.round(n <= 1 ? n * 100 : n); } // accepts 0.42 or 42
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function clock(ts) {
    var d = new Date(ts);
    if (isNaN(d)) return "";
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0") + ":" + String(d.getSeconds()).padStart(2, "0");
  }
  // SVG text does not wrap: greedy word wrap, last line ellipsised.
  function wrap(text, max, lines) {
    var words = String(text || "").split(/\s+/).filter(Boolean);
    var out = [], cur = "";
    for (var i = 0; i < words.length; i++) {
      var w = words[i].length > max ? words[i].slice(0, max - 1) + "…" : words[i];
      if (!cur) cur = w;
      else if ((cur + " " + w).length <= max) cur += " " + w;
      else { out.push(cur); cur = w; if (out.length === lines) break; }
    }
    if (cur && out.length < lines) out.push(cur);
    else if (out.length === lines && i < words.length) out[lines - 1] = out[lines - 1].replace(/.?$/, "…");
    return out;
  }

  /* 1. The line */

  function stationX(i, n) {
    var x = FIRST + i * STEP;
    return i === n - 1 && n > 1 ? x + GATE_ROOM : x; // Sender sits past the checkpoints
  }

  function drawLine(container, data) {
    var agents = data.agents || [];
    var handoffs = data.handoffs || [];
    var trust = data.trust || {};
    var gates = trust.gates || [];
    var inbox = data.inbox || [];
    var lessons = data.lessons || [];
    var n = agents.length;
    var pos = {};
    agents.forEach(function (a, i) { pos[a.key] = { x: stationX(i, n), i: i }; });
    var reviewerI = Math.max(0, n - 2);
    var revX = stationX(reviewerI, n);
    var endX = n ? stationX(n - 1, n) : FIRST;
    var switchX = revX + 64;
    var sidingEnd = Math.min(W - 24, endX + 70);

    var wrapEl = el("div", "floor-scroll");
    wrapEl.tabIndex = 0;
    wrapEl.setAttribute("role", "region");
    wrapEl.setAttribute("aria-label", "The line, drawn as a track");
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, class: "floor-svg", role: "img" });
    var blocked = agents.filter(function (a) { return a.state === "blocked"; });
    s.append(svg("title", {}, "Assembly line of " + n + " agents" +
      (blocked.length ? "; stopped at " + blocked.map(function (a) { return a.name; }).join(", ") : "")));

    // Return loop: what Sender learns rides back to the Planner.
    if (n > 1) {
      var x0 = stationX(0, n), x1 = endX;
      var loop = "M" + x1 + " " + (TRACK - 52) + " C" + x1 + " " + LOOP_TOP + " " + (x1 - 60) + " " + LOOP_TOP + " " + (x1 - 120) + " " + LOOP_TOP +
        " L" + (x0 + 120) + " " + LOOP_TOP + " C" + (x0 + 60) + " " + LOOP_TOP + " " + x0 + " " + LOOP_TOP + " " + x0 + " " + (TRACK - 58);
      s.append(svg("path", { d: loop, class: "floor-loop" }));
      s.append(svg("path", { d: "M" + (x0 - 6) + " " + (TRACK - 66) + " L" + x0 + " " + (TRACK - 56) + " L" + (x0 + 6) + " " + (TRACK - 66), class: "floor-loop-head" }));
      var open = lessons.filter(function (l) { return l.status !== "fixed"; }).length;
      var back = lessons.filter(function (l) { return l.regressed; }).length;
      var lt = svg("text", { x: (x0 + x1) / 2, y: LOOP_TOP - 12, class: "floor-loop-label", "text-anchor": "middle" });
      lt.append(svg("tspan", {}, "Learning returns to the Planner  "));
      lt.append(svg("tspan", { class: "floor-mono" }, plural(lessons.length, "lesson", "lessons") + ", " + open + " open" + (back ? ", " + back + " came back" : "")));
      s.append(lt);
    }

    // Policy terminus: the first human touchpoint.
    s.append(svg("line", { x1: POLICY_X, y1: TRACK, x2: n ? stationX(0, n) : FIRST, y2: TRACK, class: "floor-human-track" }));
    s.append(svg("rect", { x: POLICY_X - 7, y: TRACK - 22, width: 14, height: 44, class: "floor-terminus" }));
    s.append(svg("text", { x: POLICY_X - 7, y: TRACK - 30, class: "floor-human-label" }, "Your policy"));
    s.append(svg("text", { x: POLICY_X - 7, y: TRACK + 44, class: "floor-small floor-human" }, trust.level ? String(trust.level) : ""));

    // Main track, one segment per hop; past a stopped station the line is dashed.
    var stoppedAt = -1;
    agents.forEach(function (a, i) { if (a.state === "blocked" && stoppedAt < 0) stoppedAt = i; });
    for (var i = 0; i < n - 1; i++) {
      var dead = stoppedAt >= 0 && i >= stoppedAt;
      s.append(svg("line", { x1: stationX(i, n), y1: TRACK, x2: stationX(i + 1, n), y2: TRACK, class: "floor-track" + (dead ? " is-dead" : "") }));
    }

    // Exceptions siding off a switch after the Reviewer.
    if (n > 1) {
      var sd = "M" + switchX + " " + TRACK + " C" + (switchX + 40) + " " + TRACK + " " + (switchX + 30) + " " + SIDING_Y + " " + (switchX + 90) + " " + SIDING_Y + " L" + sidingEnd + " " + SIDING_Y;
      s.append(svg("path", { d: sd, class: "floor-siding" }));
      s.append(svg("line", { x1: sidingEnd, y1: SIDING_Y - 12, x2: sidingEnd, y2: SIDING_Y + 12, class: "floor-buffer" }));
      s.append(svg("circle", { cx: switchX, cy: TRACK, r: 4, class: "floor-switch" }));
      var lab = svg("text", { x: switchX + 100, y: SIDING_Y - 14, class: "floor-human-label" });
      lab.append(svg("tspan", {}, "Needs you  "));
      lab.append(svg("tspan", { class: "floor-mono" }, String(inbox.length)));
      s.append(lab);
      inbox.slice(0, 8).forEach(function (_, k) {
        s.append(svg("rect", { x: sidingEnd - 16 - k * 11, y: SIDING_Y - 5, width: 7, height: 10, rx: 1, class: "floor-held" }));
      });
    }

    // Checkpoints: one barrier per gate, strongest layer first, between the switch and Sender.
    if (n > 1 && gates.length) {
      var order = LAYERS.map(function (L) { return L.key; });
      var g2 = gates.slice().sort(function (a, b) { return order.indexOf(a.layer) - order.indexOf(b.layer); });
      var gx0 = switchX + 44, gx1 = endX - 40;
      var gstep = g2.length > 1 ? Math.min(30, (gx1 - gx0) / (g2.length - 1)) : 0;
      var met = 0;
      g2.forEach(function (g, k) {
        var gx = gx0 + k * gstep;
        if (g.passed) met++;
        var grp = svg("g", { class: "floor-gate floor-gate-" + String(g.layer || "advised") + (g.passed ? " is-met" : "") });
        grp.append(svg("title", {}, String(g.label || "") + ": " + String(g.value != null ? g.value : "") + " against " + String(g.target != null ? g.target : "") + (g.passed ? ", met" : ", not yet")));
        grp.append(svg("line", { x1: gx, y1: TRACK - 26, x2: gx, y2: TRACK + 10, class: "floor-gate-post" }));
        grp.append(svg("rect", { x: gx - 5, y: TRACK - 36, width: 10, height: 10, class: "floor-gate-head" }));
        s.append(grp);
      });
      var gl = svg("text", { x: gx0 - 5, y: TRACK - 46, class: "floor-small" });
      gl.append(svg("tspan", { class: "floor-mono" }, met + "/" + g2.length));
      gl.append(svg("tspan", {}, " gates met"));
      s.append(gl);
    }

    // Leads already through: small marks parked short of the station they reached.
    var parked = {};
    handoffs.slice(0, -1).slice(-14).forEach(function (h) {
      var p = pos[h.to];
      if (!p) return;
      var k = parked[h.to] = (parked[h.to] || 0) + 1;
      if (k > 4) return;
      s.append(svg("rect", { x: p.x - 22 - k * 9, y: TRACK - 5, width: 6, height: 10, rx: 1, class: "floor-lead" }));
    });

    // Stations.
    agents.forEach(function (a, i) {
      var x = stationX(i, n);
      var state = ["idle", "working", "done", "blocked"].indexOf(a.state) >= 0 ? a.state : "idle";
      var g = svg("g", { class: "floor-station is-" + state });
      g.append(svg("title", {}, String(a.name || a.key) + ", " + state + ". " + String(a.did || "")));
      if (state === "working") g.append(svg("circle", { cx: x, cy: TRACK, r: 19, class: "floor-halo" }));
      if (state === "blocked") {
        g.append(svg("rect", { x: x - 30, y: TRACK - 24, width: 8, height: 48, class: "floor-stop" }));
      }
      g.append(svg("circle", { cx: x, cy: TRACK, r: 12, class: "floor-ring" }));
      if (state === "done" || state === "working") g.append(svg("circle", { cx: x, cy: TRACK, r: 5, class: "floor-core" }));
      if (state === "blocked") g.append(svg("path", { d: "M" + (x - 5) + " " + (TRACK - 5) + " L" + (x + 5) + " " + (TRACK + 5) + " M" + (x + 5) + " " + (TRACK - 5) + " L" + (x - 5) + " " + (TRACK + 5), class: "floor-x" }));
      g.append(svg("text", { x: x, y: TRACK - 30, "text-anchor": "middle", class: "floor-name" }, a.name || a.key));
      var c = svg("text", { x: x - 70, y: TRACK + 46, class: "floor-count" });
      c.append(svg("tspan", {}, String(num(a.count))));
      c.append(svg("tspan", { class: "floor-state", dx: 8 }, state === "blocked" ? "stopped" : state));
      g.append(c);
      wrap(a.did, 24, 3).forEach(function (line, k) {
        g.append(svg("text", { x: x - 70, y: TRACK + 70 + k * 18, class: "floor-did" }, line));
      });
      s.append(g);
    });

    // The one authored motion: the newest handoff's lead runs its hop.
    var newest = handoffs[handoffs.length - 1];
    if (newest && pos[newest.from]) {
      var toSiding = !pos[newest.to];
      var from = { x: pos[newest.from].x, y: TRACK };
      var to = toSiding ? { x: sidingEnd - 16, y: SIDING_Y } : { x: pos[newest.to].x - 22, y: TRACK };
      var mark = svg("rect", { x: -4, y: -6, width: 8, height: 12, rx: 1, class: "floor-lead is-new" + (toSiding ? " is-held" : "") });
      mark.style.transform = "translate(" + to.x + "px," + to.y + "px)";
      s.append(mark);
      var seen = lastShown.get(container);
      var fresh = newest.ts && newest.ts !== seen && (!seen || String(newest.ts) > String(seen));
      var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (fresh && !still && mark.animate) {
        var frames = [{ transform: "translate(" + from.x + "px," + from.y + "px)" }];
        if (toSiding) frames.push({ transform: "translate(" + switchX + "px," + TRACK + "px)", offset: 0.4 });
        frames.push({ transform: "translate(" + to.x + "px," + to.y + "px)" });
        mark.animate(frames, { duration: 640, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }); // var(--ease-out)
      }
      if (newest.ts) lastShown.set(container, newest.ts);
    }

    wrapEl.append(s);
    return wrapEl;
  }

  function headline(data) {
    var agents = data.agents || [];
    var handoffs = data.handoffs || [];
    var names = {};
    agents.forEach(function (a) { names[a.key] = a.name || a.key; });
    var head = el("header", "floor-head");
    var newest = handoffs[handoffs.length - 1];
    var h = el("h2", "floor-headline", newest ? newest.text : "The line is waiting for its first run.");
    var meta = el("p", "floor-meta");
    if (newest) {
      meta.append(el("span", "floor-mono", clock(newest.ts)), document.createTextNode("  " + (names[newest.from] || newest.from) + " handed to " + (names[newest.to] || newest.to)));
    }
    var working = agents.filter(function (a) { return a.state === "working"; }).map(function (a) { return a.name; });
    var stopped = agents.filter(function (a) { return a.state === "blocked"; }).map(function (a) { return a.name; });
    if (stopped.length) meta.append(el("span", "floor-stopped", "Stopped at " + stopped.join(", ")));
    else if (working.length) meta.append(el("span", null, working.join(", ") + " working"));
    head.append(h, meta);
    return head;
  }

  function log(data) {
    var names = {};
    (data.agents || []).forEach(function (a) { names[a.key] = a.name || a.key; });
    var items = (data.handoffs || []).slice(-5).reverse();
    if (!items.length) return null;
    var ol = el("ol", "floor-log");
    ol.setAttribute("aria-label", "Recent handoffs, newest first");
    items.forEach(function (h) {
      var li = el("li");
      li.append(el("span", "floor-mono", clock(h.ts)), el("span", "floor-hop", (names[h.from] || h.from) + " to " + (names[h.to] || h.to)), el("span", null, h.text));
      ol.append(li);
    });
    return ol;
  }

  /* 2. Why you can trust it */

  function trustSection(container, trust) {
    var sec = el("section", "floor-section floor-trust");
    sec.setAttribute("aria-labelledby", "floor-trust-h");
    var h2 = el("h2", null, "Why you can trust it");
    h2.id = "floor-trust-h";
    var side = el("div", "floor-level-col");
    var level = String(trust.level || "unknown");
    side.append(el("p", "floor-level", level));
    if (trust.note) side.append(el("p", "floor-note", trust.note));

    var i = LEVELS.indexOf(level);
    var up = i >= 0 && i < LEVELS.length - 1 ? LEVELS[i + 1] : null;
    var target = up || (i > 0 ? LEVELS[i - 1] : null);
    if (target) {
      var ctl = el("div", "floor-control");
      var btn = el("button", "floor-btn" + (up ? "" : " is-quiet"), (up ? "Request " : "Step back to ") + target);
      btn.type = "button";
      btn.addEventListener("click", function () {
        container.dispatchEvent(new CustomEvent("earshot:autonomy", { bubbles: true, detail: { level: target } }));
      });
      ctl.append(btn);
      // The server decides; when it would refuse, say why next to the button but leave it usable.
      var refused = up && (trust.requested === up && trust.allowed === false || (trust.blocked_by || []).length);
      if (refused && (trust.blocked_by || []).length) {
        var why = el("div", "floor-refusal");
        why.append(el("p", null, "Not yet granted, because:"));
        var ul = el("ul");
        trust.blocked_by.forEach(function (r) { ul.append(el("li", null, r)); });
        why.append(ul);
        ctl.append(why);
      }
      side.append(ctl);
    }

    var a = trust.agreement;
    if (a && num(a.n)) {
      var ag = el("p", "floor-agree");
      ag.append(document.createTextNode("Agreed with you on "),
        el("span", "floor-mono", num(a.agree) + " of " + num(a.n)),
        document.createTextNode(" reviews ("), el("span", "floor-mono", pct(a.rate) + "%"),
        document.createTextNode("), with "), el("span", "floor-mono", String(num(a.false_release))),
        document.createTextNode(" wrongly released and "), el("span", "floor-mono", String(num(a.false_hold))),
        document.createTextNode(" wrongly held."));
      side.append(ag);
    }

    var ladder = el("div", "floor-ladder");
    var gates = trust.gates || [];
    LAYERS.forEach(function (L) {
      var mine = gates.filter(function (g) { return (g.layer || "advised") === L.key; });
      if (!mine.length) return;
      var grp = el("div", "floor-rung floor-rung-" + L.key);
      grp.append(el("h3", null, L.title), el("p", "floor-rung-note", L.note));
      var ul = el("ul");
      mine.forEach(function (g) {
        var li = el("li", "floor-gate-row" + (g.passed ? " is-met" : ""));
        var mk = el("span", "floor-mark");
        mk.setAttribute("aria-hidden", "true");
        var val = el("span", "floor-gate-val floor-mono", String(g.value != null ? g.value : "–") + " / " + String(g.target != null ? g.target : "–"));
        li.append(mk, el("span", "floor-gate-label", g.label), val, el("span", "floor-verdict", g.passed ? "met" : "not yet"));
        ul.append(li);
      });
      grp.append(ul);
      ladder.append(grp);
    });
    if (!ladder.childNodes.length) ladder.append(el("p", "floor-empty", "No gates reported yet."));

    var body = el("div", "floor-trust-body");
    body.append(side, ladder);
    sec.append(h2, body);
    return sec;
  }

  /* 3. Needs you */

  function inboxSection(container, inbox) {
    var sec = el("section", "floor-section floor-inbox");
    sec.append(el("h2", null, "Needs you"));
    if (!inbox.length) { sec.append(el("p", "floor-empty", "Nothing needs you. The line is running.")); return sec; }
    var ul = el("ul");
    inbox.forEach(function (it) {
      var li = el("li");
      var b = el("button", "floor-inbox-btn");
      b.type = "button";
      b.append(el("span", "floor-inbox-name", it.name || it.login), el("span", "floor-mono floor-login", it.login));
      b.addEventListener("click", function () {
        container.dispatchEvent(new CustomEvent("earshot:open", { bubbles: true, detail: { login: it.login } }));
      });
      var r = el("ul", "floor-reasons");
      (it.reasons || []).forEach(function (x) { r.append(el("li", null, x)); });
      li.append(b, r);
      ul.append(li);
    });
    sec.append(ul);
    return sec;
  }

  /* 4. What it has learned */

  function lessonsSection(lessons) {
    var sec = el("section", "floor-section floor-lessons");
    sec.append(el("h2", null, "What it has learned"));
    if (!lessons.length) { sec.append(el("p", "floor-empty", "No lessons yet. It learns from what you change.")); return sec; }
    var ol = el("ol");
    lessons.slice().reverse().forEach(function (l) {
      var li = el("li", "floor-lesson" + (l.regressed ? " is-regressed" : "") + (l.status === "fixed" ? " is-fixed" : ""));
      var top = el("p", "floor-lesson-top");
      top.append(el("span", "floor-lesson-kind", l.kind || "lesson"),
        el("span", "floor-mono", "seen " + plural(num(l.seen), "time", "times")),
        el("span", "floor-lesson-status", l.status === "fixed" ? "fixed" : "open"));
      li.append(top);
      if (l.regressed) li.append(el("p", "floor-regressed", "Came back after it was fixed"));
      li.append(el("p", "floor-pattern", l.pattern), el("p", "floor-fix", l.fix ? "Fix: " + l.fix : ""));
      ol.append(li);
    });
    sec.append(ol);
    return sec;
  }

  /* 5. Proving ground */

  function simSection(sim) {
    var sec = el("section", "floor-section floor-sim");
    sec.append(el("h2", null, "Proving ground"));
    if (!sim || !(sim.by_kind || []).length) { sec.append(el("p", "floor-empty", "No simulation has run yet.")); return sec; }
    var meta = el("p", "floor-meta");
    meta.append(el("span", "floor-mono", plural(num(sim.cases), "case", "cases")));
    if (sim.ran_at) meta.append(el("span", null, "ran " + new Date(sim.ran_at).toLocaleString()));
    sec.append(meta);

    var wrap = el("div", "floor-table-wrap");
    var t = el("table", "floor-table");
    var hr = el("tr");
    [["Product kind", ""], ["Cases", "num"], ["Works, thin, fails", ""], ["Avg leads", "num"], ["Relevant", "num"], ["Interested", "num"], ["Annoyed", "num"]]
      .forEach(function (c) { var th = el("th", c[1], c[0]); th.scope = "col"; hr.append(th); });
    var thead = el("thead"); thead.append(hr);
    var tb = el("tbody");
    sim.by_kind.forEach(function (k) {
      var tr = el("tr");
      var th = el("th", null, k.kind); th.scope = "row";
      var total = num(k.works) + num(k.thin) + num(k.fails) || 1;
      var cell = el("td", "floor-bar-cell");
      var bar = el("span", "floor-bar");
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", num(k.works) + " work, " + num(k.thin) + " thin, " + num(k.fails) + " fail");
      ["works", "thin", "fails"].forEach(function (key) {
        var seg = el("span", "floor-bar-" + key);
        seg.style.flexGrow = String(num(k[key]) / total);
        bar.append(seg);
      });
      var bw = el("span", "floor-bar-wrap");
      cell.append(bw);
      bw.append(bar, el("span", "floor-mono floor-bar-nums", num(k.works) + " · " + num(k.thin) + " · " + num(k.fails)));
      tr.append(th, el("td", "num", num(k.cases)), cell, el("td", "num", (Math.round(num(k.avg_leads) * 10) / 10).toFixed(1)),
        el("td", "num", Math.round(num(k.relevant_pct)) + "%"), el("td", "num", Math.round(num(k.interested_pct)) + "%"), el("td", "num", Math.round(num(k.annoyed_pct)) + "%"));
      tb.append(tr);
    });
    t.append(thead, tb);
    wrap.append(t);
    sec.append(wrap);
    if ((sim.fit || []).length) {
      var ul = el("ul", "floor-fit");
      sim.fit.forEach(function (f) { ul.append(el("li", null, f)); });
      sec.append(ul);
    }
    return sec;
  }

  function render(container, data) {
    data = data || {};
    container.replaceChildren();
    container.classList.add("floor");
    var line = el("section", "floor-line");
    line.setAttribute("aria-label", "The line");
    line.append(headline(data), drawLine(container, data));
    var lg = log(data);
    if (lg) line.append(lg);
    var pair = el("div", "floor-pair");
    pair.append(inboxSection(container, data.inbox || []), lessonsSection(data.lessons || []));
    container.append(line, trustSection(container, data.trust || {}), pair, simSection(data.simulation));
  }

  window.EarshotFactory = { render: render };
})();
