// Every string from GitHub or the model goes through esc(): it is untrusted text.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const safeUrl = u => /^https?:\/\//.test(u || "") ? esc(u) : "#";
const $ = id => document.getElementById(id);
const who = a => a === "rep" ? "you" : a === "agent" ? "Earshot" : a;
const TIER = {A: "Strong", B: "Good", C: "Maybe"};
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
// Home is the customer; the other two are pages of their own. Old section names land on the nearest page.
const SECTIONS = {leads: "People", activity: "Activity"};
const MOVED = {floor: "home", profile: "home", map: "leads", pipeline: "leads", proof: "activity"};
const EMAIL = {valid: "verified", accept_all: "domain accepts all mail", invalid: "failed verification", webmail: "personal webmail", disposable: "disposable address", unknown: "unverified", pending: "verifying"};

const ui = {data: null, json: "", example: false, restart: false, selected: null, tier: "All", rejecting: false, desc: "", repo: "", target: "", error: "", detailKey: "", shown: "", open: {},
  head: "", ticked: new Set(), ledgerAll: false, entered: new Set(), moving: null, prof: 0, layout: "List"};
try { if (localStorage.getItem("earshot.layout") === "Board") ui.layout = "Board"; } catch (e) { /* storage blocked: list it is */ }

async function api(path, body) {
  const r = await fetch(path, body ? {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)} : {});
  if (!r.ok) {
    const d = (await r.json().catch(() => ({}))).detail;
    throw new Error(typeof d === "string" ? d : "The request was rejected. Try again.");
  }
  return r.json();
}
// Anchors inside Activity (the story line links to them) open Activity.
const ANCHORS = /^(step-[1-5]|trust|credits)$/;
const view = () => { const h = location.hash.slice(1); return SECTIONS[h] ? h : ANCHORS.test(h) ? "activity" : "home"; };
const lead = () => ui.data.leads.find(l => l.login === ui.selected);
// A web lead whose only name is the site it was found on.
const nameOf = l => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(l.name || "") ? `Someone on ${l.name.replace(/^www\./i, "")}` : (l.name || l.login);

