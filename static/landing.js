// The landing page: an explorable map of one run, a miniature of the answer screen, and motion.
// Without this script every section is visible and still, and the map reads as an ordered list.
(() => {
  const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const WIDE = matchMedia("(min-width: 70rem)");
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const G = window.gsap;
  if (!RM) document.documentElement.classList.add("motion");

  // --- the steps: every number is from today's run on flexprice.io ---
  const STEP = {
    site: ["Start", "Your website", "You paste one link. That is all Earshot asks for.", "flexprice.io"],
    planner: ["Step 1", "Planner", "Reads your site, names who buys and where they write.", "6 sites chosen to listen on"],
    trackers: ["Step 2", "Issue trackers", "Reads public issues on your repo and your open-source rivals.", "463 public posts read across 3 trackers plus forum posts"],
    forums: ["Step 2", "Forums and review sites", "Searches forums and review sites for the same complaints.", "Their posts are part of the 463 read"],
    match: ["Step 3", "Match by meaning", "Compares each post with the pains by meaning, not by words.", "39 people found describing the problem"],
    qualifier: ["Step 4", "Qualifier", "Weighs each person and drops anyone who is not a fit.", "19 dropped as not a fit; 6 kept"],
    enricher: ["Step 5", "Enricher", "Looks up a work email, or says there is none.", ""],
    writer: ["Step 6", "Writer", "Drafts a short message from what the person wrote.", "6 messages written"],
    reviewer: ["Step 7", "Reviewer", "Checks every claim in a draft against what the person wrote.", "A second model checks every message and the Writer gets one rewrite"],
    you: ["Step 8", "You: yes or no", "Nothing goes out until you say yes.", "Nothing is sent to the person in this demo"],
    inbox: ["Step 9", "Test inbox", "An approved message lands in a test inbox, not with the person.", ""],
    meter: ["Under every step", "Every step is metered", "Each step is counted as usage against a credit budget.", ""],
    graph: ["Under every step", "Everything is written to a graph", "People, posts, pains and your decisions, linked.", ""],
  };
  const TOOL = {
    claude: ["Claude", "Reads the site, weighs each person and writes each draft."],
    tavily: ["Tavily", "Reads your site and searches forums and review sites."],
    github: ["GitHub", "Public issues, where engineers describe the problem."],
    moss: ["Moss", "Matches posts to pains by meaning, not keywords."],
    hunter: ["Hunter", "Looks up a work email for the people kept."],
    subq: ["SubQ", "The second model that checks every claim in a draft."],
    resend: ["Resend", "Delivers approved messages to the test inbox."],
    flexprice: ["Flexprice", "Meters every step of the run as usage."],
    kuzu: ["Kùzu", "The graph that holds people, posts, pains and decisions."],
    band: ["Band", "Four agents planned, built and reviewed a rule."],
    claudecode: ["Claude Code", "Wrote and checked the code with the builder."],
  };
  const ORDER = Object.keys(STEP);
  const EDGES = [["site", "planner"], ["planner", "trackers"], ["planner", "forums"], ["trackers", "match"], ["forums", "match"], ["match", "qualifier"],
    ["qualifier", "enricher"], ["enricher", "writer"], ["writer", "reviewer"], ["reviewer", "you"], ["you", "inbox"]];
  const RAILS = {meter: "[data-meter]", graph: "[data-graph]"};

  const map = $("#map"), flow = $("#flow"), svg = $("#map-lines"), detail = $("#detail");
  const NS = "http://www.w3.org/2000/svg";
  const li = id => $(`.node[data-id="${id}"]`, flow).parentElement;
  const mk = (tag, cls) => { const e = document.createElementNS(NS, tag); if (cls) e.setAttribute("class", cls); svg.append(e); return e; };
  const lines = {};  // key -> {base, on}
  EDGES.forEach(([a, b]) => lines[a + ">" + b] = {base: mk("path"), on: mk("path", "on")});
  lines.loop = {base: mk("path"), on: mk("path", "on")};
  const ticks = ORDER.flatMap(id => Object.keys(RAILS).filter(r => $(`.node[data-id="${id}"]`).matches(RAILS[r])).map(r => ({id, r, el: mk("line", "tick")})));
  const dot = mk("circle", "dot"); dot.setAttribute("r", 5); dot.style.opacity = 0;

  let sel = "site", lit = new Set(), extra = null, tool = null;

  function box(el) { const m = map.getBoundingClientRect(), r = el.getBoundingClientRect(); return {l: r.left - m.left, t: r.top - m.top, r: r.right - m.left, b: r.bottom - m.top, w: r.width, h: r.height}; }
  function draw() {
    const wide = WIDE.matches;
    for (const [a, b] of EDGES) {
      const A = box(li(a)), B = box(li(b));
      let d;
      if (wide) { const x1 = A.r, y1 = A.t + A.h / 2, x2 = B.l, y2 = B.t + B.h / 2, mx = (x1 + x2) / 2; d = `M${x1} ${y1}C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`; }
      else { const x1 = A.l + A.w / 2, y1 = A.b, x2 = B.l + B.w / 2, y2 = B.t, my = (y1 + y2) / 2; d = `M${x1} ${y1}C${x1} ${my} ${x2} ${my} ${x2} ${y2}`; }
      setD(a + ">" + b, d);
    }
    const W = box(li("writer")), R = box(li("reviewer"));
    setD("loop", wide ? `M${R.l + R.w / 2} ${R.t}C${R.l + R.w / 2} ${R.t - 44} ${W.l + W.w / 2} ${W.t - 44} ${W.l + W.w / 2} ${W.t}`
      : `M${R.r} ${R.t + R.h / 2}C${R.r + 36} ${R.t + R.h / 2} ${W.r + 36} ${W.t + W.h / 2} ${W.r} ${W.t + W.h / 2}`);
    for (const k of ticks) {
      k.el.style.display = wide ? "" : "none";
      if (!wide) continue;
      const N = box(li(k.id)), T = box(li(k.r)), x = N.l + N.w / 2 + (k.r === "meter" ? -5 : 5);
      k.el.setAttribute("x1", x); k.el.setAttribute("x2", x); k.el.setAttribute("y1", N.b); k.el.setAttribute("y2", T.t);
    }
    paint();
  }
  function setD(key, d) { const L = lines[key]; L.base.setAttribute("d", d); L.on.setAttribute("d", d); const n = L.on.getTotalLength(); L.on.style.strokeDasharray = n; L.len = n; }
  function paint() {
    for (const key in lines) { const L = lines[key]; L.on.style.strokeDashoffset = lit.has(key) || extra === key ? 0 : L.len; }
    for (const k of ticks) k.el.classList.toggle("lit", sel === k.r);
  }

  // The path from the start up to a node: its ancestors along the edges.
  function pathTo(id) {
    const on = new Set([id]);
    if (RAILS[id]) { $$(RAILS[id], flow).forEach(b => on.add(b.dataset.id)); return {nodes: on, edges: new Set()}; }
    for (let grew = true; grew;) { grew = false; for (const [a, b] of EDGES) if (on.has(b) && !on.has(a)) { on.add(a); grew = true; } }
    const edges = new Set(EDGES.filter(([a, b]) => on.has(a) && on.has(b)).map(([a, b]) => a + ">" + b));
    if (["reviewer", "you", "inbox"].includes(id)) edges.add("loop");
    return {nodes: on, edges};
  }

  function chipsHtml(id) { return $$(".chips .chip", li(id)).map(c => c.outerHTML).join(""); }
  function fill(k, t, s, n, chips) { $("#d-k").textContent = k; $("#d-t").textContent = t; $("#d-s").textContent = s; $("#d-n").textContent = n; $("#d-c").innerHTML = chips; }

  function select(id, o = {}) {
    if (!STEP[id]) return;
    if (!o.play && !o.preview) stop();
    if (!o.preview) { sel = id; setTool(null, true); }
    const p = pathTo(id);
    lit = p.edges;
    $$(".flow > .nd, .flow > .rail").forEach(el => { const nid = $(".node", el).dataset.id; el.classList.toggle("is-on", nid === id); el.classList.toggle("is-path", p.nodes.has(nid) && nid !== id); });
    $$(".node", flow).forEach(b => b.dataset.id === id ? b.setAttribute("aria-current", "step") : b.removeAttribute("aria-current"));
    const [k, t, s, n] = STEP[id];
    fill(k, t, s, n, chipsHtml(id));
    placeDetail(id);
    draw();
    if (o.hash) history.replaceState(null, "", "#how-" + id);
  }
  // Narrow screens: the panel sits right under the chosen step.
  function placeDetail(id) {
    const want = WIDE.matches ? null : li(id === "trackers" ? "forums" : id);
    if (want) { if (want.nextElementSibling !== detail) want.after(detail); }
    else if (flow.lastElementChild !== detail) flow.append(detail);
  }

  function setTool(name, quiet) {
    tool = name === tool ? null : name;
    $$(".chip").forEach(c => c.setAttribute("aria-pressed", c.dataset.tool === tool));
    $$(".flow > .nd, .flow > .rail").forEach(el => el.classList.toggle("is-tool", !!tool && !!$(`.chip[data-tool="${tool}"]`, el)));
    if (quiet) return;
    if (!tool) return select(sel);
    const [t, line] = TOOL[tool];
    if (tool === "band" || tool === "claudecode") { $("#built-line").textContent = line; return; }
    const where = $$(".flow > .nd, .flow > .rail").filter(el => $(`.chip[data-tool="${tool}"]`, el)).map(el => STEP[$(".node", el).dataset.id][1]);
    fill("Tool", t, line, "Powers: " + where.join(", "), "");
  }

  // --- input: mouse, keyboard, deep links ---
  flow.addEventListener("click", e => {
    const c = e.target.closest(".chip"); if (c) { stop(); return setTool(c.dataset.tool); }
    const n = e.target.closest(".node"); if (n) select(n.dataset.id, {hash: true});
  });
  $(".built").addEventListener("click", e => { const c = e.target.closest(".chip"); if (c) setTool(c.dataset.tool); });
  flow.addEventListener("keydown", e => {
    const n = e.target.closest(".node"); if (!n) return;
    const i = ORDER.indexOf(n.dataset.id), step = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[e.key];
    const j = step ? i + step : e.key === "Home" ? 0 : e.key === "End" ? ORDER.length - 1 : -1;
    if (j < 0 || j >= ORDER.length || j === i) return;
    e.preventDefault();
    select(ORDER[j], {hash: true});
    $(`.node[data-id="${ORDER[j]}"]`).focus();
  });
  if (matchMedia("(hover: hover)").matches) {
    flow.addEventListener("pointerover", e => { const el = e.target.closest(".nd, .rail"); if (el && !playing) select($(".node", el).dataset.id, {preview: true}); });
    flow.addEventListener("pointerleave", () => { if (!playing && !tool) select(sel, {preview: true}); });
  }
  const fromHash = () => { const m = location.hash.match(/^#how-(\w+)$/); if (m && STEP[m[1]]) { select(m[1]); return true; } return false; };
  addEventListener("hashchange", fromHash);

  // --- play the run: a dot carries one post from your site to the inbox ---
  const SEQ = [["site", "planner"], ["planner", "trackers"], ["trackers", "match"], ["match", "qualifier"], ["qualifier", "enricher"], ["enricher", "writer"],
    ["writer", "reviewer"], ["loop", "writer"], ["writer", "reviewer"], ["reviewer", "you"], ["you", "inbox"]];
  const FUNNEL = {site: [1, "website"], trackers: [463, "posts read"], match: [39, "people"], qualifier: [6, "kept"], writer: [6, "messages"]};
  const TRAVEL = RM ? 1 : 700, DWELL = RM ? 1100 : 650;
  const playBtn = $("#play"), fN = $("#funnel-n"), fT = $("#funnel-t");
  let playing = false, segI = 0, segT = 0, arrived = false, last = 0, done = true;
  function funnel(id) {
    const f = FUNNEL[id]; if (!f) return;
    fT.textContent = f[1];
    if (G && !RM) { const o = {v: +fN.textContent || 0}; G.to(o, {v: f[0], duration: 0.6, ease: "power2.out", onUpdate: () => fN.textContent = Math.round(o.v)}); }
    else fN.textContent = f[0];
  }
  function setPlaying(on) { playing = on; playBtn.setAttribute("aria-pressed", on); $(".play-t", playBtn).textContent = on ? "Pause" : done ? "Play the run" : "Resume"; }
  function play() {
    if (done) { segI = 0; segT = 0; arrived = false; done = false; select("site", {play: true}); funnel("site"); }
    setPlaying(true); dot.style.opacity = RM ? 0 : 1; last = performance.now(); requestAnimationFrame(tick);
  }
  function stop() { if (!playing && done) return; done = true; setPlaying(false); dot.style.opacity = 0; extra = null; fN.textContent = FUNNEL.trackers[0]; fT.textContent = "posts read"; }
  function tick(now) {
    if (!playing) return;
    if (segT === 0) { const [a0, b0] = SEQ[segI]; extra = a0 === "loop" ? "loop" : a0 + ">" + b0; paint(); }
    segT += Math.min(64, now - last); last = now;
    const [a, b] = SEQ[segI], key = a === "loop" ? "loop" : a + ">" + b, L = lines[key];
    const k = Math.min(1, segT / TRAVEL), e = 1 - Math.pow(1 - k, 3), pt = L.on.getPointAtLength(e * L.len);
    dot.setAttribute("cx", pt.x); dot.setAttribute("cy", pt.y);
    if (k >= 1 && !arrived) { arrived = true; extra = null; select(b, {play: true}); funnel(b); }
    if (segT >= TRAVEL + DWELL) {
      segI++; segT = 0; arrived = false;
      if (segI >= SEQ.length) { done = true; setPlaying(false); dot.style.opacity = 0; return; }
    }
    requestAnimationFrame(tick);
  }
  playBtn.addEventListener("click", () => playing ? (setPlaying(false)) : play());

  // --- the miniature: one story row open at a time, as in the app ---
  $("#mini-story").addEventListener("click", e => {
    const b = e.target.closest(".st-btn"); if (!b) return;
    const open = b.getAttribute("aria-expanded") !== "true";
    $$("#mini-story .st").forEach(st => { const on = open && st.contains(b); st.classList.toggle("is-open", on); $(".st-btn", st).setAttribute("aria-expanded", on); $(".st-more", st).inert = !on; });
  });

  // --- motion ---
  new ResizeObserver(() => { placeDetail(sel); draw(); }).observe(map);
  document.fonts && document.fonts.ready.then(draw);
  const deep = fromHash();
  if (!deep) select("site");
  if (deep) requestAnimationFrame(() => map.scrollIntoView({block: "center"}));

  $$(".flow > li").forEach((el, i) => el.style.setProperty("--i", i));
  $$(".rows").forEach(ul => [...ul.children].forEach((el, i) => el.style.setProperty("--i", i)));
  const countUp = sec => $$(".logos .num, .r-t .num, .r-n .num", sec).forEach(el => {
    const to = +(el.dataset.to || el.textContent); if (!G || RM || !to) return;
    if (el._tw) el._tw.kill();
    const o = {v: 0}; el._tw = G.to(o, {v: to, duration: 1.2, ease: "power2.out", onUpdate: () => el.textContent = Math.round(o.v)});
  });
  let autoplayed = deep;
  const enter = sec => {
    sec.classList.add("is-in"); countUp(sec);
    setTimeout(() => flow.classList.add("settled"), 1600);
    if (sec.id === "how" && !autoplayed && !RM) { autoplayed = true; setTimeout(() => { if (done && sel === "site") play(); }, 900); }
  };
  const secs = $$(".sec");
  if (RM) secs.forEach(s => s.classList.add("is-in"));
  else if (window.ScrollTrigger && G) { G.registerPlugin(ScrollTrigger); secs.forEach(s => ScrollTrigger.create({trigger: s, start: "top 75%", once: true, onEnter: () => enter(s)})); }
  else if ("IntersectionObserver" in window) { const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { enter(e.target); io.unobserve(e.target); } }), {threshold: 0.2}); secs.forEach(s => io.observe(s)); }
  else secs.forEach(enter);

  // The hero arrives: nav drops in, headline rises line by line, the italic phrase last, then the pill.
  if (G && !RM) {
    G.timeline({defaults: {ease: "power4.out"}})
      .from(".nav", {y: -48, opacity: 0, duration: 0.9})
      .from(".hero .label", {y: 12, opacity: 0, duration: 0.6}, 0.1)
      .from(".hero-title .ln:first-child > span", {yPercent: 110, duration: 1.1}, 0.2)
      .from(".hero-title .ln:last-child > span", {yPercent: 110, duration: 1.1}, 0.55)
      .from(".hero-line", {y: 16, opacity: 0, duration: 0.8}, 0.85)
      .from(".hero .btn", {scale: 0.85, opacity: 0, duration: 0.8, ease: "power3.out"}, 1)
      .from(".hero .hint", {opacity: 0, duration: 0.6}, 1.2);
  }


  // --- live numbers: swap today's hard-coded run for the server's latest finished run; any miss keeps the fallback ---
  const vals = f => Array.isArray(f) ? f : (f && f.values) || [];
  const STOP = /^(to|the|a|an|of|in|for|with|and|or|our|we|is|are|on|at|by|but)$/i, cap = t => t ? t[0].toUpperCase() + t.slice(1) : t;
  function buyer(role) {  // same cut as the app's buyer(): at most six words, the phrase after the noun in italic
    let w = String(role || "").replace(/\s*\(.*?\)/g, "").replace(/(\w+)\/[\w-]+/g, "$1").split(/\s+(?:at|who|with|for|in)\s+|,/i)[0].trim().split(/\s+/).slice(0, 6);
    while (w.length > 2 && STOP.test(w.at(-1))) w.pop();
    const i = w.findIndex((x, k) => k > 0 && /ing$/i.test(x)), at = i > 0 ? i : Math.max(1, w.length - 1);
    return [cap(w.slice(0, at).join(" ")), w.slice(at).join(" ")];
  }
  const setN = (el, n) => { if (el && Number.isFinite(n)) { el.dataset.to = n; el.textContent = n; } };
  const setT = (el, t) => { if (el && t) el.textContent = t; };
  function applyLive(d) {
    const log = (d.status && d.status.log) || [], i = d.icp, leads = d.leads;
    const lm = re => log.map(l => l.match(re)).find(Boolean) || null;
    let site = ""; try { const u = lm(/^Planner: reading (\S+)/); site = u ? new URL(u[1]).hostname.replace(/^www\./, "") : ""; } catch (e) {}
    const scan = lm(/(\d+) of (\d+) issues describe a target pain, from (\d+) people/), kept = lm(/(\d+) leads kept/), dropped = lm(/dropped (\d+) people whose issue/);
    const trackers = lm(/watch (\d+) public issue trackers/);
    const doms = vals(i.channels).map(c => c.domain).filter(Boolean);
    const posts = scan ? +scan[2] : NaN, people = scan ? +scan[3] : NaN, keptN = kept ? +kept[1] : NaN, dropN = dropped ? +dropped[1] : NaN;
    const msgs = leads.filter(l => l.draft_status !== "no_author").length, sites = doms.length;
    const [role, rest] = buyer(vals(i.personas)[0]);
    const sells = String(i.product || "").replace(/^[^:]{1,40}:\s*/, "").split(/\s+/).slice(0, 6).join(" ").replace(/[,;:.]$/, "");
    const ok = Number.isFinite;
    // map node details and the Play counter
    if (site) { STEP.site[3] = site; $(".node[data-id=site] .nd-s").textContent = site; $(".sub", $("#how")).innerHTML = `Pick any step, or play today&rsquo;s run on ${site}.`; }
    if (sites) STEP.planner[3] = `${sites} sites chosen to listen on`;
    if (ok(posts)) {
      STEP.trackers[3] = `${posts} public posts read across ${trackers ? trackers[1] : 3} trackers plus forum posts`; STEP.forums[3] = `Their posts are part of the ${posts} read`;
      FUNNEL.trackers[0] = posts; if (done) fN.textContent = posts;
    }
    if (ok(people)) { STEP.match[3] = `${people} people found describing the problem`; FUNNEL.match[0] = people; }
    if (ok(keptN)) FUNNEL.qualifier[0] = keptN;
    if (ok(keptN) && ok(dropN)) STEP.qualifier[3] = `${dropN} dropped as not a fit; ${keptN} kept`;
    STEP.writer[3] = `${msgs} messages written`; FUNNEL.writer[0] = msgs;
    // the miniature
    if (site) { $(".mini-bar").innerHTML = `Example: today&rsquo;s run on ${site}`; setT($("#mini-story .st:nth-child(1) .r-t em"), site); }
    if (rest) $(".mini-line").innerHTML = `${role.replace(/[&<]/g, "")} <em>${rest.replace(/[&<]/g, "")}</em>`;
    setN($(".logos .num"), people);
    if (doms.length) $(".logo-row").replaceChildren(...doms.slice(0, 6).map(x => Object.assign(document.createElement("li"), {textContent: x.replace(/^(www|news)\./, "")})));
    if (sites) setT($("#mini-story .st:nth-child(2) .r-t em"), `${sites} sites`);
    setN($("#mini-story .st:nth-child(2) .r-n .num"), posts);
    if (ok(people)) setT($("#mini-story .st:nth-child(3) .r-t em"), `${people} people`);
    if (ok(keptN)) setT($("#mini-story .st:nth-child(4) .r-t em"), keptN);
    if (ok(dropN)) { const t = $("#mini-story .st:nth-child(4) .r-n").firstChild; if (t && t.nodeType === 3) t.nodeValue = `${dropN} dropped as not a fit`; }
    setT($("#mini-story .st:nth-child(5) .r-t em"), `${msgs} ${msgs === 1 ? "message" : "messages"}`);
    if (sells) { const t = $("#mini-story .st:nth-child(1) .r-n").firstChild; if (t && t.nodeType === 3) t.nodeValue = cap(sells); }
    // counters already played start again from zero towards the live figure; the rest read it when they first play
    const ans = $("#answer.is-in"); if (ans) countUp(ans);
    if (!tool) select(sel, {preview: true});
  }
  (async () => {
    const ac = new AbortController(), t = setTimeout(() => ac.abort(), 4000);
    try {
      const r = await fetch("/api/state", {signal: ac.signal}); if (!r.ok) return;
      const d = await r.json();
      if (d && d.icp && d.leads && d.leads.length && d.status && d.status.running === false) applyLive(d);
    } catch (e) { /* offline or slow: the hard-coded run stays */ } finally { clearTimeout(t); }
  })();

  // Scroll position as a hairline under the nav.
  const bar = $(".nav-progress"); let queued = false;
  const prog = () => { queued = false; const h = document.documentElement.scrollHeight - innerHeight; bar.style.setProperty("--p", h > 0 ? Math.min(1, scrollY / h) : 0); };
  addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(prog); } }, {passive: true});
  prog();
})();
