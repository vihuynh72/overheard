// Every string from GitHub or the model goes through esc(): it is untrusted text.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const safeUrl = u => /^https?:\/\//.test(u || "") ? esc(u) : "#";
const $ = id => document.getElementById(id);
const EXT = `<svg class="icon" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3.5 8.5 8.5 3.5M4.5 3.5h4v4"/></svg>`;
const who = a => a === "rep" ? "you" : a;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
// Home is the customer; the other two are pages of their own. Old section names land on the nearest page.
const SECTIONS = {leads: "People", activity: "Activity"};
const MOVED = {floor: "home", profile: "home", map: "leads", pipeline: "leads", proof: "activity"};
const EMAIL = {valid: "verified", accept_all: "domain accepts all mail", invalid: "failed verification", webmail: "personal webmail", disposable: "disposable address", unknown: "unverified", pending: "verifying"};

const ui = {data: null, json: "", example: false, restart: false, selected: null, tier: "All", rejecting: false, desc: "", repo: "", target: "", error: "", detailKey: "", shown: "", open: {},
  head: "", ticked: new Set(), ledgerAll: false, entered: new Set()};

async function api(path, body) {
  const r = await fetch(path, body ? {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)} : {});
  if (!r.ok) {
    const d = (await r.json().catch(() => ({}))).detail;
    throw new Error(typeof d === "string" ? d : "The request was rejected. Try again.");
  }
  return r.json();
}
const view = () => { const h = location.hash.slice(1); return SECTIONS[h] ? h : "home"; };
const lead = () => ui.data.leads.find(l => l.login === ui.selected);
// A web lead whose only name is the site it was found on.
const nameOf = l => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(l.name || "") ? `Someone on ${l.name.replace(/^www\./i, "")}` : (l.name || l.login);
const tier = t => `<span class="tier" data-tier="${esc(t)}">${esc(t)}</span>`;
const steps = () => `<ol class="steps">${ui.data.status.log.map(l => `<li>${esc(l)}</li>`).join("")}</ol>`;
const fold = (key, title, line, body, short) => `<details class="fold" data-fold="${key}" ${(ui.open[key] ?? short) ? "open" : ""}><summary><h2>${title}</h2><span class="fold-line">${line}</span></summary><div class="fold-body">${body}</div></details>`;

// --- home --------------------------------------------------------------------------

function homeLine() {
  const {leads, status, floor} = ui.data;
  if (status.running) return status.log.at(-1) || "Starting.";
  if (status.error) return `The last run stopped: ${status.error}`;
  if (!leads.length) return "Resting. No one found yet.";
  const pending = leads.filter(l => l.draft_status === "pending").length;
  const written = leads.filter(l => ["Contacted", "Replied", "Meeting Booked"].includes(l.stage)).length;
  const needs = (floor.inbox || []).length;
  return [`Found ${plural(leads.length, "person", "people")} describing your problem.`,
    pending ? `${pending} ${pending === 1 ? "draft is" : "drafts are"} ready.` : `${written} written to.`,
    needs ? `${needs} ${needs === 1 ? "needs" : "need"} your decision.` : "Nothing needs you."].join(" ");
}

function homeStrip() {
  const {floor, billing} = ui.data, gates = floor.trust?.gates || [];
  const level = floor.trust?.level === "autopilot" ? "Earshot sends on its own" : "You approve every message";
  return `<span class="strip-say">${esc(ui.data.status.running ? "Running" : homeLine())}</span><a href="#activity">${level}</a>
    <a href="#activity">Trust checks <span class="num">${gates.filter(g => g.passed).length} of ${gates.length}</span> passed</a>
    <a href="#activity"><span class="num">${Math.floor(billing.credits)}</span> credits left</a>
    <button type="button" class="linkish" data-restart>Try another website</button>`;
}

