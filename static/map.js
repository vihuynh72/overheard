// Earshot market map: pains -> people -> companies -> repos, drawn as four aligned columns.
// Every string in `data` is untrusted (GitHub / model output): text goes in via textContent only.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  // Layout in px; JS owns geometry, map.css owns type and colour.
  var COLS = [
    { key: "pain", title: "Pains", w: 248 },
    { key: "person", title: "People", w: 212 },
    { key: "company", title: "Companies", w: 156 },
    { key: "repo", title: "Where they wrote", w: 188 },
  ];
  var GAP = 88;          // horizontal room for links between columns
  var HEAD = 48;         // column header band
  var PAIN_H = 68;       // three lines of pain text
  var ROW_H = 32;        // person, company, repo rows
  var GROUP_GAP = 16;    // space between people groups

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  function layout(data) {
    var byId = {};
    var nodes = [];
    function add(kind, item) {
      if (!item || item.id == null) return;
      var id = String(item.id);
      var key = kind + ":" + id;
      if (byId[key]) return;
      byId[key] = { key: key, kind: kind, id: id, item: item, links: [] };
      nodes.push(byId[key]);
    }
    (data.pains || []).forEach(function (p) { add("pain", p); });
    (data.people || []).forEach(function (p) { add("person", p); });
    (data.companies || []).forEach(function (c) { add("company", c); });
    (data.repos || []).forEach(function (r) { add("repo", r); });

    // Edges only go pain-person, person-company, person-repo; anything else is ignored.
    function find(id, kinds) {
      for (var i = 0; i < kinds.length; i++) {
        var n = byId[kinds[i] + ":" + id];
        if (n) return n;
      }
      return null;
    }
    var edges = [];
    var seen = {};
    (data.edges || []).forEach(function (e) {
      if (!e) return;
      var a = find(String(e.from), ["pain", "person", "company", "repo"]);
      var b = find(String(e.to), ["person", "company", "repo", "pain"]);
      if (!a || !b) return;
      if (b.kind === "person" && a.kind !== "person") { var t = a; a = b; b = t; }
      if (a.kind === "person" && b.kind === "pain") { var s = a; a = b; b = s; }
      var ok = (a.kind === "pain" && b.kind === "person") ||
               (a.kind === "person" && (b.kind === "company" || b.kind === "repo"));
      if (!ok) return;
      var k = a.key + ">" + b.key;
      if (seen[k]) return;
      seen[k] = true;
      var edge = { a: a, b: b };
      edges.push(edge);
      a.links.push(edge);
      b.links.push(edge);
    });

    function neighbours(n, kind) {
      return n.links.map(function (e) { return e.a === n ? e.b : e.a; })
        .filter(function (m) { return m.kind === kind; });
    }
    function score(n) { var s = Number(n.item.score); return isFinite(s) ? s : -Infinity; }
    function byScore(a, b) { return score(b) - score(a); }

    // Pains by how many people voiced them; each person sits under the first pain they voiced, best score first.
    var pains = nodes.filter(function (n) { return n.kind === "pain"; });
    pains.forEach(function (p, i) { p.count = neighbours(p, "person").length; p.order = i; });
    pains.sort(function (a, b) { return b.count - a.count || a.order - b.order; });

    var placed = {};
    var groups = pains.map(function (p) {
      var people = neighbours(p, "person").filter(function (m) {
        if (placed[m.key]) return false;
        placed[m.key] = true;
        return true;
      }).sort(byScore);
      return { pain: p, people: people };
    });
    var loose = nodes.filter(function (n) { return n.kind === "person" && !placed[n.key]; }).sort(byScore);
    if (loose.length) groups.push({ pain: null, people: loose });

    var y = HEAD;
    groups.forEach(function (g) {
      var h = Math.max(g.people.length * ROW_H, g.pain ? PAIN_H : 0);
      if (g.pain) { g.pain.y = y; g.pain.h = PAIN_H; }
      var top = y + (h - g.people.length * ROW_H) / 2;
      g.people.forEach(function (m, i) { m.y = top + i * ROW_H; m.h = ROW_H; });
      y += h + GROUP_GAP;
    });
    var height = Math.max(y - GROUP_GAP, HEAD);

    // Companies and repos sit at the average height of their people, then get pushed apart.
    ["company", "repo"].forEach(function (kind) {
      var col = nodes.filter(function (n) { return n.kind === kind; });
      col.forEach(function (n, i) {
        var ppl = neighbours(n, "person");
        n.count = ppl.length;
        n.order = i;
        n.want = ppl.length
          ? ppl.reduce(function (s, m) { return s + m.y + ROW_H / 2; }, 0) / ppl.length - ROW_H / 2
          : Infinity;
        n.h = ROW_H;
      });
      col.sort(function (a, b) { return a.want - b.want || a.order - b.order; });
      var floor = HEAD;
      col.forEach(function (n) {
        n.y = Math.max(isFinite(n.want) ? n.want : floor, floor);
        floor = n.y + ROW_H;
      });
      // If pushing ran past the bottom, slide the column up as far as the header allows.
      var over = floor - height;
      if (over > 0) {
        for (var i = col.length - 1; i >= 0 && over > 0; i--) {
          var limit = i === 0 ? HEAD : col[i - 1].y + ROW_H;
          var shift = Math.min(over, col[i].y - limit);
          for (var j = i; j < col.length; j++) col[j].y -= shift;
          over -= shift;
        }
        height = Math.max(height, col.length ? col[col.length - 1].y + ROW_H : height);
      }
    });

    var x = 0;
    var colX = {};
    COLS.forEach(function (c) { colX[c.key] = x; x += c.w + GAP; });
    nodes.forEach(function (n) {
      n.x = colX[n.kind];
      n.w = COLS.filter(function (c) { return c.key === n.kind; })[0].w;
    });

    return { nodes: nodes, edges: edges, groups: groups, colX: colX, width: x - GAP, height: height + 8 };
  }

  function nodeEl(n) {
    var item = n.item;
    var box;
    if (n.kind === "person") {
      box = el("button", "emap-node emap-person");
      box.type = "button";
      var tier = el("span", "emap-tier", item.tier || "–");
      if (item.tier) tier.setAttribute("data-tier", String(item.tier));
      tier.setAttribute("aria-label", "Tier " + (item.tier || "unknown"));
      var name = el("span", "emap-name", item.name || n.id);
      var sc = el("span", "emap-num", item.score != null ? item.score : "");
      box.append(tier, name, sc);
      box.title = (item.name || n.id) + (item.company ? ", " + item.company : "") + (item.stage ? " (" + item.stage + ")" : "");
    } else if (n.kind === "pain") {
      box = el("div", "emap-node emap-pain");
      box.append(el("span", "emap-pain-text", item.text || n.id), el("span", "emap-num", n.count));
      box.title = String(item.text || n.id);
    } else {
      box = el("div", "emap-node emap-" + n.kind);
      box.append(el("span", "emap-name", n.id));
      if (n.kind === "repo") {
        box.append(el("span", "emap-num", n.count));
        if (item.kind === "product") box.setAttribute("data-product", "");
      }
      box.title = n.id + (n.kind === "repo" && item.kind ? " (" + item.kind + ")" : "");
    }
    if (n.kind !== "person") box.tabIndex = 0;
    box.style.left = n.x + "px";
    box.style.top = n.y + "px";
    box.style.width = n.w + "px";
    box.style.height = n.h + "px";
    return box;
  }

  function edgePath(e) {
    var x1 = e.a.x + e.a.w, y1 = e.a.y + e.a.h / 2;
    var x2 = e.b.x, y2 = e.b.y + e.b.h / 2;
    var mx = (x1 + x2) / 2;
    return "M" + x1 + " " + y1 + " C" + mx + " " + y1 + " " + mx + " " + y2 + " " + x2 + " " + y2;
  }

  function list(L) {
    var details = el("details", "emap-list");
    details.append(el("summary", null, "Read as a list"));
    var ul = el("ul");
    L.groups.forEach(function (g) {
      if (!g.people.length && !g.pain) return;
      var li = el("li");
      li.append(el("p", "emap-list-pain",
        g.pain ? (g.pain.item.text || g.pain.id) + " (" + g.pain.count + ")" : "No pain linked"));
      var inner = el("ul");
      // The map draws a person once; the list repeats them under every pain they voiced.
      var people = !g.pain ? g.people : g.pain.links.map(function (e) { return e.b; })
        .sort(function (x, y) { return (Number(y.item.score) || 0) - (Number(x.item.score) || 0); });
      people.forEach(function (m) {
        var parts = [];
        m.links.forEach(function (e) {
          var o = e.a === m ? e.b : e.a;
          if (o.kind === "company") parts.unshift(o.id);
          if (o.kind === "repo") parts.push("wrote in " + o.id);
        });
        var line = (m.item.name || m.id) + ", score " + (m.item.score != null ? m.item.score : "unknown") +
          ", tier " + (m.item.tier || "unknown") + (parts.length ? ". " + parts.join(", ") : "");
        inner.append(el("li", null, line));
      });
      li.append(inner);
      ul.append(li);
    });
    details.append(ul);
    return details;
  }

  function render(container, data) {
    container.replaceChildren();
    container.classList.add("emap");
    data = data || {};
    if (!(data.people || []).length) {
      container.append(el("p", "emap-empty", "No leads to map yet. Run a search first."));
      return;
    }
    var L = layout(data);

    var scroll = el("div", "emap-scroll");
    var canvas = el("div", "emap-canvas");
    canvas.setAttribute("role", "group");
    canvas.setAttribute("aria-label", "Map of pains, people, companies and repositories");
    canvas.style.width = L.width + "px";
    canvas.style.height = L.height + "px";

    COLS.forEach(function (c) {
      var h = el("p", "emap-head", c.title);
      h.style.left = L.colX[c.key] + "px";
      h.style.width = c.w + "px";
      canvas.append(h);
    });

    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "emap-links");
    svg.setAttribute("width", L.width);
    svg.setAttribute("height", L.height);
    svg.setAttribute("aria-hidden", "true");
    L.edges.forEach(function (e) {
      var p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", edgePath(e));
      p.setAttribute("class", "emap-edge" + (e.b.kind === "repo" ? " emap-edge-long" : ""));
      e.el = p;
      svg.append(p);
    });
    canvas.append(svg);

    L.nodes.forEach(function (n) {
      n.el = nodeEl(n);
      n.el.addEventListener("pointerenter", function () { focus(n); });
      n.el.addEventListener("pointerleave", clear);
      n.el.addEventListener("focus", function () { focus(n); });
      n.el.addEventListener("blur", clear);
      if (n.kind === "person") {
        n.el.addEventListener("click", function () {
          container.dispatchEvent(new CustomEvent("earshot:open", { bubbles: true, detail: { login: n.id } }));
        });
      }
      canvas.append(n.el);
    });

    function other(e, n) { return e.a === n ? e.b : e.a; }
    // A person lights its direct links; any other node lights its people and their other links,
    // because every link runs through a person and a pain alone would only light names.
    function focus(n) {
      var onN = new Set([n]);
      var onE = new Set();
      n.links.forEach(function (e) {
        onE.add(e);
        var m = other(e, n);
        onN.add(m);
        if (n.kind !== "person" && m.kind === "person") {
          m.links.forEach(function (f) {
            if (other(f, m).kind === n.kind && other(f, m) !== n) return; // no sibling pains/companies/repos
            onE.add(f);
            onN.add(other(f, m));
          });
        }
      });
      canvas.setAttribute("data-active", "");
      L.nodes.forEach(function (m) { m.el.classList.toggle("is-on", onN.has(m)); });
      L.edges.forEach(function (e) { e.el.classList.toggle("is-on", onE.has(e)); });
    }
    function clear() {
      var a = document.activeElement;
      var still = L.nodes.filter(function (m) { return m.el === a; })[0];
      if (still) { focus(still); return; }
      canvas.removeAttribute("data-active");
      L.nodes.forEach(function (m) { m.el.classList.remove("is-on"); });
      L.edges.forEach(function (e) { e.el.classList.remove("is-on"); });
    }

    scroll.append(canvas);
    container.append(scroll, list(L));
  }

  window.EarshotMap = { render: render };
})();
