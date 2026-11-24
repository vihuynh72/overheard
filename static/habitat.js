// Earshot habitat: the seven agents drawn as generative creatures living in one workroom, each at its own
// workspace, carrying work to each other as real handoffs arrive. API: EarshotHabitat.render(container, data).
// Every string in `data` is untrusted: it reaches the DOM through textContent and the canvas through fillText only.
(function () {
  "use strict";

  var W = 1000, H = 540, TAU = Math.PI * 2;
  var STATES = ["idle", "working", "done", "blocked"];
  var PLACES = {
    planner: { x: 95, y: 160, label: "Chart table" },
    scout: { x: 225, y: 360, label: "Reading room" },
    qualifier: { x: 355, y: 160, label: "Scales" },
    enricher: { x: 485, y: 360, label: "Address book" },
    writer: { x: 615, y: 160, label: "Writing desk" },
    reviewer: { x: 745, y: 360, label: "Proofing table" },
    gate: { x: 850, y: 160, label: "The Gate" },
    sender: { x: 925, y: 360, label: "Outbox" }
  };
  var ROUTE = ["planner", "scout", "qualifier", "enricher", "writer", "reviewer", "gate", "sender"];
  var ALCOVE = { x: 95, y: 462 };
  var COMMONS = { x: 500, y: 260 };
  var STAND = 64;                 // a creature stands this far above its workspace
  var GATE_OPEN = { shadow: 0, supervised: 0.35, autopilot: 1 };
  // Body plans: size and proportion per agent; the rest of each shape is seeded from its key.
  var BODY = {
    planner: { R: 25, squash: 1.08 }, scout: { R: 21, squash: 0.9 }, qualifier: { R: 27, squash: 0.72 },
    enricher: { R: 22, squash: 0.95 }, writer: { R: 23, squash: 1 }, reviewer: { R: 26, squash: 0.86 },
    sender: { R: 20, squash: 1.02 }
  };
  var BREATH = { idle: 1.1, working: 2.6, done: 0.8, blocked: 0 };

  var instances = new WeakMap(); // container -> instance
  var reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

  // --- small helpers -------------------------------------------------------------

  function hash(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function rng(seed) { // mulberry32
    return function () {
      seed = (seed + 0x6D2B79F5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function stamp(ts) { var n = typeof ts === "number" ? ts : Date.parse(ts); return isFinite(n) ? n : 0; }
  function clock(ts) {
    var d = new Date(stamp(ts));
    if (!stamp(ts)) return "";
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map(function (n) { return String(n).padStart(2, "0"); }).join(":");
  }
  function short(s, n) { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function ease(u) { return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2; }

  // Pre-seeded scenery so the room looks the same on every visit.
  var SPINES = (function () {
    var r = rng(hash("reading-room")), out = [];
    for (var shelf = 0; shelf < 2; shelf++) {
      var x = -42;
      while (x < 38) { var w = 4 + r() * 5; out.push({ shelf: shelf, x: x, w: w, h: 12 + r() * 10 }); x += w + 1.5; }
    }
    return out;
  })();
  var MOTES = (function () {
    var r = rng(hash("motes")), out = [];
    for (var i = 0; i < 48; i++) out.push({ x: r() * W, y: 40 + r() * (H - 80), p: r() * TAU, sp: 0.4 + r(), a: 0.08 + r() * 0.14 });
    return out;
  })();
  var PATH = (function () { // Catmull-Rom through the workspaces, along the floor
    var pts = ROUTE.map(function (k) { return { x: PLACES[k].x, y: PLACES[k].y + 80 }; }), seg = [];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      seg.push([p1, { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 }, { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 }, p2]);
    }
    return seg;
  })();

  // --- creatures -----------------------------------------------------------------

  function makeCreature(key) {
    var r = rng(hash("earshot:" + key)), b = BODY[key] || { R: 20 + r() * 6, squash: 0.85 + r() * 0.2 };
    var harm = [2, 3, 4, 5].map(function (k) { return { k: k, a: (0.025 + r() * 0.06) / (k * 0.55), p: r() * TAU, w: 0.3 + r() * 0.7 }; });
    var spots = [];
    for (var i = 0, n = 2 + Math.floor(r() * 3); i < n; i++) spots.push({ x: (r() - 0.5) * 0.9, y: 0.1 + r() * 0.5, r: 1.2 + r() * 1.8 });
    var np = [0, 1, 2].map(function () { return [r() * TAU, r() * TAU, r() * TAU]; });
    var c = {
      key: key, R: b.R, squash: b.squash, harm: harm, spots: spots, np: np, cilia: 3 + Math.floor(r() * 3),
      bp: r() * TAU, mt: r() * 10, nextBlink: 1 + r() * 3, blinkAt: -9, r: r,
      x: 0, y: 0, vx: 0, vy: 0, gx: 0, gy: 1, lean: 0, work: 0, pulse: 0, task: null,
      state: "idle", name: key, did: "", count: null
    };
    var h = home(c);
    c.x = h.x; c.y = h.y;
    return c;
  }
  function home(c) { var p = PLACES[c.key]; return p ? { x: p.x, y: p.y - STAND } : COMMONS; }
  function head(c) { return { x: c.x, y: c.y - c.R * c.squash - 14 }; }
  function noise(c, x, ch) { var p = c.np[ch]; return 0.6 * Math.sin(x + p[0]) + 0.3 * Math.sin(x * 2.3 + p[1]) + 0.1 * Math.sin(x * 4.7 + p[2]); }

  function target(c, inst) {
    if (c.task) return c.task();
    var h = home(c), t = inst.t, m = inst.still ? 0 : 1;
    if (c.state === "idle") return {
      x: h.x + (COMMONS.x - h.x) * 0.22 + noise(c, t * 0.11, 0) * 36 * m,
      y: h.y + (COMMONS.y - h.y) * 0.3 + noise(c, t * 0.09, 1) * 18 * m
    };
    if (c.state === "working") return { x: h.x + noise(c, t * 0.5, 0) * 5 * m, y: h.y + noise(c, t * 0.6, 1) * 3 * m };
    if (c.state === "done") return { x: h.x + 30 + noise(c, t * 0.2, 0) * 8 * m, y: h.y + 6 + noise(c, t * 0.25, 1) * 4 * m };
    return h; // blocked: stands still at its post
  }

  function attention(c, inst) {
    var a = inst.act;
    if (a) {
      if (a.carrier === c && a.phase === "carry") return a.dest();
      if (a.recipient === c) return a.phase === "carry" && a.carrier ? a.carrier : a.token;
    }
    var p = PLACES[c.key];
    if (p && c.state === "working") return { x: p.x + Math.sin(inst.t * 0.7) * 20, y: p.y - 6 };
    if (p && c.state === "blocked") return { x: p.x, y: p.y + 20 };
    var best = null, bd = 230 * 230;
    inst.creatures.forEach(function (o) {
      if (o === c) return;
      var d = (o.x - c.x) * (o.x - c.x) + (o.y - c.y) * (o.y - c.y);
      if (d < bd) { bd = d; best = o; }
    });
    return best || { x: c.x + noise(c, inst.t * 0.3, 2) * 120, y: c.y + 70 };
  }

  function step(c, inst, dt) {
    var tg = target(c, inst), K = c.task ? 9 : c.state === "blocked" ? 14 : 5, D = 2 * Math.sqrt(K);
    c.vx += ((tg.x - c.x) * K - c.vx * D) * dt;
    c.vy += ((tg.y - c.y) * K - c.vy * D) * dt;
    c.x += c.vx * dt; c.y += c.vy * dt;
    c.lean += (clamp(c.vx * 0.0025, -0.35, 0.35) - c.lean) * Math.min(1, dt * 6);
    c.work += ((c.state === "working" ? 1 : 0) - c.work) * Math.min(1, dt * 3);
    c.pulse *= Math.exp(-dt * 4);
    c.bp += dt * BREATH[c.state];
    c.mt += dt * (c.state === "working" ? 1.6 : c.state === "blocked" ? 0 : 0.6);
    var at = attention(c, inst), dx = at.x - c.x, dy = at.y - c.y, len = Math.hypot(dx, dy) || 1;
    var k = Math.min(1, dt * 5);
    c.gx += (dx / len - c.gx) * k; c.gy += (dy / len - c.gy) * k;
    if (inst.t > c.nextBlink && c.state !== "blocked") { c.blinkAt = inst.t; c.nextBlink = inst.t + 2.4 + c.r() * 4; }
  }

  function snap(c, inst) {
    var tg = target(c, inst), p = PLACES[c.key];
    c.x = tg.x; c.y = tg.y; c.vx = c.vy = 0; c.lean = 0; c.work = c.state === "working" ? 1 : 0;
    var at = p ? { x: p.x, y: p.y } : { x: c.x, y: c.y + 1 }, dx = at.x - c.x, dy = at.y - c.y, len = Math.hypot(dx, dy) || 1;
    c.gx = dx / len; c.gy = dy / len;
  }

  // --- drawing -------------------------------------------------------------------

  var PTS = new Float32Array(80);
  function bodyPath(ctx, c, rx, ry, k, oy) {
    var N = 40;
    for (var i = 0; i < N; i++) {
      var a = i / N * TAU, m = 1;
      for (var j = 0; j < c.harm.length; j++) { var h = c.harm[j]; m += h.a * Math.sin(h.k * a + h.p + c.mt * h.w); }
      var y = Math.sin(a) * ry * m * k;
      PTS[i * 2] = Math.cos(a) * rx * m * k;
      PTS[i * 2 + 1] = oy + y + (y > 0 ? y * 0.08 : 0); // a little weight settles in the belly
    }
    ctx.beginPath();
    ctx.moveTo((PTS[(N - 1) * 2] + PTS[0]) / 2, (PTS[(N - 1) * 2 + 1] + PTS[1]) / 2);
    for (i = 0; i < N; i++) {
      var n = ((i + 1) % N) * 2;
      ctx.quadraticCurveTo(PTS[i * 2], PTS[i * 2 + 1], (PTS[i * 2] + PTS[n]) / 2, (PTS[i * 2 + 1] + PTS[n + 1]) / 2);
    }
    ctx.closePath();
  }

  function blinkOf(c, inst, delay) {
    var u = (inst.t - c.blinkAt - (delay || 0)) / 0.16;
    var b = u > 0 && u < 1 ? Math.sin(Math.PI * u) : 0;
    if (c.state === "blocked") return 0.6;
    if (c.state === "done") return Math.max(b, 0.35);
    if (c.state === "working" && c.key === "writer") return Math.max(b, 0.3);
    return b;
  }
  function eye(ctx, inst, c, x, y, r, closed) {
    var col = inst.col, line = c.state === "blocked" ? col.danger : col.ink;
    if (closed > 0.85) {
      ctx.beginPath(); ctx.moveTo(x - r, y); ctx.quadraticCurveTo(x, y + r * 0.5, x + r, y);
      ctx.strokeStyle = line; ctx.lineWidth = 1.4; ctx.stroke(); return;
    }
    ctx.beginPath(); ctx.ellipse(x, y, r, r * (1 - closed), 0, 0, TAU);
    ctx.fillStyle = col.ink; ctx.fill();
    ctx.beginPath(); ctx.arc(x + c.gx * r * 0.42, y + c.gy * r * 0.42 * (1 - closed), r * 0.5 * (1 - closed * 0.5), 0, TAU);
    ctx.fillStyle = col.paper; ctx.fill();
  }
  function stroke(ctx, colour, w, alpha) { ctx.globalAlpha = alpha == null ? 1 : alpha; ctx.strokeStyle = colour; ctx.lineWidth = w; ctx.stroke(); ctx.globalAlpha = 1; }
  function fill(ctx, colour, alpha) { ctx.globalAlpha = alpha == null ? 1 : alpha; ctx.fillStyle = colour; ctx.fill(); ctx.globalAlpha = 1; }

  // Features that sit behind the body.
  function back(ctx, inst, c, rx, ry, line) {
    var t = inst.t, speed = clamp(Math.hypot(c.vx, c.vy) / 120, 0, 1);
    if (c.key === "scout") {
      [-1, 1].forEach(function (s) {
        var bx = s * rx * 0.35, by = -ry * 0.8;
        var dx = c.gx * 0.8 + s * 0.3, dy = c.gy * 0.6 - 0.8, l = Math.hypot(dx, dy) || 1;
        var len = c.R * (1.5 + 0.8 * c.work + 0.15 * Math.sin(t * 2.7 + s));
        var tx = bx + dx / l * len, ty = by + dy / l * len, wob = Math.sin(t * 3.1 + s * 2) * 6;
        ctx.beginPath(); ctx.moveTo(bx, by);
        ctx.quadraticCurveTo(bx + dx / l * len * 0.5 - dy / l * wob, by + dy / l * len * 0.5 + dx / l * wob, tx, ty);
        stroke(ctx, line, 1.4);
        ctx.beginPath(); ctx.arc(tx, ty, 2.4, 0, TAU); fill(ctx, line);
      });
    } else if (c.key === "sender") {
      var rate = 2.5 + 7 * Math.max(speed, c.work * 0.6), flap = Math.sin(t * rate) * (0.2 + 0.5 * Math.max(speed, c.work));
      [-1, 1].forEach(function (s) {
        var sx = s * rx * 0.45, sy = -ry * 0.35, ang = 0.95 + flap, L = c.R * 1.55;
        var tx = sx + s * Math.sin(ang) * L, ty = sy - Math.cos(ang) * L;
        ctx.beginPath(); ctx.moveTo(sx, sy);
        ctx.quadraticCurveTo(sx + s * L * 0.2, ty - 6, tx, ty);
        ctx.quadraticCurveTo(sx + s * L * 0.75, sy + 6, s * rx * 0.75, ry * 0.15);
        ctx.closePath();
        fill(ctx, line, 0.1); stroke(ctx, line, 1.3, 0.85);
        for (var v = 1; v <= 2; v++) {
          ctx.beginPath(); ctx.moveTo(sx, sy);
          ctx.lineTo(sx + (tx - sx) * (0.4 + v * 0.18), sy + (ty - sy) * (0.4 + v * 0.18) + v * 5);
          stroke(ctx, line, 0.9, 0.45);
        }
      });
    } else if (c.key === "planner") {
      for (var i = -1; i <= 1; i++) {
        var bx = i * rx * 0.3, by = -ry * 0.9, sway = Math.sin(t * 1.3 + i) * 3;
        var tx = i * rx * 0.58 + sway, ty = -ry * 1.6 - (i === 0 ? c.R * 0.3 : 0);
        ctx.beginPath(); ctx.moveTo(bx, by); ctx.quadraticCurveTo(i * rx * 0.2, -ry * 1.35, tx, ty);
        stroke(ctx, line, 1.3);
        ctx.beginPath(); ctx.arc(tx, ty, 2.2, 0, TAU); fill(ctx, line);
      }
    } else if (c.key === "enricher") {
      var sw = Math.sin(t * 1.1) * 4, ax = rx * 0.55 + sw, ay = -ry * 1.75;
      ctx.beginPath(); ctx.moveTo(rx * 0.1, -ry * 0.9); ctx.quadraticCurveTo(rx * 0.1, -ry * 1.5, ax, ay);
      stroke(ctx, line, 1.3);
      ctx.beginPath(); ctx.arc(ax + 4, ay, 4, Math.PI, Math.PI * 2.6); stroke(ctx, line, 1.3); // the finder's hook
    }
  }

  // Features in front of the body: faces, hands, tools.
  function front(ctx, inst, c, rx, ry, line) {
    var t = inst.t, fx = c.gx * rx * 0.2, fy = c.gy * ry * 0.12, i;
    if (c.key === "reviewer") {
      var sizes = [3.4, 4.2, 5, 4.2, 3.4];
      for (i = 0; i < 5; i++) {
        var a = -Math.PI * 0.85 + i * Math.PI * 0.175;
        eye(ctx, inst, c, fx + Math.cos(a) * rx * 0.52, fy + ry * 0.2 + Math.sin(a) * ry * 0.62, sizes[i] * c.R / 24, blinkOf(c, inst, i * 0.06));
      }
    } else if (c.key === "planner" || c.key === "sender") {
      eye(ctx, inst, c, fx, fy - ry * 0.15, c.R * (c.key === "planner" ? 0.3 : 0.24), blinkOf(c, inst));
    } else {
      var gap = c.key === "qualifier" ? 0.36 : 0.3, r = c.R * (c.key === "scout" ? 0.17 : 0.15);
      eye(ctx, inst, c, fx - rx * gap, fy - ry * 0.12, r, blinkOf(c, inst));
      eye(ctx, inst, c, fx + rx * gap, fy - ry * 0.12, r, blinkOf(c, inst, 0.02));
    }
    if (c.key === "qualifier") { // two pans, weighing one thing against another
      [-1, 1].forEach(function (s) {
        var bob = s * Math.sin(t * 2.2) * 6 * c.work + 4, px = s * (rx + 15), py = bob;
        ctx.beginPath(); ctx.moveTo(s * rx * 0.85, 0); ctx.quadraticCurveTo(s * (rx + 6), -8, px, py - 6);
        stroke(ctx, line, 1.3);
        ctx.beginPath(); ctx.arc(px, py - 6, 7, 0.1, Math.PI - 0.1); stroke(ctx, line, 1.4);
      });
    } else if (c.key === "writer") {
      var wx = Math.cos(t * 7) * 4 * c.work, wy = Math.sin(t * 14) * 2 * c.work;
      var hx = rx * 0.55 + wx, hy = ry * 1.05 + wy, qa = -1.05 + Math.sin(t * 7) * 0.12 * c.work;
      ctx.beginPath(); ctx.moveTo(rx * 0.7, ry * 0.15); ctx.quadraticCurveTo(rx * 1.05, ry * 0.7, hx, hy);
      stroke(ctx, line, 1.3);
      var qx = hx + Math.cos(qa) * 24, qy = hy + Math.sin(qa) * 24, nx = -Math.sin(qa) * 4, ny = Math.cos(qa) * 4;
      ctx.beginPath(); ctx.moveTo(hx, hy);
      ctx.quadraticCurveTo((hx + qx) / 2 + nx, (hy + qy) / 2 + ny, qx, qy);
      ctx.quadraticCurveTo((hx + qx) / 2 - nx, (hy + qy) / 2 - ny, hx, hy);
      fill(ctx, line, 0.15); stroke(ctx, line, 1);
    } else if (c.key === "enricher") {
      ctx.beginPath(); ctx.ellipse(0, ry * 0.3, rx * 0.5, ry * 0.32, 0, 0.15, Math.PI - 0.15);
      stroke(ctx, line, 1.2, 0.7);
      for (i = 0; i < 2; i++) { ctx.beginPath(); ctx.rect(-7 + i * 6, ry * 0.12 - i * 2, 5, 7); stroke(ctx, line, 1, 0.6); }
    }
  }

  function drawCreature(ctx, inst, c) {
    var col = inst.col, t = inst.t, line = c.state === "blocked" ? col.danger : col.ink;
    var b = Math.sin(c.bp) * (c.state === "working" ? 0.05 : 0.035), sc = 1 + 0.14 * c.pulse;
    var rx = c.R * sc * (1 - b * 0.4), ry = c.R * c.squash * sc * (1 + b) * (c.state === "blocked" ? 0.92 : 1);
    var speed = clamp(Math.hypot(c.vx, c.vy) / 120, 0, 1);
    ctx.save();
    ctx.translate(c.x, c.y);
    ctx.transform(1, 0, -c.lean, 1, 0, 0); // shear: the top leans the way it is going
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    back(ctx, inst, c, rx, ry, line);
    for (var i = 0; i < c.cilia; i++) { // feet
      var a = Math.PI * (0.25 + 0.5 * i / (c.cilia - 1)), bx = Math.cos(a) * rx * 0.92, by = Math.sin(a) * ry * 1.0;
      var wig = Math.sin(t * (2 + 10 * speed) + i * 1.7) * (1 + 2.5 * speed);
      ctx.beginPath(); ctx.moveTo(bx, by); ctx.quadraticCurveTo(bx + wig, by + 4, bx + Math.cos(a) * 3 + wig, by + 7);
      stroke(ctx, line, 1.2, 0.7);
    }
    bodyPath(ctx, c, rx, ry, 1, 0);
    ctx.globalAlpha = 1; ctx.fillStyle = col.paper; ctx.fill(); // opaque so the room does not show through
    fill(ctx, line, 0.1);
    stroke(ctx, line, 1.6);
    bodyPath(ctx, c, rx, ry, 0.62, -ry * 0.14);
    stroke(ctx, line, 1, 0.2);
    c.spots.forEach(function (s) { ctx.beginPath(); ctx.arc(s.x * rx, s.y * ry, s.r, 0, TAU); fill(ctx, line, 0.2); });
    front(ctx, inst, c, rx, ry, line);
    if (c.state === "blocked") { // a stop bar over its head
      ctx.beginPath(); ctx.moveTo(-8, -ry - 16); ctx.lineTo(8, -ry - 16);
      ctx.lineCap = "butt"; stroke(ctx, col.danger, 3.5);
    }
    ctx.restore();
    if (inst.focus === c.key) {
      ctx.beginPath(); ctx.setLineDash([4, 4]); ctx.arc(c.x, c.y - 4, c.R * 2, 0, TAU);
      stroke(ctx, col.focus, Math.max(2, 2 / inst.s)); ctx.setLineDash([]);
    }
  }

  function envelope(ctx, inst, x, y, rot) {
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot);
    ctx.beginPath(); ctx.rect(-7, -5, 14, 10); fill(ctx, inst.col.accent);
    ctx.beginPath(); ctx.moveTo(-7, -5); ctx.lineTo(0, 1); ctx.lineTo(7, -5); stroke(ctx, inst.col.paper, 1.2);
    ctx.restore();
  }

  // --- places --------------------------------------------------------------------

  function workOf(inst, key) { var c = inst.creatures.get(key); return c ? c.work : 0; }
  function seg(ctx, x1, y1, x2, y2) { ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); }

  function drawPlace(ctx, inst, key) {
    var p = PLACES[key], x = p.x, y = p.y, col = inst.col, ink = col.ink, t = inst.t;
    var w = workOf(inst, key), hot = w > 0.5 ? col.accent : ink, i;
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath();
    if (key === "planner") {
      seg(ctx, x - 42, y, x + 42, y); seg(ctx, x - 34, y, x - 34, y + 28); seg(ctx, x + 34, y, x + 34, y + 28);
      ctx.moveTo(x - 32, y - 4); ctx.lineTo(x + 28, y - 4); ctx.lineTo(x + 36, y - 20); ctx.lineTo(x - 24, y - 20); ctx.closePath();
      stroke(ctx, ink, 1.3, 0.55);
      ctx.beginPath(); ctx.setLineDash([2, 4]); ctx.moveTo(x - 22, y - 8); ctx.lineTo(x - 6, y - 16); ctx.lineTo(x + 8, y - 9); ctx.lineTo(x + 26, y - 17);
      ctx.lineDashOffset = -t * 6 * w; stroke(ctx, hot, 1.4, w > 0.5 ? 1 : 0.6); ctx.setLineDash([]);
    } else if (key === "scout") {
      seg(ctx, x - 46, y - 8, x + 46, y - 8); seg(ctx, x - 46, y + 20, x + 46, y + 20); seg(ctx, x - 46, y - 34, x - 46, y + 28); seg(ctx, x + 46, y - 34, x + 46, y + 28);
      stroke(ctx, ink, 1.3, 0.55);
      SPINES.forEach(function (s, n) {
        var base = s.shelf ? y + 20 : y - 8, pulled = n === 5 && w > 0.5;
        ctx.beginPath(); ctx.rect(x + s.x, base - s.h - (pulled ? 6 + Math.sin(t * 3) * 2 : 0), s.w, s.h);
        if (pulled) fill(ctx, col.accent); else stroke(ctx, ink, 1, 0.45);
      });
    } else if (key === "qualifier") {
      var tilt = w * Math.sin(t * 1.6) * 0.16 + 0.04;
      seg(ctx, x, y + 26, x, y - 18); seg(ctx, x - 16, y + 26, x + 16, y + 26);
      stroke(ctx, ink, 1.4, 0.55);
      var ex = Math.cos(tilt) * 36, ey = Math.sin(tilt) * 36;
      ctx.beginPath(); seg(ctx, x - ex, y - 18 - ey, x + ex, y - 18 + ey);
      seg(ctx, x - ex, y - 18 - ey, x - ex, y - 4 - ey); seg(ctx, x + ex, y - 18 + ey, x + ex, y - 4 + ey);
      stroke(ctx, ink, 1.3, 0.55);
      ctx.beginPath(); ctx.arc(x - ex, y - 4 - ey, 10, 0, Math.PI); stroke(ctx, ink, 1.3, 0.55);
      ctx.beginPath(); ctx.arc(x + ex, y - 4 + ey, 10, 0, Math.PI); stroke(ctx, ink, 1.3, 0.55);
      ctx.beginPath(); ctx.arc(x - ex, y - 1 - ey, 4, 0, TAU); fill(ctx, hot, w > 0.5 ? 1 : 0.5);
    } else if (key === "enricher") {
      seg(ctx, x, y - 14, x, y + 18);
      [-1, 1].forEach(function (s) {
        ctx.moveTo(x, y - 14); ctx.quadraticCurveTo(x + s * 20, y - 6, x + s * 42, y - 18);
        ctx.lineTo(x + s * 42, y + 12); ctx.quadraticCurveTo(x + s * 20, y + 22, x, y + 18);
      });
      for (i = 0; i < 3; i++) { seg(ctx, x - 34, y - 6 + i * 7, x - 8, y - 2 + i * 7); seg(ctx, x + 8, y - 2 + i * 7, x + 34 - i * 6, y - 6 + i * 7); }
      stroke(ctx, ink, 1.2, 0.55);
      ctx.beginPath(); ctx.rect(x + 42, y - 10 + Math.sin(t * 2) * 2 * w, 6, 9); fill(ctx, hot, w > 0.5 ? 1 : 0.4);
    } else if (key === "writer") {
      seg(ctx, x - 44, y, x + 44, y); seg(ctx, x - 36, y, x - 36, y + 28); seg(ctx, x + 36, y, x + 36, y + 28);
      ctx.moveTo(x - 18, y - 2); ctx.lineTo(x - 14, y - 30); ctx.lineTo(x + 18, y - 30); ctx.lineTo(x + 20, y - 2);
      stroke(ctx, ink, 1.3, 0.55);
      ctx.beginPath(); for (i = 0; i < 3; i++) seg(ctx, x - 11, y - 24 + i * 6, x + 13, y - 24 + i * 6); stroke(ctx, ink, 1, 0.4);
      var prog = w > 0.5 ? (t * 0.4) % 1 : 0.6;
      ctx.beginPath(); seg(ctx, x - 11, y - 6, x - 11 + 24 * prog, y - 6); stroke(ctx, hot, 1.4, w > 0.5 ? 1 : 0.4);
    } else if (key === "reviewer") {
      seg(ctx, x - 46, y, x + 46, y); seg(ctx, x - 38, y, x - 38, y + 28); seg(ctx, x + 38, y, x + 38, y + 28);
      ctx.rect(x - 34, y - 9, 26, 7); ctx.rect(x - 2, y - 10, 30, 8);
      stroke(ctx, ink, 1.3, 0.55);
      var lx = x + 6 + Math.sin(t * 0.9) * 18 * w, ly = y - 18;
      ctx.beginPath(); ctx.arc(lx, ly, 8, 0, TAU); seg(ctx, lx + 6, ly + 6, lx + 13, ly + 13);
      stroke(ctx, hot, 1.5, w > 0.5 ? 1 : 0.55);
    } else if (key === "gate") {
      var o = inst.gateO, gates = inst.trust.gates;
      seg(ctx, x - 32, y + 28, x - 32, y - 34); seg(ctx, x + 32, y + 28, x + 32, y - 34);
      ctx.moveTo(x - 32, y - 34); ctx.quadraticCurveTo(x, y - 58, x + 32, y - 34);
      stroke(ctx, ink, 1.5, 0.6);
      [-1, 1].forEach(function (s) { // two leaves swing open toward the viewer as trust is earned
        var lw = 30 * Math.cos(o * Math.PI * 0.45), hx = x + s * 32, ex = hx - s * lw; // hinge at the post, free edge toward the middle
        ctx.beginPath(); seg(ctx, hx, y - 24, ex, y - 24 + o * 6); seg(ctx, hx, y + 22, ex, y + 22 - o * 2);
        for (var v = 1; v <= 3; v++) { var vx = hx + (ex - hx) * v / 3; seg(ctx, vx, y - 24 + o * 2 * v, vx, y + 22); }
        stroke(ctx, ink, 1.2, 0.55);
      });
      var n = gates.length;
      for (i = 0; i < n; i++) {
        var u = n === 1 ? 0.5 : i / (n - 1), gx = x - 26 + 52 * u, gy = y - 36 - Math.sin(u * Math.PI) * 10;
        ctx.beginPath(); ctx.arc(gx, gy, 3, 0, TAU);
        if (gates[i] && gates[i].passed) fill(ctx, col.good); else stroke(ctx, col.control, 1.2);
      }
    } else if (key === "sender") {
      ctx.moveTo(x - 36, y - 6); ctx.lineTo(x + 36, y - 6); ctx.lineTo(x + 28, y + 20); ctx.lineTo(x - 28, y + 20); ctx.closePath();
      stroke(ctx, ink, 1.3, 0.55);
      for (i = 0; i < 2; i++) {
        ctx.beginPath(); ctx.rect(x - 18 + i * 4, y - 16 + i * 3, 30, 14); ctx.moveTo(x - 18 + i * 4, y - 16 + i * 3); ctx.lineTo(x - 3 + i * 4, y - 8 + i * 3); ctx.lineTo(x + 12 + i * 4, y - 16 + i * 3);
        stroke(ctx, ink, 1, 0.45);
      }
      if (w > 0.5) envelope(ctx, inst, x + 2, y - 22 - Math.abs(Math.sin(t * 2.5)) * 6, -0.08);
    }
  }

  function label(ctx, inst, x, y, title, sub, subColour) {
    var s = inst.s, big = clamp(15 * s, 11, 17) / s, small = clamp(11.5 * s, 10, 13) / s, col = inst.col;
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    ctx.font = "500 " + big + "px " + col.display; ctx.fillStyle = col.muted;
    ctx.fillText(title, x, y);
    if (sub) { ctx.font = "400 " + small + "px " + col.mono; ctx.fillStyle = subColour || col.muted; ctx.fillText(sub, x, y + small * 1.5); }
  }

  function drawLabels(ctx, inst) {
    var col = inst.col;
    ROUTE.forEach(function (key) {
      var p = PLACES[key], c = inst.creatures.get(key);
      if (key === "gate") {
        var g = inst.trust.gates, passed = g.filter(function (x) { return x && x.passed; }).length;
        label(ctx, inst, p.x, p.y + 48, p.label, short(inst.trust.level || "shut", 14) + " · " + passed + " of " + g.length);
        return;
      }
      if (!c) { label(ctx, inst, p.x, p.y + 48, p.label); return; }
      var sub = short(c.name, 16) + (c.count != null ? " · " + c.count : "");
      label(ctx, inst, p.x, p.y + 48, p.label, (c.state === "blocked" ? "stopped · " : "") + sub,
        c.state === "blocked" ? col.danger : c.state === "working" ? col.ink : col.muted);
      if (c.state === "done") {
        ctx.font = "400 " + clamp(11.5 * inst.s, 10, 13) / inst.s + "px " + col.mono;
        var wdt = ctx.measureText(sub).width;
        ctx.beginPath(); ctx.arc(p.x - wdt / 2 - 7, p.y + 48 + clamp(11.5 * inst.s, 10, 13) / inst.s * 1.15, 2.5, 0, TAU); fill(ctx, col.good);
      }
    });
  }

  function drawAlcove(ctx, inst) {
    var x = ALCOVE.x, y = ALCOVE.y, col = inst.col, items = inst.inbox, i;
    ctx.beginPath(); ctx.moveTo(x - 58, y + 24); ctx.lineTo(x - 58, y - 12); ctx.quadraticCurveTo(x - 58, y - 52, x, y - 52);
    ctx.quadraticCurveTo(x + 58, y - 52, x + 58, y - 12); ctx.lineTo(x + 58, y + 24);
    stroke(ctx, col.ink, 1.4, 0.5);
    ctx.beginPath(); ctx.moveTo(x - 48, y + 24); ctx.lineTo(x - 48, y - 10); ctx.quadraticCurveTo(x - 48, y - 42, x, y - 42);
    ctx.quadraticCurveTo(x + 48, y - 42, x + 48, y - 10); ctx.lineTo(x + 48, y + 24);
    stroke(ctx, col.ink, 1, 0.18);
    ctx.beginPath(); seg(ctx, x - 70, y + 24, x + 70, y + 24); stroke(ctx, col.ink, 1.2, 0.4);
    var small = clamp(10.5 * inst.s, 9, 12) / inst.s;
    ctx.font = "400 " + small + "px " + col.mono; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    for (i = 0; i < Math.min(items.length, 3); i++) {
      var sy = y - 26 + i * 15, sway = inst.still ? 0 : Math.sin(inst.t * 0.8 + i) * 0.6;
      ctx.save(); ctx.translate(x - 38, sy); ctx.rotate((i % 2 ? 0.03 : -0.03) + sway * 0.02);
      ctx.beginPath(); ctx.rect(0, -6, 76, 12); fill(ctx, col.paper2); stroke(ctx, col.ink, 1, 0.5);
      ctx.fillStyle = col.ink; ctx.fillText(short(items[i].login || items[i].name, 11), 4, 0.5);
      ctx.restore();
    }
    if (items.length > 3) { ctx.fillStyle = col.muted; ctx.textAlign = "center"; ctx.fillText("+" + (items.length - 3) + " more", x, y + 16); }
    label(ctx, inst, x, y + 46, "Needs you", items.length ? items.length + " waiting" : "nothing waiting", items.length ? col.accent : col.muted);
  }

  function draw(inst) {
    var ctx = inst.ctx, col = inst.col, k = inst.dpr * inst.s;
    if (!inst.cssW) return;
    ctx.setTransform(k, 0, 0, k, 0, 0);
    ctx.clearRect(0, 0, W, H);
    MOTES.forEach(function (m) {
      var mx = m.x + (inst.still ? 0 : Math.sin(inst.t * 0.05 * m.sp + m.p) * 22), my = m.y + (inst.still ? 0 : Math.cos(inst.t * 0.04 * m.sp + m.p) * 14);
      ctx.beginPath(); ctx.arc(mx, my, 1.1, 0, TAU); fill(ctx, col.ink, m.a);
    });
    ctx.beginPath(); ctx.moveTo(PATH[0][0].x, PATH[0][0].y);
    PATH.forEach(function (s) { ctx.bezierCurveTo(s[1].x, s[1].y, s[2].x, s[2].y, s[3].x, s[3].y); });
    ctx.setLineDash([3, 7]); ctx.lineDashOffset = -inst.flow; stroke(ctx, col.rule, 1.4); ctx.setLineDash([]);
    ROUTE.forEach(function (key) { drawPlace(ctx, inst, key); });
    drawAlcove(ctx, inst);
    drawLabels(ctx, inst);
    Array.from(inst.creatures.values()).sort(function (a, b) { return a.y - b.y; }).forEach(function (c) { drawCreature(ctx, inst, c); });
    var a = inst.act;
    if (a && a.token) envelope(ctx, inst, a.token.x, a.token.y, Math.sin(inst.t * 4) * 0.15);
  }

  // --- handoffs ------------------------------------------------------------------

  function alcoveSpot() { return { x: ALCOVE.x + 66, y: ALCOVE.y - 34 }; }

  function start(inst, h) {
    var from = inst.creatures.get(h.from), to = inst.creatures.get(h.to);
    showCaption(inst, h);
    if (from === to) to = null;
    if (!from && !to) return;
    var act = { h: h, carrier: from || null, recipient: to || null, phase: from ? "carry" : "fly", t0: inst.t };
    act.dest = function () {
      if (!act.recipient) return alcoveSpot();
      var side = act.carrier && act.carrier.x < act.recipient.x ? -1 : 1;
      return { x: act.recipient.x + side * 50, y: act.recipient.y + 4 };
    };
    if (from) {
      from.task = act.dest;
      act.token = head(from);
    } else {
      act.from = { x: ALCOVE.x, y: ALCOVE.y - 20 }; // the human hands it in
      act.token = { x: act.from.x, y: act.from.y };
    }
    inst.act = act;
  }

  function advance(inst) {
    var a = inst.act;
    if (!a) { if (inst.queue.length) start(inst, inst.queue.shift()); return; }
    if (a.phase === "carry") {
      var hd = head(a.carrier), d = a.dest();
      a.token = { x: hd.x, y: hd.y + Math.sin(inst.t * 6) * 1.5 };
      if (Math.hypot(a.carrier.x - d.x, a.carrier.y - d.y) < 12 || inst.t - a.t0 > 4) {
        a.phase = "fly"; a.t0 = inst.t; a.from = hd; a.carrier.task = null;
      }
      return;
    }
    var u = Math.min(1, (inst.t - a.t0) / 0.5), e = ease(u);
    var to = a.recipient ? head(a.recipient) : { x: ALCOVE.x, y: ALCOVE.y - 20 };
    a.token = { x: a.from.x + (to.x - a.from.x) * e, y: a.from.y + (to.y - a.from.y) * e - Math.sin(Math.PI * u) * 30 };
    if (u >= 1) { if (a.recipient) a.recipient.pulse = 1; inst.act = null; }
  }

  function showCaption(inst, h) {
    var nameOf = function (k) { var c = inst.creatures.get(k); return c ? c.name : k === "inbox" ? "Needs you" : String(k || ""); };
    inst.capWhen.textContent = clock(h.ts);
    inst.capWho.textContent = short(nameOf(h.from), 24) + " to " + short(nameOf(h.to), 24);
    inst.capWhat.textContent = String(h.text || "");
  }

  // --- the instance --------------------------------------------------------------

  function create(container) {
    var wrap = el("div", "habitat"), stage = el("div", "habitat-stage"), canvas = document.createElement("canvas");
    var tip = el("div", "habitat-tip"), cap = el("p", "habitat-caption"), list = el("ul", "habitat-sr");
    canvas.setAttribute("aria-hidden", "true");
    tip.setAttribute("aria-hidden", "true"); tip.hidden = true;
    var tipName = el("p", "habitat-tip-name"), tipState = el("p", "habitat-tip-state"), tipDid = el("p", "habitat-tip-did"), tipCount = el("p", "habitat-tip-count");
    tip.append(tipName, tipState, tipDid, tipCount);
    cap.setAttribute("aria-live", "polite");
    var capWhen = el("span", "habitat-when"), capWho = el("span", "habitat-who"), capWhat = el("span", "habitat-what", "No handoffs yet.");
    cap.append(capWhen, capWho, capWhat);
    list.setAttribute("aria-label", "Agents");
    stage.append(canvas, tip);
    wrap.append(stage, cap, list);
    container.replaceChildren(wrap);

    var inst = {
      wrap: wrap, canvas: canvas, ctx: canvas.getContext("2d"), tip: tip, tipName: tipName, tipState: tipState, tipDid: tipDid, tipCount: tipCount,
      capWhen: capWhen, capWho: capWho, capWhat: capWhat, list: list, buttons: new Map(),
      creatures: new Map(), queue: [], act: null, seen: new Set(), lastTs: -Infinity, primed: false,
      trust: { level: "", gates: [] }, inbox: [], gateO: 0, flow: 0,
      t: 0, last: 0, raf: 0, visible: true, still: reduceQuery.matches, s: 1, dpr: 1, cssW: 0,
      hover: null, focus: null, tipKey: ""
    };
    inst.col = (function () {
      var cs = getComputedStyle(wrap), v = function (n) { return cs.getPropertyValue(n).trim(); };
      return {
        paper: v("--color-paper"), paper2: v("--color-paper-2"), rule: v("--color-rule"), control: v("--color-control"),
        muted: v("--color-muted"), ink: v("--color-ink"), accent: v("--color-accent"), good: v("--color-good"),
        danger: v("--color-danger"), focus: v("--color-focus"), display: v("--font-display"), mono: v("--font-mono")
      };
    })();

    function frame(now) {
      inst.raf = 0;
      if (!wrap.isConnected) { destroy(); return; }
      var dt = Math.min(0.05, (now - inst.last) / 1000 || 0);
      inst.last = now; inst.t += dt;
      var anyWorking = false;
      inst.creatures.forEach(function (c) { step(c, inst, dt); if (c.state === "working") anyWorking = true; });
      inst.flow += dt * (anyWorking ? 14 : 2);
      inst.gateO += ((GATE_OPEN[inst.trust.level] || 0) - inst.gateO) * Math.min(1, dt * 2);
      advance(inst);
      draw(inst);
      placeTip(inst);
      sync();
    }
    function sync() {
      var run = !inst.still && inst.visible && !document.hidden && wrap.isConnected;
      if (run && !inst.raf) { inst.last = performance.now(); inst.raf = requestAnimationFrame(frame); }
      else if (!run && inst.raf) { cancelAnimationFrame(inst.raf); inst.raf = 0; }
    }
    function still() { // reduced motion: one calm frame with everyone at their post
      inst.act = null; inst.queue.length = 0;
      inst.creatures.forEach(function (c) { c.task = null; snap(c, inst); });
      inst.gateO = GATE_OPEN[inst.trust.level] || 0;
      draw(inst); placeTip(inst);
    }
    function onMotion() { inst.still = reduceQuery.matches; if (inst.still) still(); sync(); }
    function onVisibility() { sync(); }
    function destroy() {
      if (inst.raf) cancelAnimationFrame(inst.raf);
      inst.raf = 0; ro.disconnect(); io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduceQuery.removeEventListener("change", onMotion);
      if (instances.get(container) === inst) instances.delete(container);
    }

    var ro = new ResizeObserver(function (entries) {
      var w = entries[0].contentRect.width;
      if (!w || w === inst.cssW) return;
      inst.cssW = w; inst.s = w / W; inst.dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.style.height = H * inst.s + "px";
      canvas.width = Math.round(w * inst.dpr); canvas.height = Math.round(H * inst.s * inst.dpr);
      if (inst.still) still();
    });
    ro.observe(stage);
    var io = new IntersectionObserver(function (entries) {
      inst.visible = entries[entries.length - 1].isIntersecting;
      if (!wrap.isConnected) destroy(); else sync();
    });
    io.observe(stage);
    document.addEventListener("visibilitychange", onVisibility);
    reduceQuery.addEventListener("change", onMotion);
    if (document.fonts) document.fonts.ready.then(function () { if (inst.still && wrap.isConnected) still(); });

    function pick(e) {
      var x = e.offsetX / inst.s, y = e.offsetY / inst.s, best = null, bd = 44 * 44;
      inst.creatures.forEach(function (c) { var d = (c.x - x) * (c.x - x) + (c.y - y) * (c.y - y); if (d < bd) { bd = d; best = c.key; } });
      return best;
    }
    canvas.addEventListener("pointermove", function (e) {
      var k = pick(e);
      if (k === inst.hover) return;
      inst.hover = k; canvas.classList.toggle("is-pointing", !!k);
      if (inst.still) placeTip(inst);
    });
    canvas.addEventListener("pointerleave", function () { inst.hover = null; canvas.classList.remove("is-pointing"); if (inst.still) placeTip(inst); });
    canvas.addEventListener("click", function (e) { var k = pick(e); if (k) select(k); });
    function select(key) { container.dispatchEvent(new CustomEvent("earshot:agent", { bubbles: true, detail: { key: key } })); }

    inst.button = function (key) {
      var b = el("button");
      b.type = "button";
      b.addEventListener("focus", function () { inst.focus = key; if (inst.still) { draw(inst); placeTip(inst); } });
      b.addEventListener("blur", function () { if (inst.focus === key) inst.focus = null; if (inst.still) { draw(inst); placeTip(inst); } });
      b.addEventListener("click", function () { select(key); });
      var li = el("li"); li.append(b); list.append(li);
      return b;
    };
    inst.still_ = still; inst.sync = sync;
    return inst;
  }

  function placeTip(inst) {
    var key = inst.focus || inst.hover, c = key && inst.creatures.get(key), tip = inst.tip;
    if (!c) { if (!tip.hidden) tip.hidden = true; inst.tipKey = ""; return; }
    var sig = key + "|" + c.state + "|" + c.did + "|" + c.count + "|" + c.name;
    if (sig !== inst.tipKey) {
      inst.tipKey = sig;
      inst.tipName.textContent = c.name;
      inst.tipState.textContent = c.state === "blocked" ? "stopped" : c.state;
      inst.tipState.dataset.state = c.state;
      inst.tipDid.textContent = c.did || "Nothing yet.";
      inst.tipCount.textContent = c.count != null ? "count " + c.count : "";
    }
    var x = clamp(c.x * inst.s, 132, Math.max(132, inst.cssW - 132)), y = (c.y - c.R * c.squash - 22) * inst.s;
    var below = y < 110;
    if (below) y = (c.y + c.R * c.squash + 16) * inst.s;
    tip.classList.toggle("is-below", below);
    tip.style.left = x + "px"; tip.style.top = y + "px";
    if (tip.hidden) tip.hidden = false;
  }

  function update(inst, data) {
    data = data || {};
    var agents = Array.isArray(data.agents) ? data.agents : [], keep = new Set();
    agents.forEach(function (a) {
      if (!a || a.key == null) return;
      var key = String(a.key), c = inst.creatures.get(key);
      if (!c) { c = makeCreature(key); inst.creatures.set(key, c); }
      keep.add(key);
      c.state = STATES.indexOf(a.state) >= 0 ? a.state : "idle";
      c.name = String(a.name || key);
      c.did = String(a.did || "");
      c.count = a.count != null && isFinite(Number(a.count)) ? Number(a.count) : null;
      var b = inst.buttons.get(key) || inst.buttons.set(key, inst.button(key)).get(key);
      b.textContent = c.name + ", " + (c.state === "blocked" ? "stopped" : c.state) + ". " + (c.did ? c.did + ". " : "") + (c.count != null ? "Count " + c.count + "." : "");
    });
    inst.creatures.forEach(function (c, key) {
      if (keep.has(key)) return;
      inst.creatures.delete(key);
      var b = inst.buttons.get(key); if (b) { b.parentNode.remove(); inst.buttons.delete(key); }
      if (inst.act && (inst.act.carrier === c || inst.act.recipient === c)) inst.act = null;
    });
    var tr = data.trust || {};
    inst.trust = { level: String(tr.level || ""), gates: Array.isArray(tr.gates) ? tr.gates : [] };
    inst.inbox = Array.isArray(data.inbox) ? data.inbox.filter(Boolean) : [];

    var hs = Array.isArray(data.handoffs) ? data.handoffs.filter(Boolean) : [], fresh = [];
    hs.forEach(function (h) {
      var sig = stamp(h.ts) + "|" + h.from + "|" + h.to + "|" + h.text;
      if (inst.seen.has(sig) || stamp(h.ts) < inst.lastTs) return;
      inst.seen.add(sig); fresh.push(h);
    });
    if (hs.length) inst.lastTs = Math.max(inst.lastTs, stamp(hs[hs.length - 1].ts));
    if (inst.seen.size > 400) inst.seen = new Set(Array.from(inst.seen).slice(-200));
    if (!inst.primed || inst.still) { // history is not replayed; only what happens from now on is acted out
      inst.primed = true;
      if (hs.length) showCaption(inst, hs[hs.length - 1]);
    } else {
      inst.queue = inst.queue.concat(fresh).slice(-4); // keep up when many arrive at once
    }
    if (inst.still) inst.still_();
    inst.sync();
  }

  window.EarshotHabitat = {
    render: function (container, data) {
      var inst = instances.get(container);
      if (!inst || !container.contains(inst.wrap)) { inst = create(container); instances.set(container, inst); }
      update(inst, data);
    }
  };
})();