// --- who the customer is, from the inferred profile and the people who proved it ---
const vals = f => Array.isArray(f) ? f : (f?.values || []);
const lowerFirst = t => /^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t;
const words = (t, n) => { const w = String(t).split(/\s+/); return w.length > n ? w.slice(0, n).join(" ") + "…" : t; };
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
const andList = a => a.length > 1 ? a.slice(0, -1).join(", ") + " and " + a.at(-1) : a[0] || "";
const cap = t => t ? t[0].toUpperCase() + t.slice(1) : t;
const noTag = t => String(t || "").replace(/^\s*\[[A-Za-z ]+\]:?\s*/, "");  // "[BUG]: x" reads as "x"
const initials = n => String(n || "?").replace(/^Someone on /, "").split(/[\s._-]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("") || "?";
const noAuthor = l => l.draft_status === "no_author";
const whoOf = l => noAuthor(l) ? `Someone on ${hostOf(l.url) || "the web"}` : nameOf(l);
const EAR = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><path d="M4 3.5h8a1.5 1.5 0 0 1 1.5 1.5v4.5A1.5 1.5 0 0 1 12 11H8l-3 2.5V11H4a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 4 3.5Z"/></svg>`;
// A face for every person: their GitHub avatar, else their initials; a post with no author gets a neutral speech mark.
const avatar = l => {
  if (noAuthor(l)) return `<span class="av av-none">${EAR}</span>`;
  const gh = l.login && !l.login.startsWith("web:");
  return `<span class="av"><span class="av-i" aria-hidden="true">${esc(initials(nameOf(l)))}</span>${gh ? `<img src="https://github.com/${encodeURIComponent(l.login)}.png?size=64" alt="" width="32" height="32" loading="lazy" onerror="this.remove()">` : ""}</span>`;
};
const favicon = d => /^[a-z0-9.-]+$/i.test(d || "") ? `<img class="fav" src="https://${d}/favicon.ico" alt="" width="16" height="16" loading="lazy" onerror="this.style.visibility='hidden'">` : "";
const when = d => { const t = new Date(d || ""); return isNaN(t) ? "" : t.toLocaleDateString(undefined, {month: "short", year: "numeric"}); };
// Entrance plays once per page, on the first paint with content, never on a poll.
const enter = k => ui.entered.has(k) ? "" : (ui.entered.add(k), " is-enter");
const stagger = i => ` style="--i:${Math.min(i, 9)}"`;

// The sentence and, beside it, the same sentence with its three load-bearing phrases (role, company kind, trigger) marked.
function customerLine(icp) {
  const role = vals(icp.personas)[0], kind = vals(icp.industries)[0], trig = vals(icp.triggers)[0];
  if (!role) { const t = icp.product ? `Working out who buys ${words(icp.product.split(":")[0], 6)}.` : "Working out who your customer is."; return {text: t, html: esc(t)}; }
  const parts = [cap(lowerFirst(role.replace(/\s*\(.*?\)/g, ""))), kind && !/\sat\s/i.test(role) ? kind.replace(/\s+compan(y|ies)$/i, "") : "", trig ? lowerFirst(trig) : ""];
  // Role and company kind carry the accent; the trigger stays in ink so the eye lands on two phrases, not a whole line.
  const build = (f, g) => `${f(parts[0])}${parts[1] ? ` at ${f(parts[1])} companies` : ""}${parts[2] ? `, ${g(parts[2])}` : ""}.`;
  return {text: build(x => x, x => x), html: build(x => `<em>${esc(x)}</em>`, esc)};
}

// Where the answer came from, in counts the run itself reported; a number it did not report is left out.
function provenance(d) {
  const m = (d.status.log || []).map(l => l.match(/(\d+) of \d+ issues describe a target pain, from (\d+) people/)).find(Boolean);
  const posts = m ? +m[1] : d.leads.reduce((n, l) => n + l.signals.length, 0), people = m ? +m[2] : d.leads.length;
  const sites = vals(d.icp?.channels).map(c => c.domain).filter(Boolean);
  if (!posts) return "";
  return `<p class="prov">From <span class="num">${posts}</span> public ${posts === 1 ? "post" : "posts"}${people ? ` by <span class="num">${people}</span> ${people === 1 ? "person" : "people"}` : ""}${sites.length ? ` on ${esc(andList(sites))}` : ""}.</p>`;
}

function customerFacts(icp, leads) {
  const sigs = leads.flatMap(l => l.signals.map(s => ({...s, login: l.login})));
  const voiced = p => new Set(sigs.filter(s => s.pain === p).map(s => s.login)).size;
  const all = [...new Set([...vals(icp.pains), ...vals(icp.learned_pains)])].map(p => [p, voiced(p)]).sort((a, b) => b[1] - a[1]);
  const pains = (all.some(p => p[1]) ? all.filter(p => p[1]) : all).slice(0, 4), most = Math.max(1, ...pains.map(p => p[1]));
  const tally = list => Object.entries(list.reduce((m, k) => (k && (m[k] = (m[k] || 0) + 1), m), {})).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const where = vals(icp.channels).length ? vals(icp.channels).slice(0, 3).map(c => ({d: c.domain, why: c.why})) : tally(sigs.map(s => hostOf(s.url))).map(([d]) => ({d}));
  // Real words only: the titles people gave their own posts, strongest match first, one per person.
  const seen = new Set(), say = [...sigs].sort((a, b) => (b.match || 0) - (a.match || 0)).filter(s => noTag(s.title) && !seen.has(s.login) && seen.add(s.login)).slice(0, 2);
  const by = login => leads.find(l => l.login === login);
  const fact = (cls, k, items) => `<div class="fact ${cls}"><h2 class="label">${k}</h2><ul>${items || `<li class="muted">Not known yet</li>`}</ul></div>`;
  return `<div class="facts-row">
    ${fact("f-pains", "What they struggle with", pains.map(([p, n], i) => `<li${stagger(i)}><span class="pain">${esc(p)}</span>
      <span class="voiced"><span class="voiced-bar" aria-hidden="true"><span style="--v:${(n / most).toFixed(3)}"></span></span><span class="num">${n ? plural(n, "person", "people") : "Not heard yet"}</span></span></li>`).join(""))}
    ${fact("f-where", "Where they write", where.map(({d, why}, i) => `<li${stagger(i)}><span class="site">${favicon(d)}${esc(d)}</span>${why ? `<span class="site-why">${esc(why)}</span>` : ""}</li>`).join(""))}
    ${fact("f-words", "In their own words", say.map((s, i) => { const l = by(s.login) || {}; return `<li class="quote"${stagger(i)}><blockquote>${esc(noTag(s.title))}</blockquote>
      <cite>${esc(whoOf(l))}<span class="num">${esc([s.repo || hostOf(s.url), when(s.created)].filter(Boolean).join(" · "))}</span></cite></li>`; }).join(""))}
  </div>`;
}

// In the example every row is inert: nothing in it belongs to this founder.
function proofPeople(leads, example) {
  if (!leads.length) return "";
  const top = [...leads].sort((a, b) => b.score - a.score).slice(0, 3);
  return `<section class="said" aria-labelledby="said-h"><h2 class="label" id="said-h">People who said it</h2><ul>
    ${top.map((l, i) => { const s = l.signals[0] || {}, inner = `${avatar(l)}<span class="said-main">
      <span class="said-who">${esc(whoOf(l))}${l.company ? ` <span class="muted">${esc(l.company)}</span>` : ""}${noAuthor(l) ? ` <span class="ev-only">evidence only</span>` : ""}</span>
      <span class="said-words">${esc(noTag(s.title) || l.reason)}</span>
      <span class="said-meta num">${esc([s.repo || hostOf(s.url), when(s.created)].filter(Boolean).join(" · "))}</span></span>
      <span class="said-score num" title="Score">${esc(l.score)}</span>`;
      return `<li${stagger(i)}>${example ? `<span class="said-row">${inner}</span>` : `<button type="button" class="said-row" data-open="${esc(l.login)}" data-go-leads>${inner}</button>`}
      <a class="said-src" href="${safeUrl(s.url)}" target="_blank" rel="noopener" aria-label="Open what ${esc(whoOf(l))} wrote">${EXT}</a></li>`; }).join("")}
    </ul>${example ? "" : `<a class="see-all" href="#leads">See all ${leads.length}</a>`}</section>`;
}

function homeCustomer(d, example) {
  const {icp, leads, status} = d;
  const line = status.error ? {text: `The last run stopped: ${status.error}`} : customerLine(icp || {}), head = line.text;
  const sub = example ? "" : `<p class="home-sub">This is who Earshot thinks your customer is, based on what real people wrote. Each name links to their post.</p>`;
  const banner = example ? `<p class="example-bar"><span>Example: Flexprice. Nothing here is yours yet, and nothing is sent.</span><button type="button" class="linkish" data-example-off>Use my own website</button></p>` : "";
  // The headline draws in once per new answer, never on a poll that repeats it.
  const fresh = head !== ui.head; ui.head = head;
  return `<div class="answer${enter(example ? "sample" : "home")}">${banner}${status.error ? "" : `<p class="label">Your customer</p>`}<h1 class="home-line${fresh ? " is-new" : ""}" id="home-line">${line.html || esc(head)}</h1>
    ${icp && !status.error ? provenance(d) : ""}${sub}
    ${icp ? customerFacts(icp, leads) : ""}${proofPeople(leads, example)}</div>`;
}

// Moment 1: one promise, one field, and what will happen next.
function intakeForm() {
  const back = ui.data.leads.length ? `<button type="button" class="linkish" data-restart-off>Back to your results</button>` : `<button type="button" class="linkish" data-example>See an example first</button>`;
  return `<form class="intake" id="intake" novalidate>
    <h1>Who is your customer?</h1>
    <p class="intake-lede">Paste your website. Earshot reads it, finds people who have described the problem you solve, and shows you who they are.</p>
    <label for="target">Your website</label>
    <div class="intake-row"><input type="text" id="target" placeholder="yourcompany.com" maxlength="200" autocomplete="url" inputmode="url" value="${esc(ui.target)}"
      ${ui.error ? `aria-invalid="true" aria-describedby="intake-err"` : ""}>
      <button class="btn">Find my customers</button></div>
    ${ui.error ? `<p class="error" id="intake-err" role="alert">${esc(ui.error)}</p>` : ""}
    <p class="hint">About two minutes. You don't need to do anything else.</p>
    <ol class="intake-steps">
      <li>Earshot reads your site to learn what you sell.</li>
      <li>It listens where your buyers write: GitHub, forums, review sites.</li>
      <li>It shows you who they are, with a message ready for each. You say yes or no.</li>
    </ol>
    ${back}
  </form>
  <details class="nosite" data-fold="manual" ${ui.open.manual ? "open" : ""}><summary>My product has no website</summary>
    <form class="intake-manual" id="intake-manual" novalidate>
      <div class="field"><label for="desc">What you sell, and who buys it</label><textarea id="desc" rows="5" maxlength="20000">${esc(ui.desc)}</textarea></div>
      <div class="field"><label for="repo">Public GitHub repository</label><input type="text" id="repo" placeholder="owner/name" value="${esc(ui.repo)}"></div>
      <div class="actions"><button class="btn">Find leads</button></div>
    </form></details>`;
}

// Moment 2: the run's log, translated into five steps a founder recognises.
const strip = l => l.replace(/^[A-Z][a-z]+( → [A-Z][a-z]+)?:\s*/, "");
const RUN = [
  {name: "Reading your website", done: /^Planner: inferring/},
  {name: "Working out who your customer is", done: /^Planner → Scout/},
  {name: "Listening where they write", done: /^Scout → Qualifier/,
    result: log => { const m = log.map(l => l.match(/(\d+) of (\d+) issues .* from (\d+) people/)).find(Boolean); return m && `${m[2]} posts read, ${m[3]} people found`; }},
  {name: "Checking each person really has this problem", done: /^(Enricher → Writer|Writer →)/,
    result: log => { const m = log.map(l => l.match(/^Enricher → Writer: (\d+) leads kept/)).find(Boolean); return m && `${plural(+m[1], "person", "people")} kept`; }},
  {name: "Writing a message to each from their own words", done: /^Done:/,
    result: log => { const m = log.map(l => l.match(/(\d+) messages drafted/)).find(Boolean); return m && plural(+m[1], "message", "messages") + " written"; }},
];
function runView() {
  const log = ui.data.status.log || [];
  const doneAt = RUN.map(s => log.findIndex(l => s.done.test(l)));
  const cur = doneAt.findIndex(i => i < 0);
  const sites = (log.find(l => /listening on /.test(l)) || "").split("listening on ")[1];
  return `<div class="run" aria-live="polite"><h1>Finding your customers${ui.target ? ` on <span class="run-site">${esc(hostOf(/^https?:/.test(ui.target) ? ui.target : "https://" + ui.target) || ui.target)}</span>` : ""}</h1>
    <ol class="checklist">${RUN.map((s, i) => {
      const state = doneAt[i] >= 0 ? "done" : i === cur ? "now" : "next";
      const tick = state === "done" && !ui.ticked.has(i) && ui.ticked.add(i);  // draw each tick once
      const note = state === "done" ? s.result?.(log) : state === "now" ? (i === 2 && sites ? `Listening on ${sites}` : strip(log.at(-1) || "Starting.")) : "";
      return `<li data-state="${state}"${state === "now" ? ` aria-current="step"` : ""}${tick ? ` class="is-new"` : ""}><svg class="check" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9"/><path d="m6 10.5 2.7 2.7L14.2 7.5"/></svg><span class="check-name">${s.name}<span class="visually-hidden">${state === "done" ? ", done" : state === "now" ? ", in progress" : ""}</span></span>${note ? `<span class="check-note">${esc(note)}</span>` : ""}</li>`;
    }).join("")}</ol>
    <p class="hint">This takes about two minutes. You can leave this tab open.</p></div>`;
}
function failedView() {
  const err = String(ui.data.status.error || "").replace(/^[A-Za-z]+Error:\s*/, "");
  const decline = /not a fit/i.test(err);
  return `<div class="run" role="alert"><h1>${decline ? "Earshot is the wrong tool for this product" : "That run stopped before it finished"}</h1>
    <p class="intake-lede">${decline ? `We would rather tell you now than send you the wrong people. ${esc(err.replace(/^Earshot is not a fit for this product:\s*/i, "The reason: "))}` : esc(err)}</p>
    <div class="actions"><button type="button" class="btn" data-restart>${decline ? "Try another website" : "Try again"}</button></div></div>`;
}

function homeMode() {
  const {leads, status} = ui.data;
  if (status.running) return "running";
  if (ui.example) return "example";
  if (ui.restart) return "fresh";
  if (!leads.length) return status.error ? "failed" : "fresh";
  return "home";
}

function renderHome() {
  const mode = homeMode(), slot = $("home-top");
  document.body.classList.toggle("is-fresh", mode !== "home");
  document.body.dataset.mode = mode;
  if (mode === "fresh") {
    // Rebuild the form only when it is not being typed in.
    if (!slot.querySelector("#intake") || !slot.contains(document.activeElement)) slot.innerHTML = intakeForm();
  } else slot.innerHTML = mode === "running" ? runView() : mode === "failed" ? failedView() : homeCustomer(mode === "example" ? SAMPLE : ui.data, mode === "example");
  $("home-strip").innerHTML = mode === "home" ? homeStrip() : "";
  if (mode !== "running") ui.ticked.clear();
  const ask = document.querySelector("body > .ask");
  if (ask) $("ask-slot").append(ask);  // the card lives beside the answer, not over it
}

// A fixed picture of a finished Flexprice run, shown before anything is run. Links search the real trackers; nothing is invented about the people beyond their public titles.
const issueSearch = (repo, q) => `https://github.com/${repo}/issues?q=${encodeURIComponent(q)}`;
const SAMPLE = {status: {running: false, log: []},
  icp: {personas: ["Backend engineers building billing"], industries: ["AI-native SaaS"], triggers: ["launching or migrating to usage-based or credit-based pricing"],
    pains: ["Stripe metered billing doesn't support our credit-based pricing", "Our home-grown usage billing keeps producing invoice mismatches", "How do I meter LLM tokens per customer"],
    channels: [{domain: "github.com"}, {domain: "news.ycombinator.com"}, {domain: "reddit.com"}],
    learned_pains: ["No invoice is generated for billing periods where the charge is $0", "Coupon discounts don't carry over to the Stripe invoice lines"]},
  leads: [
    {login: "deef", name: "deef", company: "", score: 3, signals: [{title: "[BUG]: Invoice not being generated when cost is 0", url: issueSearch("getlago/lago", "Invoice not being generated when cost is 0"), repo: "getlago/lago"}]},
    {login: "superphao4", name: "superphao4", company: "", score: 2, reason: "Opened billing issues on getlago/lago", signals: [{title: "", url: issueSearch("getlago/lago", "author:superphao4"), repo: "getlago/lago"}]},
    {login: "derekperkins", name: "Derek Perkins", company: "Nozzle", score: 1, signals: [{title: "[FEAT]: invoice approvals", url: issueSearch("getlago/lago", "invoice approvals"), repo: "getlago/lago"}]},
  ]};

// --- sections ------------------------------------------------------------------------

function peopleView() {
  const {leads, status} = ui.data;
  const found = leads.length, written = leads.filter(l => ["Contacted", "Replied", "Meeting Booked"].includes(l.stage)).length;
  const replied = leads.filter(l => ["Replied", "Meeting Booked"].includes(l.stage)).length;
  const head = `<p class="funnel num" id="funnel">${found} found · ${written} written to · ${replied} replied</p>`;
  if (!found) return head + (status.running ? steps() : `<p class="empty">No one yet.</p>`);
  if (lead()) return head + `<button type="button" class="back" data-back>${backIcon} Everyone</button><div class="detail" id="detail"></div>`;
  const filter = found > 12;
  const shown = leads.filter(l => !filter || ui.tier === "All" || l.tier === ui.tier);
  return head + (filter ? `<div class="seg" role="group" aria-label="Filter by tier">${["All", "A", "B", "C"].map(t => `<button type="button" data-tier-filter="${t}" aria-pressed="${ui.tier === t}">${t}</button>`).join("")}</div>` : "") +
    `<ul class="people${enter("leads")}">${shown.map((l, i) => `<li${stagger(i)}><button type="button" class="row" data-open="${esc(l.login)}">
      ${avatar(l)}
      <span class="who">${esc(whoOf(l))}<small>${noAuthor(l) ? "evidence only" : esc([l.role !== "unknown" && l.role, l.company].filter(Boolean).join(" · ") || (l.login.startsWith("web:") ? "" : "@" + l.login))}</small></span>
      <span class="why">${esc(l.reason)}</span>
      <span class="grade">${meter(l)}<span class="stage">${esc(l.stage)}</span></span></button></li>`).join("") || `<li class="empty">No one in this tier.</li>`}</ul>`;
}
// Score as a short bar with the tier letter: the number is there for a reader who wants it.
const meter = l => { const v = Math.max(0, Math.min(100, Number(l.score) || 0)); return `<span class="meter" data-tier="${esc(l.tier)}" title="Score ${v} of 100"><span class="meter-bar" aria-hidden="true"><span style="--v:${v / 100}"></span></span><span class="meter-t">${esc(l.tier || "–")}</span><span class="num meter-n">${v}</span></span>`; };
const backIcon = `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M10 3 5 8l5 5"/></svg>`;

function detail() {
  const el = $("detail");
  if (!el) return;
  const l = lead();
  const key = l ? l.login + l.draft_status + ui.rejecting : "none";
  if (key === ui.detailKey && el.childElementCount) return;  // keep in-progress edits across polls
  ui.detailKey = key;
  if (!l) { el.innerHTML = ""; return; }
  const done = l.draft_status !== "pending";
  el.innerHTML = `<div class="detail-head">${avatar(l)}<h2>${esc(whoOf(l))} ${tier(l.tier)}</h2></div>
    <p class="facts"><a href="${safeUrl(l.url)}" target="_blank" rel="noopener">${l.url.startsWith("https://github.com/") ? "GitHub" : "Where they posted"}${EXT}</a>
      ${l.company ? `<span>${esc(l.company)}</span>` : ""}
      <span>${l.email ? esc(l.email) + " · " + esc(EMAIL[l.email_status] || "unverified") : "No email"}</span>
      ${safeUrl(l.linkedin_url) !== "#" ? `<a href="${safeUrl(l.linkedin_url)}" target="_blank" rel="noopener">LinkedIn${EXT}</a>` : ""}
      <span>Score <span class="num">${l.score}</span></span><span>${esc(l.stage)}</span></p>
    <p class="reason">${esc(l.reason)}</p>
    <section class="block"><h3>What they wrote</h3>
      ${l.signals.map(s => `<article class="signal"><a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.title)}${EXT}</a>
        <p class="meta num">${esc(s.repo)} · ${esc(s.created)}</p>
        <blockquote>${esc(s.excerpt)}${s.excerpt.length >= 300 ? "…" : ""}</blockquote></article>`).join("")}</section>
    ${l.draft_status === "no_author" ? `<section class="block"><h3>No message</h3><p class="hint">This post has no named author, so there is nobody to write to. It is kept as evidence of the problem.</p></section>` : `<section class="block"><h3>Draft${done ? ` · ${esc(l.draft_status)} by ${esc(who(l.stage_actor))}` : ""}</h3>
      <div class="field"><label for="subj">Subject</label><input type="text" id="subj" maxlength="300" value="${esc(l.subject)}" ${done ? "disabled" : ""}></div>
      <div class="field"><label for="bodyTxt">Message</label><textarea id="bodyTxt" rows="9" maxlength="5000" ${done ? "disabled" : ""}>${esc(l.body)}</textarea></div>
      ${done ? "" : ui.rejecting
        ? `<div class="field"><label for="why">Why is this lead wrong?</label><input type="text" id="why" maxlength="500" placeholder="Hobby project, not a company"></div>
           <div class="actions"><button type="button" class="btn danger" data-act="reject">Reject lead</button><button type="button" class="btn quiet" data-act="cancel">Keep</button></div>`
        : `<div class="actions"><button type="button" class="btn" data-act="approve">Approve</button><button type="button" class="btn quiet" data-act="start-reject">Reject</button></div>
           <p class="hint">Goes to the demo inbox, never to the lead.</p>`}
    </section>`}`;
  if (ui.rejecting) $("why")?.focus();
}