// --- shared pieces ----------------------------------------------------------------
const AR = `<span class="arr" aria-hidden="true">↗</span>`;
const secHead = (k, title, sub) => `<div class="sec-head"><p class="label">${k}</p><h2 class="title">${title}</h2>${sub ? `<p class="sub">${sub}</p>` : ""}</div>`;
const sec = (key, inner, id) => `<section class="sec${enter(key)}"${id ? ` id="${id}"` : ""}><div class="wrap">${inner}</div></section>`;
const vals = f => Array.isArray(f) ? f : (f?.values || []);
const lowerFirst = t => /^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t;
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
const cap = t => t ? t[0].toUpperCase() + t.slice(1) : t;
const noTag = t => String(t || "").replace(/^\s*\[[A-Za-z ]+\]:?\s*/, "");  // "[BUG]: x" reads as "x"
const initials = n => String(n || "?").replace(/^Someone on /, "").split(/[\s._-]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("") || "?";
const noAuthor = l => l.draft_status === "no_author";
const whoOf = l => noAuthor(l) ? `Someone on ${hostOf(l.url) || "the web"}` : nameOf(l);
const EAR = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><path d="M4 3.5h8a1.5 1.5 0 0 1 1.5 1.5v4.5A1.5 1.5 0 0 1 12 11H8l-3 2.5V11H4a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 4 3.5Z"/></svg>`;
// A face for every person: their GitHub avatar, else their initials; a post with no author gets a neutral speech mark.
const avatar = (l, big) => {
  if (noAuthor(l)) return `<span class="av${big ? " big" : ""}">${EAR}</span>`;
  const gh = l.login && !l.login.startsWith("web:");
  return `<span class="av${big ? " big" : ""}"><span aria-hidden="true">${esc(initials(nameOf(l)))}</span>${gh ? `<img src="https://github.com/${encodeURIComponent(l.login)}.png?size=160" alt="" loading="lazy" onerror="this.remove()">` : ""}</span>`;
};
const when = d => { const t = new Date(d || ""); return isNaN(t) ? "" : t.toLocaleDateString(undefined, {month: "short", year: "numeric"}); };
// Sections fade in once per page, on the first paint with content, never on a poll.
const enter = k => ui.entered.has(k) ? "" : (ui.entered.add(k), " reveal");
const io = "IntersectionObserver" in window ? new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }), {threshold: 0.12}) : null;
const reveal = () => document.querySelectorAll(".reveal:not(.is-in)").forEach(el => io ? io.observe(el) : el.classList.add("is-in"));
const TICK = `<svg class="tick" viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m5 10.5 3.2 3.2L15 6.5"/></svg>`;

// A pain as a headline: up to the first clause boundary, at most ten words, never cut mid-word, never an ellipsis.
const STOP = /^(to|the|a|an|of|in|for|with|and|or|our|we|is|are|on|at|by|but)$/i;
function headline(p) {
  const s = String(p || "").replace(/\s*\(.*?\)/g, "").trim();
  const head = s.split(/[,;:.?!]|\s(?:and|so|because|but|which|when|while|where|if)\s/i)[0].trim();
  let w = (head.split(/\s+/).length >= 3 ? head : s).split(/\s+/).slice(0, 10);
  while (w.length > 3 && STOP.test(w.at(-1))) w.pop();
  return cap(w.join(" "));
}
// The buyer in at most six words, cut at a natural phrase; the phrase after the noun goes in italic.
function buyer(role) {
  let w = String(role || "").replace(/\s*\(.*?\)/g, "").replace(/(\w+)\/[\w-]+/g, "$1").split(/\s+(?:at|who|with|for|in)\s+|,/i)[0].trim().split(/\s+/).slice(0, 6);
  while (w.length > 2 && STOP.test(w.at(-1))) w.pop();
  const i = w.findIndex((x, k) => k > 0 && /ing$/i.test(x)), at = i > 0 ? i : Math.max(1, w.length - 1);
  return `${esc(cap(w.slice(0, at).join(" ")))} <em>${esc(w.slice(at).join(" "))}</em>`;
}

// --- home --------------------------------------------------------------------------

function homeStrip() {
  const {floor, billing} = ui.data, gates = floor.trust?.gates || [];
  const level = floor.trust?.level === "autopilot" ? "Earshot sends on its own" : "You approve every message";
  return `<a href="#activity">${level}</a><span class="dot" aria-hidden="true">·</span>
    <a href="#trust">Trust checks <span class="num">${gates.filter(g => g.passed).length} of ${gates.length}</span> passed</a><span class="dot" aria-hidden="true">·</span>
    <a href="#credits"><span class="num">${Math.floor(billing.credits)}</span> credits left</a>`;
}

// How many people the run heard, from the count it reported; otherwise the people kept.
const heardFrom = d => { const m = (d.status.log || []).map(l => l.match(/issues describe a target pain, from (\d+) people/)).find(Boolean); return m ? +m[1] : d.leads.length; };

// --- the story: the whole run as five plain steps, every number read from state (none invented) ---
const logm = (d, re) => (d.status.log || []).map(l => l.match(re)).find(Boolean) || null;
const PLAIN = s => String(s).replace(/\bleads\b/g, "people").replace(/\blead\b/g, "person").replace(/self-check/gi, "its own check")
  .replace(/^Qualifier → Enricher: scored; looking up a business email for the strong people/, "Scored everyone; looked up a work email for the strongest");
const STEP_OF = [/^Planner: (reading|inferring)/, /^(Planner → Scout|Scout: .+ has \d+ issues|Scout: found)/, /^(Scout → Qualifier|Scout: learned|Scout: dropped)/, /^(Qualifier|Enricher)/, /^(Writer|Reviewer|Done)/];
function story(d, example) {
  const i = d.icp || {}, leads = d.leads;
  const read = logm(d, /^Planner: reading (\S+)/), site = hostOf(read ? read[1] : (i.sources || [])[0]);
  const scan = logm(d, /(\d+) of (\d+) issues describe a target pain, from (\d+) people/);
  const chans = vals(i.channels).filter(c => c.domain);
  const kept = logm(d, /(\d+) leads kept/), dropped = logm(d, /dropped (\d+) people whose issue/);
  const flagged = logm(d, /(\d+) make a claim the evidence does not show/), rew = logm(d, /(\d+) drafts claimed more .* (\d+) now pass, (\d+) held/);
  const msgs = leads.filter(l => !noAuthor(l)), pending = msgs.filter(l => (l.draft_status || "pending") === "pending").length;
  const sells = String(i.product || "").replace(/^[^:]{1,40}:\s*/, "").split(/\s+/).slice(0, 6).join(" ").replace(/[,;:.]$/, "");
  const drops = (d.status.log || []).filter(l => /^(Qualifier|Scout): dropped/.test(l)).map(l => cap(PLAIN(strip(l))));
  const more = (lines, href, label) => `<ul class="st-lines">${lines.map(t => `<li>${t}</li>`).join("")}</ul>${href ? `<a class="linkish" href="${href}">${label} →</a>` : ""}`;
  return [
    {t: site ? `Read <em>${esc(site)}</em>` : "Read <em>your description</em>", n: sells ? esc(cap(sells)) : "",
      more: more(vals(i.pains).slice(0, 3).map(p => esc(headline(p))), "#pains", "What they struggle with")},
    {t: chans.length ? `Listened on <em>${plural(chans.length, "site", "sites")}</em>` : "Listened where they <em>write</em>", n: scan ? `${scan[2]} posts read` : "",
      more: more(chans.slice(0, 6).map(c => `<b>${esc(c.domain.replace(/^(www|news)\./, ""))}</b> ${esc(c.why || "")}`), example ? "" : "#step-2", "Where it listened")},
    {t: scan ? `Found <em>${scan[3]} people</em> with this problem` : "Found people <em>with this problem</em>", n: "matched by meaning, not keywords",
      more: more(vals(i.learned_pains).length ? ["How they say it:", ...vals(i.learned_pains).slice(0, 3).map(p => `<q>${esc(p)}</q>`)] : ["Each post was compared with the pains by what it means, not by its words."], example ? "" : "#step-3", "Everything it read")},
    {t: `Kept <em>${kept ? kept[1] : leads.length}</em> worth writing to`, n: dropped ? `${dropped[1]} dropped as not a fit` : "",
      more: more([...drops.map(esc), "Posts with no named author are kept as evidence only: there is nobody to write to."], example ? "" : "#leads", "See the people")},
    {t: pending ? `Wrote <em>${plural(msgs.length, "message", "messages")}</em>. They wait for you.` : `<em>${plural(msgs.length, "message", "messages")}</em> decided`, n: "", pending, example,
      more: more([flagged ? `A second model checked every message against what the person wrote; ${flagged[1]} claimed more than they wrote${rew ? `, ${rew[1]} were rewritten, ${rew[3]} are held` : ""}.` : "A second model checked every message against what the person wrote.",
        "Nothing is sent to the person in this demo."], example ? "" : "#step-5", "What happened to each")},
  ];
}
// The one next step, in plain words; nothing while a run goes (that screen is the run itself).
function nextAction(d, example) {
  if (example || d.status.running || !d.leads.length) return "";
  const n = d.leads.filter(l => l.draft_status === "pending").length;
  return `<div class="hero-act">${n ? `<button type="button" class="btn" data-review>Review ${plural(n, "message", "messages")}</button>` : `<button type="button" class="btn" data-restart>Find more customers</button>`}
    <button type="button" class="linkish" data-scroll="how">How we got here</button></div>`;
}
function storyLine(d, example) {
  const rows = story(d, example).map((s, k) => {
    const n = k + 1, open = ui.step === n;
    const act = n === 5 && !example ? (s.pending ? `<button type="button" class="pill st-act" data-review>Review them</button>` : `<a class="pill st-act" href="#activity">See activity</a>`) : "";
    return `<li class="st${open ? " is-open" : ""}${act ? " has-act" : ""}"><button type="button" class="r st-btn" data-step="${n}" aria-expanded="${open}" aria-controls="st-more-${n}">
      <span class="r-k num">0${n}</span><span class="r-t">${s.t}</span><span class="r-n">${s.n}<span class="chev" aria-hidden="true">⌄</span></span></button>${act}
      <div class="st-more" id="st-more-${n}"${open ? "" : " inert"}><div>${s.more}</div></div></li>`;
  }).join("");
  return `<section class="sec${enter(example ? "s-how" : "h-how")}" id="how"><div class="wrap">${secHead("How we got here", "Five <em>steps</em>")}<ul class="rows story">${rows}</ul></div></section>`;
}

function homeCustomer(d, example) {
  const {icp, leads, status} = d, i = icp || {};
  const role = vals(i.personas)[0], kind = vals(i.industries)[0], trig = vals(i.triggers)[0];
  const sigs = leads.flatMap(l => l.signals.map(s => ({...s, login: l.login})));
  const by = login => leads.find(l => l.login === login) || {};
  const voiced = p => new Set(sigs.filter(s => s.pain === p).map(s => s.login)).size;
  const learned = new Set(vals(i.learned_pains));
  const all = [...new Set([...vals(i.pains), ...learned])].map(p => [p, voiced(p)]).sort((a, b) => b[1] - a[1]);
  const pains = (all.filter(p => p[1]).length >= 3 ? all.filter(p => p[1]) : all).slice(0, 3);
  const sites = vals(i.channels).map(c => c.domain).filter(Boolean).slice(0, 4);
  const n = heardFrom(d);
  const line = [kind && !/\sat\s/i.test(role || "") ? `At ${kind.replace(/\s+compan(y|ies)$/i, "")} companies` : "", trig ? lowerFirst(trig) : ""].filter(Boolean).join(", ");
  const banner = example ? `<p class="example-bar"><span>Example: Flexprice. Nothing here is yours.</span><button type="button" class="linkish" data-example-off>Use my website</button></p>` : "";
  const hero = `<header class="hero${enter(example ? "s-hero" : "h-hero")}"><div class="wrap">${banner}
    <p class="label">${status.error ? "Last run stopped" : "Your customer"}</p>
    <h1 class="display" id="home-line">${status.error ? esc(status.error) : role ? buyer(role) : "Working out <em>who buys</em>"}</h1>
    ${line ? `<p class="hero-desc">${esc(cap(line))}.</p>` : ""}
    ${nextAction(d, example)}
    ${sites.length && n ? `<div class="logos"><p class="label bare">Heard from <span class="num">${n}</span> ${n === 1 ? "person" : "people"} on</p>
      <ul class="logo-row">${sites.map(s => `<li><a href="https://${esc(s)}" target="_blank" rel="noopener">${esc(s.replace(/^(www|news)\./, ""))}</a></li>`).join("")}</ul></div>` : ""}
  </div></header>`;
  if (!icp) return hero;
  const painCards = pains.map(([p, k]) => `<li class="card"><div class="card-media"><p class="card-big num">${k || "–"}<small>${k === 1 ? "person" : k ? "people" : "not heard yet"}</small></p></div>
    <div class="card-body"><p class="card-title">${esc(headline(p))}</p><p class="card-line">${esc(p)}</p><p class="meta">${learned.has(p) ? "Learned from posts" : "From your site"}</p></div></li>`).join("");
  const words = [...sigs].filter(s => noTag(s.title)).sort((a, b) => (b.match || 0) - (a.match || 0)).slice(0, 6);
  const wordRows = words.map(s => `<li><a class="r" href="${safeUrl(s.url)}" target="_blank" rel="noopener"><span class="r-k">${esc(when(s.created))}</span>
    <span class="r-t"><i>${esc(s.repo || hostOf(s.url))}</i> ${esc(noTag(s.title))}</span><span class="r-n">${esc(whoOf(by(s.login)))}${AR}</span></a></li>`).join("");
  const top = [...leads].sort((a, b) => b.score - a.score).slice(0, 3);
  const personCard = l => { const inner = `<div class="card-media">${avatar(l, true)}</div><div class="card-body"><p class="card-title">${esc(whoOf(l))}${example ? "" : AR}</p>
      <p class="meta">${esc([l.company || (noAuthor(l) ? "Evidence only" : "GitHub"), `Score ${l.score}`].join(" · "))}</p></div>`;
    return `<li>${example ? `<div class="card">${inner}</div>` : `<button type="button" class="card" data-open="${esc(l.login)}" data-go-leads>${inner}</button>`}</li>`; };
  return hero + storyLine(d, example) +
    (pains.length ? sec(example ? "s-pains" : "h-pains", secHead("What they struggle with", `${["One", "Two", "Three"][pains.length - 1]} <em>${pains.length === 1 ? "pain" : "pains"}</em>`) + `<ul class="cards">${painCards}</ul>`, "pains") : "") +
    (wordRows ? sec(example ? "s-words" : "h-words", secHead("In their own words", "What they <em>wrote</em>") + `<ul class="rows">${wordRows}</ul>`) : "") +
    (top.length ? sec(example ? "s-people" : "h-people", secHead("People", "Who <em>said it</em>") + `<ul class="cards">${top.map(personCard).join("")}</ul>` +
      (example ? "" : `<p class="center"><a class="pill" href="#leads">See all ${leads.length} <span aria-hidden="true">⌄</span></a></p>`)) : "") +
    (example ? "" : fullProfile(i, d.expansions || {}));
}
// Everything else the Planner inferred, closed by default: one row per question, opened in place.
function fullProfile(i, said) {
  const list = xs => `<ul class="st-lines">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`;
  const exp = (i.expansion || []).filter(x => x.segment).map(x => { const a = said[x.segment], seg = esc(x.segment);
    const pills = ["accept", "dismiss"].filter(k => k !== a).map(k => `<button type="button" class="pill sm" data-expand="${k}" data-segment="${seg}">${a ? (k === "accept" ? "Add instead" : "Dismiss instead") : k === "accept" ? "Add" : "Dismiss"}</button>`).join("");
    return `<li class="exp"><span><b>${seg}</b> ${esc(x.reasoning || "")}</span><span class="exp-act">${a ? `<span class="meta">${a === "accept" ? "Added" : "Dismissed"}</span>` : ""}${pills}</span></li>`; });
  const comp = (i.competitors || []).filter(c => c.name).map(c => `<li><b>${esc(c.name)}</b> <span class="meta">${esc(c.category || "")}</span><br>${esc(c.positioning || "")}${c.github_repo ? ` · ${ext("https://github.com/" + c.github_repo, c.github_repo + " ↗")}` : ""}</li>`);
  const rows = [
    ["Industries", vals(i.industries), list],
    ["Company size", vals(i.company_size), list],
    ["Who buys", vals(i.personas), list],
    ["What triggers a search", vals(i.triggers), list],
    ["Not a fit when", vals(i.negative_signals), list],
    ["Also worth a look", exp, xs => `<ul class="st-lines">${xs.join("")}</ul>`],
    ["Who else sells this", comp, xs => `<ul class="st-lines">${xs.join("")}</ul>`],
  ].filter(r => r[1].length);
  if (!rows.length) return "";
  const lis = rows.map(([t, xs, f], k) => { const n = k + 1, open = ui.prof === n;
    return `<li class="st${open ? " is-open" : ""}"><button type="button" class="r st-btn" data-prof="${n}" aria-expanded="${open}" aria-controls="pf-more-${n}">
      <span class="r-k num">0${n}</span><span class="r-t">${t}</span><span class="r-n">${xs.length}<span class="chev" aria-hidden="true">⌄</span></span></button>
      <div class="st-more" id="pf-more-${n}"${open ? "" : " inert"}><div>${f(xs)}</div></div></li>`; }).join("");
  return sec("h-prof", secHead("The full profile", "Who to <em>look for</em>") + `<ul class="rows story">${lis}</ul>`, "profile");
}

// Arrival: one promise, one field, three steps.
function intakeForm() {
  const back = ui.data.leads.length ? `<button type="button" class="linkish" data-restart-off>Back to your results</button>` : `<button type="button" class="linkish" data-example>See an example</button>`;
  return `<header class="hero"><div class="wrap">
    <p class="label">Earshot</p>
    <h1 class="display">Who is your <em>customer</em>?</h1>
    <p class="hero-line">Paste your website. We find the people <em>already</em> describing your problem.</p>
    <form class="intake" id="intake" novalidate>
      <label for="target" class="visually-hidden">Your website</label>
      <div class="field-pill"><input type="text" id="target" placeholder="yourcompany.com" maxlength="200" autocomplete="url" inputmode="url" value="${esc(ui.target)}"
        ${ui.error ? `aria-invalid="true" aria-describedby="intake-err"` : ""}><button class="btn">Find my customers</button></div>
      ${ui.error ? `<p class="error" id="intake-err" role="alert">${esc(ui.error)}</p>` : ""}
      <p class="hint" style="margin-top:var(--space-3)">About two minutes · ${back}</p>
    </form>
    <details class="nosite" data-fold="manual" ${ui.open.manual ? "open" : ""}><summary>No website?</summary>
      <form class="intake-manual" id="intake-manual" novalidate>
        <div class="field"><label for="desc">What you sell, and to whom</label><textarea id="desc" rows="4" maxlength="20000">${esc(ui.desc)}</textarea></div>
        <div class="field"><label for="repo">GitHub repository</label><input type="text" id="repo" placeholder="owner/name" value="${esc(ui.repo)}"></div>
        <div class="actions"><button class="btn">Find my customers</button></div>
      </form></details>
  </div></header>
  <section class="sec"><div class="wrap">${secHead("How it works", "Three <em>steps</em>")}
    <ul class="rows"><li><div class="r"><span class="r-k">01</span><span class="r-t">Reads your site</span><span class="r-n">What you sell</span></div></li>
    <li><div class="r"><span class="r-k">02</span><span class="r-t">Listens where buyers <i>write</i></span><span class="r-n">GitHub, forums, reviews</span></div></li>
    <li><div class="r"><span class="r-k">03</span><span class="r-t">Shows who they are</span><span class="r-n">You say yes or no</span></div></li></ul></div></section>`;
}

// Progress: the run's log, as five steps a founder recognises.
const strip = l => l.replace(/^[A-Z][a-z]+( → [A-Z][a-z]+)?:\s*/, "");
const RUN = [
  {name: "Reading your site", done: /^Planner: inferring/},
  {name: "Naming your customer", done: /^Planner → Scout/},
  {name: "Listening where they write", done: /^Scout → Qualifier/,
    result: log => { const m = log.map(l => l.match(/(\d+) of (\d+) issues .* from (\d+) people/)).find(Boolean); return m && `${m[2]} posts, ${m[3]} people`; }},
  {name: "Checking each person", done: /^(Enricher → Writer|Writer →)/,
    result: log => { const m = log.map(l => l.match(/^Enricher → Writer: (\d+) leads kept/)).find(Boolean); return m && `${plural(+m[1], "person", "people")} kept`; }},
  {name: "Writing to each", done: /^Done:/,
    result: log => { const m = log.map(l => l.match(/(\d+) messages drafted/)).find(Boolean); return m && plural(+m[1], "message", "messages"); }},
];
function runView() {
  const log = ui.data.status.log || [];
  const doneAt = RUN.map(s => log.findIndex(l => s.done.test(l)));
  const cur = doneAt.findIndex(i => i < 0);
  const site = ui.target ? hostOf(/^https?:/.test(ui.target) ? ui.target : "https://" + ui.target) || ui.target : "";
  return `<header class="hero"><div class="wrap" aria-live="polite"><p class="label">Earshot</p>
    <h1 class="display">Finding your <em>customers</em></h1>${site ? `<p class="hero-line">${esc(site)}</p>` : ""}<p class="hero-desc">About two minutes.</p></div></header>
    <section class="sec"><div class="wrap"><ul class="rows">${RUN.map((s, i) => {
      const state = doneAt[i] >= 0 ? "done" : i === cur ? "now" : "next";
      const note = state === "done" ? s.result?.(log) : state === "now" ? strip(log.at(-1) || "Starting.") : "";
      return `<li><div class="r" data-state="${state}"${state === "now" ? ` aria-current="step"` : ""}><span class="r-k">${state === "done" ? TICK : `0${i + 1}`}</span>
        <span class="r-t">${s.name}<span class="visually-hidden">${state === "done" ? ", done" : state === "now" ? ", in progress" : ""}</span></span><span class="r-n">${esc(note || "")}</span></div></li>`;
    }).join("")}</ul>
    <details class="nosite live" data-fold="live" ${ui.open.live ? "open" : ""}><summary>Live</summary><ul class="st-lines">${log.map(l => `<li>${esc(PLAIN(l))}</li>`).join("")}</ul></details></div></section>`;
}
function failedView() {
  const err = String(ui.data.status.error || "").replace(/^[A-Za-z]+Error:\s*/, "");
  const decline = /not a fit/i.test(err);
  return `<header class="hero" role="alert"><div class="wrap"><p class="label">${decline ? "Not a fit" : "Stopped"}</p>
    <h1 class="display">${decline ? "Wrong tool for <em>this product</em>" : "The run <em>stopped</em>"}</h1>
    <p class="hero-desc">${esc(decline ? err.replace(/^Earshot is not a fit for this product:\s*/i, "") : err)}</p>
    <div class="hero-act"><button type="button" class="btn" data-restart>${decline ? "Try another website" : "Try again"}</button></div></div></header>`;
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
  $("home-strip").hidden = mode !== "home";
  reveal();
}

// A fixed picture of a finished Flexprice run, shown before anything is run. Links search the real trackers; nothing is invented about the people beyond their public titles.
const issueSearch = (repo, q) => `https://github.com/${repo}/issues?q=${encodeURIComponent(q)}`;
const SAMPLE = {status: {running: false, log: ["Planner: reading https://flexprice.io to learn what you sell",
    "Scout → Qualifier: 70 of 463 issues describe a target pain, from 39 people", "Enricher → Writer: 6 leads kept",
    "Qualifier: dropped 17 people whose issue does not show a problem this product solves",
    "Writer: wrote nothing for 3 posts with no named author; there is nobody to write to, so they are kept as evidence only"]},
  icp: {personas: ["Backend engineers building billing"], industries: ["AI-native SaaS"], triggers: ["launching or migrating to usage-based or credit-based pricing"],
    pains: ["Stripe metered billing doesn't support our credit-based pricing", "Our home-grown usage billing keeps producing invoice mismatches", "How do I meter LLM tokens per customer"],
    product: "Flexprice: open-source usage-based and credit-based billing",
    channels: [{domain: "github.com", why: "Engineers file issues where usage-based pricing breaks."}, {domain: "news.ycombinator.com", why: "Founders discuss replacing their billing."}, {domain: "reddit.com", why: "Founders ask how to price by usage and credits."}],
    learned_pains: ["No invoice is generated for billing periods where the charge is $0", "Coupon discounts don't carry over to the Stripe invoice lines"]},
  leads: [
    {login: "deef", name: "deef", company: "", score: 3, signals: [{title: "[BUG]: Invoice not being generated when cost is 0", url: issueSearch("getlago/lago", "Invoice not being generated when cost is 0"), repo: "getlago/lago"}]},
    {login: "superphao4", name: "superphao4", company: "", score: 2, reason: "Opened billing issues on getlago/lago", signals: [{title: "", url: issueSearch("getlago/lago", "author:superphao4"), repo: "getlago/lago"}]},
    {login: "derekperkins", name: "Derek Perkins", company: "Nozzle", score: 1, signals: [{title: "[FEAT]: invoice approvals", url: issueSearch("getlago/lago", "invoice approvals"), repo: "getlago/lago"}]},
  ]};

// --- sections ------------------------------------------------------------------------

const HEADS = {leads: ["People", "People who <em>described it</em>"], activity: ["Activity", "The same story, <em>in full</em>"]};
function peopleView() {
  const {leads, status} = ui.data;
  const found = leads.length, stages = ui.data.stages || [];
  const n = s => leads.filter(l => l.stage === s).length, t = k => leads.filter(l => l.tier === k).length;
  const head = `<p class="sub num" id="funnel" style="margin:0 0 var(--space-8)">${stages.map(s => `${n(s)} ${STAGE_SAYS[s] || s.toLowerCase()}`).join(" · ")}
    <small class="tiers" title="By score: the spec's Tier A, B and C">By score: ${["A", "B", "C"].map(k => `${TIER[k]} ${t(k)}`).join(" · ")}</small></p>`;
  if (!found) return head + `<p class="muted">${status.running ? "Running." : "No one yet."}</p>`;
  if (lead()) return head + `<button type="button" class="pill back" data-back><span aria-hidden="true">←</span> Everyone</button><div class="person" id="detail"></div>`;
  const filter = found > 12;
  const shown = leads.filter(l => !filter || ui.tier === "All" || l.tier === ui.tier);
  const layout = `<div class="seg" role="group" aria-label="Show as">${["List", "Board"].map(k => `<button type="button" data-layout="${k}" aria-pressed="${ui.layout === k}">${k}</button>`).join("")}</div>`;
  const bar = `<div class="peo-bar">${filter ? `<div class="seg" role="group" aria-label="Filter by match">${["All", "A", "B", "C"].map(t => `<button type="button" data-tier-filter="${t}" aria-pressed="${ui.tier === t}">${TIER[t] || t}</button>`).join("")}</div>` : "<span></span>"}${layout}</div>`;
  if (ui.layout === "Board") return head + bar + board(shown, stages);
  return head + bar +
    `<ul class="rows${enter("leads")}">${shown.map(l => `<li><button type="button" class="r" data-open="${esc(l.login)}">
      <span class="r-k num">Score ${esc(l.score)}</span>
      <span class="r-t">${esc(whoOf(l))}${l.company ? ` <i>${esc(l.company)}</i>` : ""}<small>${esc(l.reason)}</small></span>
      <span class="r-n">${esc(l.stage)}</span></button></li>`).join("") || `<li class="r muted">No one here.</li>`}</ul>`;
}
const STAGE_SAYS = {Matched: "matched", Contacted: "contacted", Replied: "replied", "Meeting Booked": "meetings", "Closed/Lost": "closed"};
// The pipeline as five columns; the Move menu is the path that always works, dragging is a shortcut.
function board(shown, stages) {
  const card = l => { const open = ui.moving === l.login;
    return `<li class="bcard" draggable="true" data-drag="${esc(l.login)}"><button type="button" class="bc-open" data-open="${esc(l.login)}">${avatar(l)}
      <span class="bc-name">${esc(whoOf(l))}<small class="meta">${esc([l.company, `Score ${l.score}`].filter(Boolean).join(" · "))}</small></span></button>
      <p class="bc-foot"><span>moved by ${esc(who(l.stage_actor) || "Earshot")}</span><button type="button" class="pill sm" data-move="${esc(l.login)}" aria-expanded="${open}" aria-controls="mv-${esc(l.login)}">Move</button></p>
      <div class="mv-menu" id="mv-${esc(l.login)}" role="group" aria-label="Move ${esc(whoOf(l))} to"${open ? "" : " hidden"}>${stages.map(s => `<button type="button" data-stage-to="${esc(s)}" data-login="${esc(l.login)}"${s === l.stage ? ` aria-current="true" disabled` : ""}>${esc(s)}</button>`).join("")}</div></li>`; };
  return `<div class="board${enter("board")}">${stages.map(s => { const ls = shown.filter(l => l.stage === s);
    return `<section class="col" data-drop="${esc(s)}" aria-label="${esc(s)}"><p class="label bare">${esc(s)} <span class="num">${ls.length}</span></p><ul class="col-list">${ls.map(card).join("")}</ul></section>`; }).join("")}</div>`;
}
async function moveTo(login, stage) {
  ui.moving = null;
  try { await api(`/api/leads/${encodeURIComponent(login)}/stage`, {stage}); } catch (err) { console.error(err); }
  refresh(true);
}

function detail() {
  const el = $("detail");
  if (!el) return;
  const l = lead();
  const key = l ? l.login + l.draft_status + ui.rejecting : "none";
  if (key === ui.detailKey && el.childElementCount) return;  // keep in-progress edits across polls
  ui.detailKey = key;
  if (!l) { el.innerHTML = ""; return; }
  const done = l.draft_status !== "pending";
  el.innerHTML = `${avatar(l, true)}<h2 class="display">${esc(whoOf(l))}</h2>
    <p class="meta">${esc([l.company, `Score ${l.score}`, TIER[l.tier], l.stage].filter(Boolean).join(" · "))}</p>
    <p class="facts"><a href="${safeUrl(l.url)}" target="_blank" rel="noopener">${l.url.startsWith("https://github.com/") ? "GitHub" : "Their post"} ↗</a></p>
    <p class="reason">${esc(l.reason)}</p>
    ${personFacts(l)}
    <section class="block">${secHead("What they wrote", "In their <em>words</em>")}<ul class="rows">
      ${l.signals.map(s => `<li><a class="r" href="${safeUrl(s.url)}" target="_blank" rel="noopener"><span class="r-k">${esc(when(s.created))}</span>
        <span class="r-t"><i>${esc(s.repo)}</i> ${esc(noTag(s.title))}<small>${esc(s.excerpt)}</small></span><span class="r-n">${AR}</span></a></li>`).join("")}</ul></section>
    ${l.draft_status === "no_author" ? `<section class="block">${secHead("Message", "No <em>author</em>", "Kept as evidence. Nobody to write to.")}</section>` : `<section class="block">${secHead(done ? `Draft · ${esc(l.draft_status)} by ${esc(who(l.stage_actor))}` : "Draft", "The <em>letter</em>")}
      <div class="letter"><div class="field"><label for="subj">Subject</label><input type="text" id="subj" maxlength="300" value="${esc(l.subject)}" ${done ? "disabled" : ""}></div>
      <div class="field"><label for="bodyTxt">Message</label><textarea id="bodyTxt" rows="9" maxlength="5000" ${done ? "disabled" : ""}>${esc(l.body)}</textarea></div>
      ${done ? "" : ui.rejecting
        ? `<div class="field"><label for="why">Why is this person wrong?</label><input type="text" id="why" maxlength="500" placeholder="Hobby project, not a company"></div>
           <div class="actions"><button type="button" class="btn danger" data-act="reject">Reject</button><button type="button" class="btn quiet" data-act="cancel">Keep</button></div>`
        : `<div class="actions"><button type="button" class="btn" data-act="approve">Approve</button><button type="button" class="btn quiet" data-act="start-reject">Reject</button></div>
           <p class="hint" style="text-align:center;margin-top:var(--space-3)">Goes to a test inbox, never to them.</p>`}</div>
    </section>`}${personHistory(l)}`;
  if (ui.rejecting) $("why")?.focus();
}
// Contact, fit and history for one person: the spec's enrichment indicators and audit trail, in ruled rows.
const fact = (k, v, n) => `<li><div class="r"><span class="r-k">${k}</span><span class="r-t">${v}</span><span class="r-n">${n || ""}</span></div></li>`;
const NOT = `<span class="muted">Not found</span>`;
const ext = (u, t) => `<a href="${safeUrl(u)}" target="_blank" rel="noopener">${esc(t)}</a>`;
function personFacts(l) {
  const mark = !l.email ? "" : l.email_status === "valid" ? "Verified by Hunter" : "Not verified";
  const site = l.domain ? ext("https://" + l.domain, l.domain) : "";
  const role = l.position || (l.role && l.role !== "unknown" ? cap(l.role) : "");
  return `<section class="block">${secHead("Contact", "How to <em>reach them</em>")}<ul class="rows facts-rows">
      ${fact("Email", l.email ? esc(l.email) : NOT, mark)}
      ${fact("LinkedIn", safeUrl(l.linkedin_url) !== "#" ? ext(l.linkedin_url, "Profile ↗") : NOT)}
      ${fact("Company", l.company || site ? [esc(l.company), site].filter(Boolean).join(" · ") : NOT)}
      ${fact("Role", role ? esc(role) : NOT)}
      ${fact("Location", l.location ? esc(l.location) : NOT)}</ul></section>
    <section class="block">${secHead("Fit", `<span class="num">${esc(l.score)}</span> <em>of 100</em>`)}<ul class="rows facts-rows">
      ${fact("Score", `<span class="bar" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, +l.score || 0))}%"></i></span>`, `${esc(TIER[l.tier] || "Unscored")}${l.tier ? ` (${esc(l.tier)})` : ""}`)}</ul></section>`;
}
function personHistory(l) {
  const hist = ui.data.events.filter(e => e.login === l.login).sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  return `${hist.length ? `<section class="block">${secHead("History", "What <em>happened</em>")}<ul class="rows facts-rows">${hist.map(e => fact(esc(String(e.ts).slice(5, 10) + " " + String(e.ts).slice(11, 16)), `${esc(cap(e.action))}${e.detail && e.action !== "matched" ? ` <small>${esc(e.detail)}</small>` : ""}`, esc(who(e.actor)))).join("")}</ul></section>` : ""}`;
}

