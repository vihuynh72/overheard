// Earshot pilot: a second, visibly machine-owned cursor that operates the real interface while the founder watches.
// It moves to real elements and clicks them for real, never presses anything on the denylist, and yields to any human input.
// Every string from the server is untrusted: it only ever reaches the page through textContent.
(function () {
  "use strict";

  // Controls that spend money or carry a decision that belongs to the human or to the gated Sender.
  var DENY = "[data-act], [data-topup], form#intake button, [data-stage], .floor-trust .floor-control";
  var DENY_WORDS = /^\s*(approve|reject|request|add|find)/i; // prefix, so "Requesting" and "Adding" are caught too
  var STORE_KEY = "earshot.pilot";
  var IDLE_RESUME_MS = 8000;
  var PATROL_AFTER_MS = 9000;
  var WAIT_MS = 4000;
  var QUEUE_CAP = 12;
  var PATROL = ["floor", "leads", "map"];
  var PATROL_SAY = {
    floor: "Checking on the line of agents",
    leads: "Looking over the leads again",
    map: "Checking who shares which pain",
    profile: "Rereading the customer profile",
    pipeline: "Glancing at where each lead stands",
    activity: "Reading back what the agents did"
  };
  var ABORT = { abort: true };

  var enabled = true, paused = false, running = false, built = false;
  var gen = 0, queue = [], latest = null, seen = null;
  var pos = { x: 0, y: 0 }, vel = 0, flip = 1, travelling = false;
  var marked = null, markHold = false, captionOn = false;
  var idleSince = 0, selfUntil = 0, graceUntil = 0, moved = 0, resumeTimer = 0;
  var root, cursor, caption, ripple, mark, live, dock, toggle, takeover;
  var T = { min: 520, max: 1500, dwell: 1600, press: 150 };

  /* --- small helpers --- */

  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function now() { return performance.now(); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function reduced() { return matchMedia("(prefers-reduced-motion: reduce)").matches; }
  function cap(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }
  function label(el) { return (el.textContent || el.value || el.getAttribute("aria-label") || "this control").trim().replace(/\s+/g, " ").slice(0, 48); }
  function ms(name, fallback) {
    var v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name));
    return isFinite(v) ? v : fallback;
  }
  function store(v) { try { localStorage.setItem(STORE_KEY, v ? "on" : "off"); } catch (e) { /* private mode: state lasts this page only */ } }
  function stored() { try { return localStorage.getItem(STORE_KEY) !== "off"; } catch (e) { return true; } }

  function isDenied(el) {
    if (!el || !el.closest) return true;
    if (el.closest(DENY)) return true;
    var b = el.closest("button, [role='button'], input[type='submit'], input[type='button']");
    return !!b && DENY_WORDS.test(b.textContent || b.value || "");
  }

  // The only place the pilot presses anything. The denylist is checked here, at the moment of the click.
  function activate(el) {
    if (!el.isConnected || isDenied(el) || el.disabled) return false;
    if (typeof el.click === "function") el.click();
    else el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    return true;
  }

  /* --- the drawn cursor --- */

  function svgEl(tag, attrs) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }
  function cursorSvg() {
    var s = svgEl("svg", { viewBox: "0 0 24 28", width: "24", height: "28", class: "pilot-arrow", "aria-hidden": "true" });
    s.append(svgEl("path", { d: "M3 2 L3 21.5 L8.2 16.9 L11.6 25 L15.2 23.5 L11.9 15.6 L19 15.6 Z", class: "pilot-arrow-body" }));
    s.append(svgEl("path", { d: "M5.2 7.2 L5.2 16.4", class: "pilot-arrow-glint" }));
    return s;
  }

  function build() {
    if (built || !document.body) return;
    built = true;
    T.min = ms("--pilot-travel-min", T.min); T.max = ms("--pilot-travel-max", T.max);
    T.dwell = ms("--pilot-dwell", T.dwell); T.press = ms("--pilot-press", T.press);

    root = h("div", "pilot-root");
    root.setAttribute("aria-hidden", "true");
    mark = h("div", "pilot-mark");
    ripple = h("span", "pilot-ripple");
    cursor = h("div", "pilot-cursor");
    var tag = h("span", "pilot-tag");
    tag.append(h("span", "pilot-dot"), h("span", null, "Earshot"));
    cursor.append(cursorSvg(), tag);
    caption = h("p", "pilot-caption");
    root.append(mark, ripple, caption, cursor);

    live = h("div", "pilot-live");
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");

    dock = h("div", "pilot-dock");
    takeover = h("div", "pilot-takeover");
    takeover.hidden = true;
    var resume = h("button", "pilot-btn", "Resume");
    resume.type = "button";
    resume.addEventListener("click", function () { resumeNow(true); });
    takeover.append(h("span", null, "You have the controls"), resume);
    toggle = h("button", "pilot-toggle");
    toggle.type = "button";
    toggle.append(h("span", "pilot-dot"), h("span", "pilot-toggle-text"));
    toggle.addEventListener("click", function () { enabled ? api.disable() : api.enable(); });
    dock.append(takeover, toggle);
    document.body.append(root, live, dock);

    pos.x = innerWidth - 140; pos.y = innerHeight - 120;
    paint();
    requestAnimationFrame(frame);
  }

  function paint() {
    if (!built) return;
    root.hidden = !enabled;
    root.classList.toggle("is-paused", paused);
    toggle.setAttribute("aria-pressed", String(enabled));
    toggle.lastChild.textContent = enabled ? "Pilot on" : "Pilot off";
    toggle.setAttribute("aria-label", enabled ? "Earshot pilot is on. Turn it off" : "Earshot pilot is off. Turn it on");
    takeover.hidden = !(enabled && paused);
  }

  // One render loop draws the cursor, its caption and the target outline from the current state.
  function frame(t) {
    requestAnimationFrame(frame);
    if (!enabled || document.hidden) return;
    var still = !travelling && !paused && !reduced();
    var bob = still ? Math.sin(t / 640) * 1.6 : 0;
    var tilt = reduced() ? 0 : clamp(vel * 0.9, -9, 9) + (still ? Math.sin(t / 910) * 1.2 : 0);
    cursor.style.transform = "translate3d(" + (pos.x - 3).toFixed(1) + "px," + (pos.y - 2 + bob).toFixed(1) + "px,0) rotate(" + tilt.toFixed(2) + "deg)";
    var w = caption.offsetWidth, ch = caption.offsetHeight;
    var cx = pos.x + 24 + w > innerWidth - 16 ? pos.x - w - 14 : pos.x + 24;
    var cy = pos.y + 30;
    if (marked && marked.isConnected) { // sit clear of the target so the caption never hides what it points at
      var mr = marked.getBoundingClientRect();
      cy = mr.bottom + 12 + ch <= innerHeight - 16 ? Math.max(cy, mr.bottom + 12) : mr.top - ch - 12;
    }
    cy = clamp(cy, 16, innerHeight - ch - 16);
    caption.style.transform = "translate3d(" + clamp(cx, 16, innerWidth - w - 16).toFixed(1) + "px," + cy.toFixed(1) + "px,0)";
    caption.classList.toggle("is-on", captionOn);
    if (marked && marked.isConnected) {
      var r = marked.getBoundingClientRect();
      mark.style.transform = "translate3d(" + (r.left - 4).toFixed(1) + "px," + (r.top - 4).toFixed(1) + "px,0)";
      mark.style.width = (r.width + 8) + "px";
      mark.style.height = (r.height + 8) + "px";
      mark.classList.add("is-on");
      mark.classList.toggle("is-hold", markHold);
    } else mark.classList.remove("is-on");
  }

  function say(text) {
    caption.textContent = text;
    live.textContent = text;
    captionOn = true;
  }

  /* --- time and motion, both of which stop while the human has the controls --- */

  function sleep(d) {
    var my = gen;
    return new Promise(function (res, rej) {
      var left = d, last = now();
      var id = setInterval(function () {
        if (my !== gen) { clearInterval(id); rej(ABORT); return; }
        var n = now();
        if (!paused) left -= n - last;
        last = n;
        if (left <= 0) { clearInterval(id); res(); }
      }, 50);
    });
  }

  function whilePaused() { return paused ? sleep(1).then(whilePaused) : Promise.resolve(); }

  function ease(t) {
    var out = 1 - Math.pow(1 - t, 3), smooth = t * t * (3 - 2 * t);
    return 0.4 * smooth + 0.6 * out; // leaves gently, slows clearly on arrival
  }

  function travel(tx, ty) {
    var sx = pos.x, sy = pos.y, dx = tx - sx, dy = ty - sy, d = Math.hypot(dx, dy);
    if (reduced() || d < 2) { pos.x = tx; pos.y = ty; return Promise.resolve(); }
    flip = -flip;
    var bend = Math.min(d * 0.22, 140) * flip;
    var cx = sx + dx / 2 - (dy / d) * bend, cy = sy + dy / 2 + (dx / d) * bend;
    var dur = clamp(T.min + d * 0.55, T.min, T.max), my = gen;
    travelling = true;
    return new Promise(function (res, rej) {
      var t = 0, last = now();
      function step(n) {
        if (my !== gen) { travelling = false; vel = 0; rej(ABORT); return; }
        if (!paused) t = Math.min(1, t + (n - last) / dur);
        last = n;
        var e = ease(t), u = 1 - e;
        var nx = u * u * sx + 2 * u * e * cx + e * e * tx, ny = u * u * sy + 2 * u * e * cy + e * e * ty;
        vel = paused ? 0 : nx - pos.x;
        pos.x = nx; pos.y = ny;
        if (t < 1) requestAnimationFrame(step); else { travelling = false; vel = 0; res(); }
      }
      requestAnimationFrame(step);
    });
  }

  function waitFor(target) {
    var my = gen, until = now() + WAIT_MS;
    return new Promise(function (res, rej) {
      (function look() {
        if (my !== gen) { rej(ABORT); return; }
        var el = typeof target === "function" ? target() : document.querySelector(target);
        if (el && el.getClientRects().length) { res(el); return; }
        if (now() > until) { res(null); return; }
        setTimeout(look, 100);
      })();
    });
  }

  function reveal(el) {
    var r = el.getBoundingClientRect();
    if (r.top >= 72 && r.bottom <= innerHeight - 72) return Promise.resolve();
    selfUntil = now() + 1400;
    el.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" });
    return sleep(reduced() ? 60 : 700);
  }

  function aim(el) {
    var r = el.getBoundingClientRect();
    return {
      x: r.left + Math.min(r.width / 2, Math.max(22, r.width * 0.22)),
      y: r.top + Math.min(r.height / 2, 26)
    };
  }

  function press() {
    cursor.classList.add("is-press");
    ripple.style.transform = "translate3d(" + pos.x.toFixed(1) + "px," + pos.y.toFixed(1) + "px,0)";
    ripple.classList.remove("is-on");
    void ripple.offsetWidth; // restart the ripple animation
    ripple.classList.add("is-on");
    return sleep(T.press).then(function () { cursor.classList.remove("is-press"); });
  }

  /* --- one step: find, travel, act, dwell --- */

  function perform(step) {
    var el;
    return whilePaused().then(function () { return waitFor(step.target); }).then(function (found) {
      if (!found) return null; // its target never appeared: skip the step
      el = found;
      return reveal(el).then(function () {
        say(typeof step.say === "function" ? step.say(el) : step.say);
        var p = aim(el);
        return travel(p.x, p.y);
      }).then(function () {
        if (!el.isConnected) return null;
        marked = el;
        markHold = step.act === "hover" || (step.act === "click" && isDenied(el));
        if (step.act !== "click") return sleep(step.dwell || T.dwell);
        if (isDenied(el)) {
          say("That is " + label(el) + ". The decision is yours, so I leave it.");
          return sleep(step.dwell || T.dwell);
        }
        return whilePaused().then(press).then(function () {
          activate(el);
          return sleep(step.dwell || 900);
        });
      }).then(function () { marked = null; });
    });
  }

  function kick() {
    if (running || !enabled || !queue.length) return;
    running = true;
    var my = gen;
    (function next() {
      if (my !== gen || !enabled || !queue.length) {
        if (my === gen) { running = false; captionOn = false; idleSince = now(); }
        return;
      }
      perform(queue.shift()).then(next, function (e) {
        if (e !== ABORT) console.error(e);
        marked = null;
        if (my === gen) next(); else if (!queue.length) running = false;
      });
    })();
  }

  /* --- deciding what to do next from successive states --- */

  function tab(view, text) {
    return { target: "nav.tabs a[data-view='" + view + "']", act: "click", say: text, dwell: 700 };
  }
  function top(leads) {
    return (leads || []).reduce(function (best, l) { return !best || Number(l.score) > Number(best.score) ? l : best; }, null);
  }
  function rowFor(login) { return "button.row[data-open='" + CSS.escape(String(login)) + "']"; }

  function handoffStep(hs) {
    var last = hs && hs[hs.length - 1];
    var text = last ? cap(last.from) + " just handed a lead to " + cap(last.to) : "Watching the line work";
    return { target: function () { return document.querySelector(".floor-log li") || document.querySelector(".floor-headline"); }, act: "look", say: text, dwell: 1800 };
  }

  function openLeadSteps(data) {
    var l = top(data.leads), name = l.name || l.login;
    var steps = [
      tab("leads", data.leads.length + " leads are in. Going to Leads"),
      { target: rowFor(l.login), act: "click", say: "Opening " + name + ", the strongest lead, to read what they wrote" },
      { target: function () { return document.querySelector("#detail .signal blockquote") || document.querySelector("#detail .signal"); }, act: "look", say: "Reading " + name + "'s own words: this is why they matched", dwell: 2600 }
    ];
    if (l.draft_status === "pending") {
      steps.push({ target: "#detail [data-act='approve']", act: "hover", say: "The draft is ready. Approving it is your call, so I leave it for you", dwell: 2200 });
    }
    steps.push(tab("map", "Opening the Map to see who else shares this pain"),
      { target: "#mount-map", act: "look", say: "Each pain, the people who voiced it, and where they wrote", dwell: 2200 });
    return steps;
  }

  function inboxSteps(inbox) {
    var it = inbox[0], name = it.name || it.login;
    return [
      tab("floor", inbox.length === 1 ? "One lead is waiting on you. Going to the Floor" : inbox.length + " leads are waiting on you. Going to the Floor"),
      { target: ".floor-inbox", act: "look", say: "These are held for your judgment, with the reason for each", dwell: 1600 },
      { target: ".floor-inbox-btn", act: "click", say: "Opening " + name + " so you can see why it was held" },
      { target: "#detail .signal", act: "look", say: "Here is what " + name + " wrote. The decision stays with you", dwell: 2200 }
    ];
  }

  function trustSteps(level) {
    return [
      tab("floor", "Autonomy changed. Going to the trust ladder"),
      { target: ".floor-trust .floor-level", act: "look", say: "The line now runs at " + level, dwell: 1600 },
      { target: ".floor-trust .floor-control button", act: "hover", say: "Raising autonomy is your decision, so I only point at it", dwell: 2000 }
    ];
  }

  function patrolSteps() {
    var cur = document.querySelector("nav.tabs a[aria-current='page']");
    var at = PATROL.indexOf(cur ? cur.getAttribute("data-view") : "");
    var v = PATROL[(at + 1) % PATROL.length];
    return [tab(v, PATROL_SAY[v]), { target: ".view-head h1", act: "look", say: PATROL_SAY[v], dwell: 2400 }];
  }

  function replace(steps) { gen++; running = false; marked = null; queue = steps.slice(0, QUEUE_CAP); }
  function push(steps) { queue = queue.concat(steps).slice(0, QUEUE_CAP); }

  function plan(data) {
    var was = seen || { status: {}, leads: [], floor: {} };
    var first = !seen;
    seen = data;
    var st = data.status || {}, fl = data.floor || {}, wfl = was.floor || {};
    var leads = data.leads || [], hs = fl.handoffs || [], inbox = fl.inbox || [];
    var level = fl.trust && fl.trust.level, wasLevel = wfl.trust && wfl.trust.level;

    if (st.error && st.error !== (was.status || {}).error) {
      replace([tab("floor", "The run stopped. Going to see where"),
        { target: function () { return document.querySelector(".floor-stopped") || document.querySelector(".floor-headline"); }, act: "look", say: "This is where the line stopped", dwell: 2400 }]);
      return;
    }
    if (st.running && !(was.status || {}).running) {
      replace([tab("floor", "A run started. Going to the Floor to watch the line work"), handoffStep(hs)]);
      return;
    }
    if (st.running && hs.length > (wfl.handoffs || []).length && !queue.length) push([handoffStep(hs)]);

    var t = top(leads), wt = top(was.leads);
    if (t && (!wt || t.login !== wt.login)) push(openLeadSteps(data));
    if (inbox.length > (first ? 0 : (wfl.inbox || []).length)) push(inboxSteps(inbox));
    if (!first && level && wasLevel && level !== wasLevel) push(trustSteps(level));
    if (first && !leads.length && !st.running && !data.icp) {
      push([{ target: "form#intake button", act: "hover", say: "Describe your product here. Starting a run is yours to do, so I wait", dwell: 2400 }]);
    }
  }

  /* --- the human always wins --- */

  function pause() {
    clearTimeout(resumeTimer);
    resumeTimer = setTimeout(function () { resumeNow(false); }, IDLE_RESUME_MS);
    if (paused) return;
    paused = true;
    live.textContent = "You have the controls. The pilot resumes after 8 seconds of stillness.";
    paint();
  }

  function resumeNow(byButton) {
    clearTimeout(resumeTimer);
    if (!paused) return;
    paused = false;
    moved = 0;
    if (byButton) graceUntil = now() + 1500; // let the hand leave the Resume button
    paint();
    kick();
  }

  function human(e) {
    if (!e.isTrusted || !enabled || !built) return;
    if (e.type === "scroll" && now() < selfUntil) return;
    if (e.type === "pointermove") {
      if (now() < graceUntil) return;
      if (!paused) { moved += Math.abs(e.movementX || 0) + Math.abs(e.movementY || 0); if (moved < 6) return; }
    }
    pause();
  }

  ["pointermove", "pointerdown", "keydown", "touchstart", "wheel", "scroll"].forEach(function (type) {
    addEventListener(type, human, { capture: true, passive: true });
  });

  setInterval(function () {
    if (!enabled || paused || running || document.hidden || !latest || !built) return;
    if (now() - idleSince < PATROL_AFTER_MS) return;
    queue = patrolSteps();
    kick();
  }, 1000);

  /* --- public API --- */

  var api = {
    update: function (data) {
      if (!data || typeof data !== "object") return;
      latest = data;
      build();
      if (!enabled) { seen = data; return; }
      plan(data);
      kick();
    },
    enable: function () {
      enabled = true;
      store(true);
      build();
      paused = false;
      seen = null;
      idleSince = now();
      paint();
      if (latest) { plan(latest); kick(); }
    },
    disable: function () {
      enabled = false;
      store(false);
      gen++;
      queue = []; running = false; paused = false; marked = null; captionOn = false;
      clearTimeout(resumeTimer);
      paint();
    },
    isEnabled: function () { return enabled; },
    isDenied: isDenied
  };

  enabled = stored();
  if (document.body) build(); else document.addEventListener("DOMContentLoaded", build);
  idleSince = now();
  window.EarshotPilot = api;
})();