const LEVELS = ["shadow", "supervised", "autopilot"];  // mirrors app/trust.py
const GOOD = `<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="9"/><path d="m6 10.5 2.7 2.7L14.2 7.5"/></svg>`;
const WAIT = `<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="9"/><path d="M6.5 10h7"/></svg>`;
function trustBlock(trust) {
  const gates = trust.gates || [], met = gates.filter(g => g.passed).length, level = String(trust.level || "unknown");
  const i = LEVELS.indexOf(level), up = i >= 0 && i < LEVELS.length - 1 ? LEVELS[i + 1] : null, target = up || (i > 0 ? LEVELS[i - 1] : null);
  const why = level === "autopilot" ? "Earshot may send on its own while every check holds." : (trust.blocked_by || []).length ? `Autopilot is not available yet: ${trust.blocked_by.join("; ")}.` : met === gates.length && gates.length ? "Every check holds; you can ask for more autonomy." : "Autopilot waits until every check passes.";
  return fold("trust", "Trust", `${esc(level[0].toUpperCase() + level.slice(1))} · <span class="num">${met} of ${gates.length}</span> checks passed`,
    `<ul class="gates">${gates.map(g => `<li class="gate" data-passed="${!!g.passed}"><span class="gate-mark" aria-hidden="true">${g.passed ? GOOD : WAIT}</span><span class="gate-label">${esc(g.label)}<span class="visually-hidden">: ${g.passed ? "passed" : "not yet"}</span></span><span class="gate-val">${esc(g.value ?? "–")}</span></li>`).join("")}</ul>
     <p class="gate-say">${esc(why)}</p>${target ? `<div class="actions"><button type="button" class="btn quiet" data-autonomy="${target}">${up ? "Request " : "Step back to "}${target}</button></div>` : ""}`, true);
}