const LEVELS = ["shadow", "supervised", "autopilot"];  // mirrors app/trust.py
const LEVEL_SAYS = {shadow: "Watching only", supervised: "You approve each message", autopilot: "Sends on its own"};
// The five trust checks in a founder's words, keyed as app/trust.py names them.
const GATE_SAYS = {self_check: "Its own checks found no problems", agreement: "It agreed with your decisions", false_release: "No message got out that you would have stopped",
  simulation: "Test runs on other products found the right people", regressions: "No old mistake came back"};
const RULE_SAYS = {unsupported_claim: "Says more than they wrote"};
const SPEND = {"lead.enriched": "Looked up a work email", "outreach.sent": "Sent a message", "graph.query": "Searched the map"};
function activityView() {
  const d = ui.data, {events, status, checks, billing, floor} = d, trust = floor?.trust || {};
  const m = d.mail || {}, log = status.log || [];
  const gates = trust.gates || [], met = gates.filter(g => g.passed).length, level = String(trust.level || "unknown");
  const li = LEVELS.indexOf(level), up = li >= 0 && li < LEVELS.length - 1 ? LEVELS[li + 1] : null, target = up || (li > 0 ? LEVELS[li - 1] : null);
  const ag = trust.agreement || {};
  const gateVal = g => g.key === "agreement" && ag.n ? `${ag.agree} of ${ag.n} matched` : String(g.value ?? "–");
  const rows = [...billing.ledger].sort((a, b) => String(b.ts).localeCompare(String(a.ts))), capN = 12, shown = ui.ledgerAll ? rows : rows.slice(0, capN);
  const sending = m.connected ? `Gmail${m.address ? ` · ${esc(m.address)}` : ""}` : m.resend ? "a test inbox" : "nowhere yet";
  const block = (id, k, title, body) => `<section class="sec" id="${id}" style="border-top:0;padding-top:0">${secHead(k, title)}${body}</section>`;
  const logRows = re => { const ls = log.filter(l => STEP_OF.findIndex(x => x.test(l)) === re); return ls.length ? `<ul class="rows">${ls.map(l => `<li><div class="r"><span class="r-k">${TICK}</span><span class="r-t" style="font-size:var(--text-sm)">${esc(cap(PLAIN(strip(l))))}</span><span class="r-n"></span></div></li>`).join("")}</ul>` : ""; };
  const steps = story(d, false), NAMES = ["Read", "Listened", "Found", "Kept", "Wrote and reviewed"];
  const extra = [
    "", "", "",
    "",
    `${checks.length ? `<ul class="rows" style="margin-top:var(--space-8)">${checks.map(c => `<li><div class="r"><span class="r-k">${esc(RULE_SAYS[c.rule] ? "Held" : "Check")}</span><span class="r-t">${esc(c.login)}<small>${esc(RULE_SAYS[c.rule] || String(c.rule).replace(/_/g, " "))}: ${esc(c.detail)}</small></span><span class="r-n">Second model</span></div></li>`).join("")}</ul>` : ""}
     ${events.length ? `<ul class="rows" style="margin-top:var(--space-8)">${events.map(e => `<li><div class="r"><span class="r-k">${esc(e.ts.slice(11, 16))}</span><span class="r-t">${esc(cap(e.action))} <i>${esc(e.login)}</i>${e.detail ? `<small>${esc(e.detail)}</small>` : ""}</span><span class="r-n">${esc(who(e.actor))}</span></div></li>`).join("")}</ul>` : ""}
     <p class="sub">Messages go to ${sending}. ${m.connected || m.resend ? "Never to the person." : "Nothing is sent."}</p>
     ${m.connected ? `<div class="actions"><button type="button" class="btn quiet" data-gmail-disconnect>Disconnect Gmail</button></div>` : m.configured ? `<div class="actions"><a class="btn quiet" href="/api/gmail/connect">Connect Gmail</a></div>` : ""}`,
  ];
  const run = status.running ? `<p class="sub" style="margin:0 0 var(--space-12)"><em>Running now.</em></p>` : !log.length ? `<p class="muted" style="margin:0 0 var(--space-12)">No run yet.</p>` : "";
  return run + steps.map((s, k) => block(`step-${k + 1}`, `0${k + 1} · ${NAMES[k]}`, s.t, `${s.n ? `<p class="sub" style="margin:0 0 var(--space-6)">${s.n}</p>` : ""}${logRows(k)}${extra[k]}`)).join("") +
    (d.map ? block("graph", "The graph", "What the <em>map</em> shows", graphRows(d)) : "") +
    block("trust", "Trust", `${esc(LEVEL_SAYS[level] || cap(level))} · <em>${met} of ${gates.length}</em>`,
      `<ul class="rows">${gates.map(g => `<li><div class="r"><span class="r-k">${g.passed ? TICK : "–"}</span><span class="r-t">${esc(GATE_SAYS[g.key] || g.label)}<span class="visually-hidden">: ${g.passed ? "true" : "not yet"}</span></span><span class="r-n">${esc(gateVal(g))}</span></div></li>`).join("")}</ul>
       <p class="sub">Earshot may send on its own only when all five of these are true.</p>${target ? `<div class="actions"><button type="button" class="btn quiet" data-autonomy="${target}">${up === "autopilot" ? "Ask to send on its own" : up ? "Let it draft for you" : "Go back to approving each"}</button></div>` : ""}`) +
    block("credits", "Credits", `<span class="credits-n num">${Math.floor(billing.credits)}</span> <em>left</em>`,
      `<p class="sub" style="margin:0 0 var(--space-6)">${billing.mode === "flexprice" ? "Metered by Flexprice." : "Local wallet."} Looking up a work email costs ${billing.costs["lead.enriched"]} · sending a message ${billing.costs["outreach.sent"]}.</p>
       ${rows.length ? `<ul class="rows">${shown.map(e => `<li><div class="r ledger"><span class="r-k">${esc(String(e.ts).slice(11, 19))}</span><span class="r-t">${esc(SPEND[e.event] || e.event)}${e.ok ? "" : " (not recorded)"}${e.lead ? ` <i>${esc(e.lead)}</i>` : ""}</span><span class="r-n">${Number(e.credits).toFixed(1)}</span></div></li>`).join("")}</ul>
       ${rows.length > capN && !ui.ledgerAll ? `<p class="center"><button type="button" class="pill" data-ledger-all>See all ${rows.length} <span aria-hidden="true">⌄</span></button></p>` : ""}` : `<p class="muted">No spend yet.</p>`}
       ${billing.mode === "local" ? `<div class="actions"><button type="button" class="btn quiet" data-topup="20">Add 20 credits</button></div>` : ""}`);
}
// Findings computed from the map's edges; each is skipped when the data does not show it.
function graphRows(d) {
  // The server's multi-hop findings lead; the browser's own counts below fill in when they are absent.
  const found = ((d.graph || {}).insights || []).filter(i => i.title && (i.rows || []).length);
  const m = d.map, E = m.edges || [], ids = xs => new Set((xs || []).map(x => x.id));
  const P = ids(m.people), C = ids(m.companies), R = new Map((m.repos || []).map(r => [r.id, r.kind])), pains = new Map((m.pains || []).map(p => [p.id, p.text]));
  const count = (pick) => { const c = new Map(); E.forEach(e => { const k = pick(e); if (k) c.set(k, (c.get(k) || 0) + 1); }); return [...c].sort((a, b) => b[1] - a[1]); };
  const topPain = count(e => pains.has(e.from) && P.has(e.to) ? e.from : null)[0];
  const topRepo = count(e => P.has(e.from) && R.get(e.to) === "competitor" ? e.to : null)[0];
  const shared = count(e => P.has(e.from) && C.has(e.to) ? e.to : null).filter(c => c[1] > 1);
  const people = P.size, stages = d.stages || [], max = Math.max(1, d.leads.length);
  const finds = [
    topPain && topPain[1] > 1 ? fact("Most voiced", esc(headline(pains.get(topPain[0]))), plural(topPain[1], "person", "people")) : "",
    topRepo ? fact("Competitor", `${topRepo[1]} of the ${people} were found complaining on <i>${esc(topRepo[0])}</i>`, "Competitor tracker") : "",
    ...shared.map(([c, k]) => fact("Company", `${k} people at <i>${esc(c)}</i>`, "One account")),
    ...found.filter(i => i.key === "shared_pain" || i.key === "freshest").map(i => fact(i.key === "shared_pain" ? "Shared pain" : "Freshest", esc(i.title), "Graph query")),
  ].join("");
  return `<ul class="rows facts-rows">${fact("Counts", `<span class="num">${[plural(people, "person", "people"), plural(C.size, "company", "companies"), plural(R.size, "tracker", "trackers"), plural(pains.size, "pain", "pains"), plural(E.length, "link", "links")].join(" · ")}</span>`)}
    ${finds}${fact("Conversion", `<span class="conv">${stages.map(s => { const k = d.leads.filter(l => l.stage === s).length;
      return `<span class="conv-row"><span>${esc(s)}</span><span class="bar" aria-hidden="true"><i style="width:${k / max * 100}%"></i></span><span class="num">${k}</span></span>`; }).join("")}</span>`)}</ul>`;
}
// --- render loop -----------------------------------------------------------------