// One large number, and a thin bar of what this ledger spent against what is left.
function creditsHead(b, rows) {
  const spent = rows.reduce((n, e) => n + (e.ok ? Number(e.credits) || 0 : 0), 0), left = Math.max(0, b.credits), all = spent + left;
  return `<div class="credits"><p class="credits-n num">${left.toFixed(1)}<span>credits left</span></p>
    ${all ? `<div class="usage" role="img" aria-label="${spent.toFixed(1)} spent, ${left.toFixed(1)} left"><span style="--v:${(spent / all).toFixed(3)}"></span></div><p class="usage-say num">${spent.toFixed(1)} spent in this ledger</p>` : ""}</div>`;
}

function activityView() {
  const {events, status, checks, billing, floor} = ui.data;
  const m = ui.data.mail || {};
  const sending = m.connected ? `Gmail${m.address ? ` · ${esc(m.address)}` : ""}` : m.resend ? "Resend, demo inbox" : "Not set up";
  const rows = [...billing.ledger].sort((a, b) => String(b.ts).localeCompare(String(a.ts))), cap = 12, shown = ui.ledgerAll ? rows : rows.slice(0, cap);
  const ledger = rows.length ? `<ul class="ruled">${shown.map(e => `<li class="ledger"><span class="num muted">${esc(String(e.ts).slice(11, 19))}</span><span>${esc(e.event)}${e.ok ? "" : " (not recorded)"}${e.lead ? ` <span class="muted">· ${esc(e.lead)}</span>` : ""}</span><span class="num">${Number(e.credits).toFixed(1)}</span></li>`).join("")}</ul>
    ${rows.length > cap && !ui.ledgerAll ? `<button type="button" class="linkish" data-ledger-all>Show all ${rows.length}</button>` : ""}` : `<p class="muted">No spend yet.</p>`;
  const audit = (events.length ? `<ul class="log">${events.map(e => `<li><span class="num muted">${esc(e.ts.slice(11, 19))}</span><span class="actor" data-actor="${esc(who(e.actor))}">${esc(who(e.actor))}</span>
      <span class="what">${esc(e.action)} ${esc(e.login)}${e.detail ? `<span class="muted"> · ${esc(e.detail)}</span>` : ""}</span></li>`).join("")}</ul>` : `<p class="muted">No decisions yet.</p>`) +
    (checks.length ? `<ul class="log">${checks.map(c => `<li><span class="num muted">${esc(c.rule)}</span><span>${esc(c.login)}</span><span class="what muted">${esc(c.detail)}</span></li>`).join("")}</ul>` : `<p class="muted">Every lead passes every rule.</p>`) +
    `<p class="muted">Sending: ${sending}. ${m.connected || m.resend ? "To the demo inbox, never to the lead." : "Approvals are recorded; nothing is sent."}</p>
     ${m.connected ? `<div class="actions"><button type="button" class="btn quiet" data-gmail-disconnect>Disconnect Gmail</button></div>` : m.configured ? `<div class="actions"><a class="btn quiet" href="/api/gmail/connect">Connect Gmail</a></div>` : ""}`;
  return trustBlock(floor?.trust || {}) +
    fold("run", "Last run", status.running ? "Running" : status.log.length ? plural(status.log.length, "step", "steps") : "None yet", status.log.length ? steps() : `<p class="muted">No run yet.</p>`, status.log.length <= 8) +
    fold("credits", "Credits", `<span class="num">${billing.credits.toFixed(1)}</span> left`,
      `${creditsHead(billing, rows)}<p class="muted">${billing.mode === "flexprice" ? "Metered by Flexprice." : "Local wallet."} A lead costs ${billing.costs["lead.enriched"]}, a sent message ${billing.costs["outreach.sent"]}.</p>
       ${billing.mode === "local" ? `<div class="actions"><button type="button" class="btn quiet" data-topup="20">Add 20 credits</button></div>` : ""}${ledger}`, rows.length <= cap) +
    fold("audit", "Sent and decisions", `${plural(events.length, "decision", "decisions")} · ${plural(checks.length, "finding", "findings")}`, audit, events.length + checks.length <= 6);
}

// --- render loop -----------------------------------------------------------------

function renderPanel() {
  const v = view(), changed = v !== ui.shown, home = v === "home";
  document.querySelectorAll(".tabs [data-view]").forEach(a => a.dataset.view === v ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  $("home").hidden = !home; $("section").hidden = home;
  if (home) { ui.shown = v; if (changed) window.scrollTo(0, 0); return; }
  $("panel-title").textContent = SECTIONS[v];
  const body = $("view");
  // Someone is typing in this section: leave it alone until they are done.
  if (!changed && body.contains(document.activeElement) && document.activeElement.matches("input, textarea")) { detail(); return; }
  if (v === "leads" && !changed && lead() && $("detail") && ui.detailFor === ui.selected) { $("funnel").outerHTML = peopleView().match(/^<p[^]*?<\/p>/)[0]; detail(); }
  else {
    body.innerHTML = {leads: peopleView, activity: activityView}[v]();
    ui.detailKey = ""; ui.detailFor = ui.selected;
    detail();
  }
  if (changed) { window.scrollTo(0, 0); $("panel-title").focus({preventScroll: true}); }
  ui.shown = v;
}

function render() { renderHome(); renderPanel(); }

async function refresh(force) {
  try {
    const data = await api("/api/state"), json = JSON.stringify(data);
    if (!force && json === ui.json) return;  // nothing changed: leave focus and typing alone
    ui.data = data; ui.json = json;
    window.EarshotAsk?.update(data, ASK);
    if (!ui.desc && !ui.target && data.icp?.sources?.length) ui.target = data.icp.sources[0];
    else if (!ui.desc && data.icp?.description) { ui.desc = data.icp.description; ui.repo = data.icp.product_repo || ""; }
    render();
  } catch (e) { if ($("home-line")) $("home-line").textContent = "Cannot reach the server."; console.error(e); }
}

document.addEventListener("input", e => {
  if (e.target.id === "desc") ui.desc = e.target.value;
  if (e.target.id === "repo") ui.repo = e.target.value;
  if (e.target.id === "target") ui.target = e.target.value;
});
document.addEventListener("toggle", e => { if (e.target.dataset?.fold) ui.open[e.target.dataset.fold] = e.target.open; }, true);  // toggle does not bubble
document.addEventListener("submit", async e => {
  if (e.target.id !== "intake" && e.target.id !== "intake-manual") return;
  e.preventDefault();
  ui.error = "";
  const typed = e.target.id === "intake-manual", target = ui.target.trim();
  try {
    if (typed && ui.desc.trim().length < 20) throw new Error("Describe it in at least 20 characters.");
    if (!typed && !target) throw new Error("Type your website address first, for example yourcompany.com.");
    await api("/api/run", typed ? {description: ui.desc, product_repo: ui.repo.trim()} : {target});
    ui.restart = ui.example = false;
    location.hash = "home";
  } catch (err) { ui.error = err.message; }
  $("home-top").innerHTML = "";  // let the next render show the error or the line
  refresh(true);
});
document.addEventListener("click", async e => {
  const nav = e.target.closest(".tabs [data-view]");
  if (nav) { if (nav.dataset.view === "leads") { ui.selected = null; if (view() === "leads") renderPanel(); } return; }
  const flip = (k, v) => { ui[k] = v; ui.error = ""; $("home-top").innerHTML = ""; location.hash = "home"; renderHome(); };
  if (e.target.closest("[data-example]")) return flip("example", true);
  if (e.target.closest("[data-example-off]")) { flip("example", false); return $("target")?.focus(); }
  if (e.target.closest("[data-restart]")) { flip("restart", true); return $("target")?.focus(); }
  if (e.target.closest("[data-restart-off]")) return flip("restart", false);
  if (e.target.closest("[data-ledger-all]")) { ui.ledgerAll = true; renderPanel(); return; }
  const au = e.target.closest("[data-autonomy]");
  if (au) { try { await api("/api/autonomy", {level: au.dataset.autonomy}); } catch (err) { console.error(err); } refresh(true); return; }
  if (e.target.closest("[data-back]")) { ui.selected = null; ui.rejecting = false; renderPanel(); return; }
  const open = e.target.closest("[data-open]"), act = e.target.closest("[data-act]"), tf = e.target.closest("[data-tier-filter]");
  if (tf) { ui.tier = tf.dataset.tierFilter; renderPanel(); }
  const tu = e.target.closest("[data-topup]");
  if (tu) { await api("/api/billing/top-up", {credits: Number(tu.dataset.topup)}); refresh(true); }
  if (e.target.closest("[data-gmail-disconnect]")) { await api("/api/gmail/disconnect", {}); refresh(true); }
  if (open && open.dataset.goLeads !== undefined) { ui.selected = open.dataset.open; ui.detailFor = null; location.hash = "leads"; renderPanel(); return; }
  if (open) { ui.selected = open.dataset.open; ui.rejecting = false; ui.detailFor = null; renderPanel(); window.scrollTo(0, 0); }
  if (!act) return;
  const a = act.dataset.act;
  if (a === "start-reject" || a === "cancel") { ui.rejecting = a === "start-reject"; ui.detailKey = ""; detail(); return; }
  try { await decideOpen(a, $("why")?.value || ""); }
  catch (err) { act.closest(".block").insertAdjacentHTML("beforeend", `<p class="error" role="alert">${esc(err.message)}</p>`); }
});
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || view() === "home" || e.defaultPrevented || document.activeElement?.closest(".ask")) return;
  location.hash = "home";
});