function renderPanel() {
  const v = view(), changed = v !== ui.shown, home = v === "home";
  document.querySelectorAll(".tabs [data-view]").forEach(a => a.dataset.view === v ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  $("home").hidden = !home; $("section").hidden = home;
  if (home) { ui.shown = v; if (changed) window.scrollTo(0, 0); return; }
  $("panel-kicker").textContent = HEADS[v][0];
  $("panel-title").innerHTML = HEADS[v][1];
  $("section-head").hidden = v === "leads" && !!lead();
  const body = $("view");
  // Someone is typing in this section: leave it alone until they are done.
  if (!changed && body.contains(document.activeElement) && document.activeElement.matches("input, textarea")) { detail(); return; }
  if (v === "leads" && !changed && lead() && $("detail") && ui.detailFor === ui.selected) { $("funnel").outerHTML = peopleView().match(/^<p[^]*?<\/p>/)[0]; detail(); }
  else {
    body.innerHTML = {leads: peopleView, activity: activityView}[v]();
    ui.detailKey = ""; ui.detailFor = ui.selected;
    detail();
  }
  reveal();
  if (changed) { window.scrollTo(0, 0); $("panel-title").focus({preventScroll: true}); const a = location.hash.slice(1); if (ANCHORS.test(a)) $(a)?.scrollIntoView(); }
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
  const lay = e.target.closest("[data-layout]");
  if (lay) { ui.layout = lay.dataset.layout; try { localStorage.setItem("earshot.layout", ui.layout); } catch (err) { /* blocked */ } renderPanel(); return; }
  const mv = e.target.closest("[data-move]");
  if (mv) { ui.moving = ui.moving === mv.dataset.move ? null : mv.dataset.move; renderPanel(); if (ui.moving) $(`mv-${ui.moving}`)?.querySelector("button:not([disabled])")?.focus(); return; }
  const to = e.target.closest("[data-stage-to]");
  if (to) return moveTo(to.dataset.login, to.dataset.stageTo);
  const pf = e.target.closest("[data-prof]");
  if (pf) {  // the full profile: one row open at a time, toggled in place like the story line
    const n = +pf.dataset.prof; ui.prof = ui.prof === n ? 0 : n;
    document.querySelectorAll("#profile .st").forEach((li, k) => { const on = ui.prof === k + 1; li.classList.toggle("is-open", on); li.querySelector(".st-btn").setAttribute("aria-expanded", on); li.querySelector(".st-more").inert = !on; });
    return;
  }
  const ex = e.target.closest("[data-expand]");
  if (ex) { try { await api("/api/expansion", {segment: ex.dataset.segment, action: ex.dataset.expand}); } catch (err) { console.error(err); } refresh(true); return; }
  if (e.target.closest("[data-review]")) { document.querySelector(".ask-chip-pill")?.click(); return; }  // the same open the corner chip does
  const sc = e.target.closest("[data-scroll]");
  if (sc) { $(sc.dataset.scroll)?.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}); return; }
  const st = e.target.closest("[data-step]");
  if (st) {  // one step open at a time; toggled in place so a poll never collapses or replays it
    const n = +st.dataset.step; ui.step = ui.step === n ? 0 : n;
    document.querySelectorAll("#how .st").forEach((li, k) => { const on = ui.step === k + 1; li.classList.toggle("is-open", on); li.querySelector(".st-btn").setAttribute("aria-expanded", on); li.querySelector(".st-more").inert = !on; });
    return;
  }
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
// Dragging a card onto a column is a shortcut for its Move menu.
document.addEventListener("dragstart", e => { const c = e.target.closest?.("[data-drag]"); if (c) e.dataTransfer.setData("text/plain", c.dataset.drag); });
document.addEventListener("dragover", e => { const c = e.target.closest?.("[data-drop]"); if (c) { e.preventDefault(); c.classList.add("is-over"); } });
document.addEventListener("dragleave", e => e.target.closest?.("[data-drop]")?.classList.remove("is-over"));
document.addEventListener("drop", e => { const c = e.target.closest?.("[data-drop]"), login = e.dataTransfer.getData("text/plain");
  if (!c || !login) return; e.preventDefault(); c.classList.remove("is-over");
  if (ui.data.leads.find(l => l.login === login)?.stage !== c.dataset.drop) moveTo(login, c.dataset.drop); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && ui.moving) { const m = ui.moving; ui.moving = null; renderPanel(); document.querySelector(`[data-move="${CSS.escape(m)}"]`)?.focus(); e.preventDefault(); return; }
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