// The open lead's draft as shown, so an edit in progress is what gets approved.
async function decideOpen(action, reason) {
  await api(`/api/leads/${encodeURIComponent(ui.selected)}/decision`, {action, subject: $("subj")?.value, body: $("bodyTxt")?.value, reason});
  ui.rejecting = false;
  refresh(true);
}

// The one place the founder acts: Ask shows a single question at a time and calls these.
const ASK = {
  decide: async (login, action, reason) => { await api(`/api/leads/${encodeURIComponent(login)}/decision`, {action, reason}); refresh(true); },
  autonomy: async level => { const r = await api("/api/autonomy", {level}); refresh(true); return r; },
  topUp: async credits => { await api("/api/billing/top-up", {credits}); refresh(true); },
  open: login => { ui.selected = login; ui.rejecting = false; if (view() === "leads") renderPanel(); },  // never pulls the founder off the view they chose
};
document.addEventListener("earshot:open", e => { ui.selected = e.detail.login; ui.rejecting = false; ui.detailFor = null; location.hash = "leads"; ui.data && renderPanel(); });
const moved = () => { const to = MOVED[location.hash.slice(1)]; if (to) location.replace("#" + to); return !!to; };
addEventListener("hashchange", () => { if (!moved()) ui.data && renderPanel(); });
moved();
refresh(true);
setInterval(refresh, 2000);
