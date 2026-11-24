// Every string from GitHub or the model goes through esc(): it is untrusted text.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const safeUrl = u => /^https?:\/\//.test(u || "") ? esc(u) : "#";
const $ = id => document.getElementById(id);
const EXT = `<svg class="icon" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3.5 8.5 8.5 3.5M4.5 3.5h4v4"/></svg>`;
const who = a => a === "rep" ? "you" : a;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
// Home is "floor"; every other name is a section that opens over it.
const SECTIONS = {leads: "People", map: "Map", profile: "Buyer", proof: "Proof", activity: "Activity"};
const EMAIL = {valid: "verified", accept_all: "domain accepts all mail", invalid: "failed verification", webmail: "personal webmail", disposable: "disposable address", unknown: "unverified", pending: "verifying"};

const ui = {data: null, json: "", selected: null, tier: "All", rejecting: false, desc: "", repo: "", target: "", manual: false, error: "", detailKey: "", shown: "", open: {},
  profileEl: Object.assign(document.createElement("div"), {id: "mount-profile"}),
  mapEl: Object.assign(document.createElement("div"), {id: "mount-map"}),
  proofEl: Object.assign(document.createElement("div"), {id: "mount-proof"})};

async function api(path, body) {
  const r = await fetch(path, body ? {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)} : {});
  if (!r.ok) {
    const d = (await r.json().catch(() => ({}))).detail;
    throw new Error(typeof d === "string" ? d : "The request was rejected. Try again.");
  }
  return r.json();
}
const view = () => { const h = location.hash.slice(1); return SECTIONS[h] ? h : "floor"; };
const lead = () => ui.data.leads.find(l => l.login === ui.selected);
// A web lead whose only name is the site it was found on.
const nameOf = l => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(l.name || "") ? `Someone on ${l.name.replace(/^www\./i, "")}` : (l.name || l.login);
const tier = t => `<span class="tier" data-tier="${esc(t)}">${esc(t)}</span>`;
const steps = () => `<ol class="steps">${ui.data.status.log.map(l => `<li>${esc(l)}</li>`).join("")}</ol>`;
const fold = (key, title, line, body) => `<details class="fold" data-fold="${key}" ${ui.open[key] ? "open" : ""}><summary><h2>${title}</h2><span class="fold-line">${line}</span></summary><div class="fold-body">${body}</div></details>`;

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
    needs ? `${needs} ${needs === 1 ? "needs" : "need"} you.` : "Nothing needs you."].join(" ");
}

function homeStrip() {
  const {floor, billing} = ui.data, gates = floor.trust?.gates || [];
  return `<span class="strip-say">${esc(ui.data.status.running ? "Running" : homeLine())}</span><a href="#proof"><span class="k">Autonomy</span> ${esc(floor.trust?.level || "unknown")}</a>
    <a href="#proof"><span class="k">Gates</span> <span class="num">${gates.filter(g => g.passed).length} of ${gates.length}</span></a>
    <a href="#activity"><span class="k">Credits</span> <span class="num">${billing.credits.toFixed(1)}</span></a>`;
}

// --- who the customer is, from the inferred profile and the people who proved it ---
const vals = f => Array.isArray(f) ? f : (f?.values || []);
const lowerFirst = t => /^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t;
const words = (t, n) => { const w = String(t).split(/\s+/); return w.length > n ? w.slice(0, n).join(" ") + "…" : t; };
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
const orList = a => a.length > 1 ? a.slice(0, -1).join(", ") + " or " + a.at(-1) : a[0] || "";

function customerLine(icp) {
  const role = vals(icp.personas)[0], kind = vals(icp.industries)[0], trig = vals(icp.triggers)[0];
  if (!role) return icp.product ? `Working out who buys ${words(icp.product.split(":")[0], 6)}.` : "Working out who your customer is.";
  return `Your customer: ${lowerFirst(role.replace(/\s*\(.*?\)/g, ""))}${kind && !/\sat\s/i.test(role) ? ` at ${kind.replace(/\s+compan(y|ies)$/i, "")} companies` : ""}${trig ? `, ${lowerFirst(trig)}` : ""}.`;
}

function customerFacts(icp, leads) {
  const sigs = leads.flatMap(l => l.signals.map(s => ({...s, login: l.login})));
  const voiced = p => new Set(sigs.filter(s => s.pain === p).map(s => s.login)).size;
  const pains = (icp.pains || []).map(p => [p, voiced(p)]).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const tally = list => Object.entries(list.reduce((m, k) => (k && (m[k] = (m[k] || 0) + 1), m), {})).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const where = icp.channels?.length ? icp.channels.slice(0, 3).map(c => [c.domain, 0]) : tally(sigs.map(s => /^https?:\/\/(www\.)?github\.com\//.test(s.url) ? s.repo : hostOf(s.url)));
  const top = [...leads].sort((a, b) => b.score - a.score);
  const say = icp.learned_pains?.length ? icp.learned_pains.slice(0, 2) : top.slice(0, 1).flatMap(l => l.signals.slice(0, 1).map(s => s.title));
  const fact = (k, items) => `<div class="fact"><h2>${k}</h2><ul>${items || `<li class="muted">Not known yet</li>`}</ul></div>`;
  return `<div class="facts-row">
    ${fact("What hurts", pains.map(([p, n]) => `<li>${esc(words(p, 9))}${n ? ` <span class="num muted">${n}</span>` : ""}</li>`).join(""))}
    ${fact("Where they talk", where.map(([d, n]) => `<li>${esc(d)}${n ? ` <span class="num muted">${n}</span>` : ""}</li>`).join(""))}
    ${fact("How they say it", say.map(t => `<li class="quote">“${esc(words(t, 14))}”</li>`).join(""))}
  </div>`;
}

function proofPeople(leads) {
  if (!leads.length) return "";
  const top = [...leads].sort((a, b) => b.score - a.score).slice(0, 3);
  return `<section class="said" aria-labelledby="said-h"><h2 id="said-h">People who said it</h2><ul>
    ${top.map(l => { const s = l.signals[0] || {}; return `<li><button type="button" class="said-who" data-open="${esc(l.login)}" data-go-leads>${esc(nameOf(l))}</button>
      <span class="muted">${esc(l.company || "")}</span>
      <a class="said-words" href="${safeUrl(s.url)}" target="_blank" rel="noopener">“${esc(words(s.title || l.reason, 12))}”${EXT}</a></li>`; }).join("")}
    </ul><a class="see-all" href="#leads">See all ${leads.length}</a></section>`;
}

function homeCustomer() {
  const {icp, leads, status} = ui.data;
  const head = status.running ? (status.log.at(-1) || "Starting.") : status.error ? `The last run stopped: ${status.error}` : customerLine(icp || {});
  return `<h1 class="home-line" id="home-line" data-running="${!!status.running}">${esc(head)}</h1>
    ${icp ? customerFacts(icp, leads) : ""}${proofPeople(leads)}`;
}

function intakeForm() {
  const busy = ui.data.status.running;
  return `<form class="intake" id="intake" novalidate>
    <h1><label for="target">Your website or GitHub repository</label></h1>
    <div class="intake-row"><input type="text" id="target" placeholder="flexprice.io" maxlength="200" autocomplete="url" value="${esc(ui.target)}">
      <button class="btn" ${busy ? "disabled" : ""}>${busy ? "Working…" : "Find leads"}</button></div>
    ${ui.error ? `<p class="error" role="alert">${esc(ui.error)}</p>` : ""}
  </form>`;
}

function renderHome() {
  const fresh = !ui.data.leads.length && !ui.data.status.running;
  document.body.classList.toggle("is-fresh", fresh);
  const slot = $("home-top");
  if (fresh) {
    // Rebuild the form only when it is not being typed in.
    if (!slot.querySelector("#intake") || !slot.contains(document.activeElement)) slot.innerHTML = intakeForm();
  } else slot.innerHTML = homeCustomer();
  $("home-strip").innerHTML = fresh ? "" : homeStrip();
  EarshotHabitat.render($("mount-habitat"), ui.data.floor);
}

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
    `<ul class="people">${shown.map(l => `<li><button type="button" class="row" data-open="${esc(l.login)}">
      <span class="score num">${l.score}</span>
      <span class="who">${esc(nameOf(l))} ${tier(l.tier)}<small>${esc([l.role !== "unknown" && l.role, l.company].filter(Boolean).join(" · ") || (l.login.startsWith("web:") ? "" : "@" + l.login))}</small></span>
      <span class="why">${esc(l.reason)}</span>
      <span class="stage">${esc(l.stage)}</span></button></li>`).join("") || `<li class="empty">No one in this tier.</li>`}</ul>`;
}
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
  el.innerHTML = `<h2>${esc(nameOf(l))} ${tier(l.tier)}</h2>
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
    <section class="block"><h3>Draft${done ? ` · ${esc(l.draft_status)} by ${esc(who(l.stage_actor))}` : ""}</h3>
      <div class="field"><label for="subj">Subject</label><input type="text" id="subj" maxlength="300" value="${esc(l.subject)}" ${done ? "disabled" : ""}></div>
      <div class="field"><label for="bodyTxt">Message</label><textarea id="bodyTxt" rows="9" maxlength="5000" ${done ? "disabled" : ""}>${esc(l.body)}</textarea></div>
      ${done ? "" : ui.rejecting
        ? `<div class="field"><label for="why">Why is this lead wrong?</label><input type="text" id="why" maxlength="500" placeholder="Hobby project, not a company"></div>
           <div class="actions"><button type="button" class="btn danger" data-act="reject">Reject lead</button><button type="button" class="btn quiet" data-act="cancel">Keep</button></div>`
        : `<div class="actions"><button type="button" class="btn" data-act="approve">Approve</button><button type="button" class="btn quiet" data-act="start-reject">Reject</button></div>
           <p class="hint">Goes to the demo inbox, never to the lead.</p>`}
    </section>`;
  if (ui.rejecting) $("why")?.focus();
}

function buyerView() {
  const icp = ui.data.icp;
  const from = icp?.sources?.length ? `<p class="hint">Read from ${icp.sources.map(u => /^https?:\/\//.test(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u.replace(/^https?:\/\//, ""))}</a>` : esc(u)).join(", ")}</p>` : "";
  const busy = ui.data.status.running;
  return `${from}<div id="mount-profile"></div>
    <details class="fold" data-fold="manual" ${ui.open.manual ? "open" : ""}><summary><h2>Describe it yourself</h2><span class="fold-line">If the site got it wrong</span></summary>
      <form class="fold-body intake-manual" id="intake-manual" novalidate>
        <div class="field"><label for="desc">What you sell, and who buys it</label><textarea id="desc" rows="6" maxlength="20000">${esc(ui.desc)}</textarea></div>
        <div class="field"><label for="repo">Public GitHub repository</label><input type="text" id="repo" placeholder="owner/name" value="${esc(ui.repo)}"></div>
        <div class="actions"><button class="btn" ${busy ? "disabled" : ""}>${busy ? "Working…" : "Find leads"}</button></div>
        ${ui.error ? `<p class="error" role="alert">${esc(ui.error)}</p>` : ""}
      </form></details>`;
}

function activityView() {
  const {events, status, checks, billing, leads, stages} = ui.data;
  const m = ui.data.mail || {};
  const sending = m.connected ? `Gmail${m.address ? ` · ${esc(m.address)}` : ""}` : m.resend ? "Resend, demo inbox" : "Not set up";
  const ledger = billing.ledger.length ? `<div class="table-wrap"><table><thead><tr><th>Time</th><th>Event</th><th>Lead</th><th class="num">Credits</th></tr></thead><tbody>${billing.ledger.map(e => `<tr><td class="num muted">${esc(String(e.ts).slice(11, 19))}</td><td>${esc(e.event)}${e.ok ? "" : " (not recorded)"}</td><td>${esc(e.lead)}</td><td class="num">${Number(e.credits).toFixed(1)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">No spend yet.</p>`;
  const audit = (checks.length ? `<ul class="log">${checks.map(c => `<li><span class="num muted">${esc(c.rule)}</span><span>${esc(c.login)}</span><span class="what muted">${esc(c.detail)}</span></li>`).join("")}</ul>` : `<p class="muted">Every lead passes every rule.</p>`) +
    (events.length ? `<ul class="log">${events.map(e => `<li><span class="num muted">${esc(e.ts.slice(11, 19))}</span><span class="actor" data-actor="${esc(who(e.actor))}">${esc(who(e.actor))}</span>
      <span class="what">${esc(e.action)} ${esc(e.login)}${e.detail ? `<span class="muted"> · ${esc(e.detail)}</span>` : ""}</span></li>`).join("")}</ul>` : "");
  const conv = `<div class="table-wrap"><table><thead><tr><th>Tier</th><th class="num">Leads</th>${stages.map(s => `<th class="num">${esc(s)}</th>`).join("")}<th class="num">Approved</th></tr></thead>
    <tbody>${["A", "B", "C"].map(t => { const inT = leads.filter(l => l.tier === t), decided = inT.filter(l => l.draft_status !== "pending");
      return `<tr><td>${tier(t)}</td><td class="num">${inT.length}</td>${stages.map(s => `<td class="num">${inT.filter(l => l.stage === s).length}</td>`).join("")}
        <td class="num">${decided.length ? Math.round(100 * decided.filter(l => l.draft_status === "approved").length / decided.length) + "%" : "–"}</td></tr>`; }).join("")}</tbody></table></div>`;
  return fold("run", "Last run", status.running ? "Running" : status.log.length ? plural(status.log.length, "step", "steps") : "None yet", status.log.length ? steps() : `<p class="muted">No run yet.</p>`) +
    fold("credits", "Credits", `<span class="num">${billing.credits.toFixed(1)}</span> left`,
      `<p class="muted">${billing.mode === "flexprice" ? "Metered by Flexprice." : "Local wallet."} A lead costs ${billing.costs["lead.enriched"]}, a sent message ${billing.costs["outreach.sent"]}.</p>
       ${billing.mode === "local" ? `<div class="actions"><button type="button" class="btn quiet" data-topup="20">Add 20 credits</button></div>` : ""}${ledger}`) +
    fold("sending", "Sending", sending, `<p class="muted">${m.connected || m.resend ? "To the demo inbox, never to the lead." : "Approvals are recorded; nothing is sent."}</p>
      <div class="actions">${m.connected ? `<button type="button" class="btn quiet" data-gmail-disconnect>Disconnect Gmail</button>` : m.configured ? `<a class="btn" href="/api/gmail/connect">Connect Gmail</a>` : ""}</div>`) +
    fold("audit", "Audit", `${plural(checks.length, "finding", "findings")} · ${plural(events.length, "decision", "decisions")}`, audit) +
    fold("conversion", "Conversion by tier", plural(leads.length, "lead", "leads"), conv);
}

// --- render loop -----------------------------------------------------------------

function renderPanel() {
  const v = view(), panel = $("panel");
  const changed = v !== ui.shown;
  document.querySelectorAll(".tabs [data-view]").forEach(b => b.dataset.view === v ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  panel.classList.toggle("is-open", v !== "floor");
  panel.inert = v === "floor";
  if (v === "floor") { if (changed && SECTIONS[ui.shown]) document.querySelector(`.tabs [data-view="${ui.shown}"]`)?.focus(); ui.shown = v; return; }
  $("panel-title").textContent = SECTIONS[v];
  const body = $("view");
  // Someone is typing in this section: leave it alone until they are done.
  if (!changed && body.contains(document.activeElement) && document.activeElement.matches("input, textarea")) { detail(); return; }
  if (v === "map") { if (body.firstChild !== ui.mapEl) body.replaceChildren(ui.mapEl); EarshotMap.render(ui.mapEl, ui.data.map); }
  else if (v === "proof") { if (body.firstChild !== ui.proofEl) body.replaceChildren(ui.proofEl); EarshotFactory.render(ui.proofEl, ui.data.floor); }
  else if (v === "leads" && !changed && lead() && $("detail") && ui.detailFor === ui.selected) { $("funnel").outerHTML = peopleView().match(/^<p[^]*?<\/p>/)[0]; detail(); }
  else {
    body.innerHTML = {leads: peopleView, profile: buyerView, activity: activityView}[v]();
    ui.detailKey = ""; ui.detailFor = ui.selected;
    detail();
    // One element for the profile across re-renders, so it keeps its choices and does not replay its drawing.
    if ($("mount-profile")) { $("mount-profile").replaceWith(ui.profileEl); EarshotProfile.render(ui.profileEl, {icp: ui.data.icp, leads: ui.data.leads}); }
  }
  if (changed) { panel.scrollTop = 0; if (ui.shown === "floor" || !ui.shown) $("panel-title").focus({preventScroll: true}); }
  ui.shown = v;
}

function render() { renderHome(); renderPanel(); }

async function refresh(force) {
  try {
    const data = await api("/api/state"), json = JSON.stringify(data);
    if (!force && json === ui.json) return;  // nothing changed: leave focus and typing alone
    ui.data = data; ui.json = json;
    window.EarshotPilot?.update(data);
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
    if (!typed && !target) throw new Error("Enter your website or GitHub repository.");
    await api("/api/run", typed ? {description: ui.desc, product_repo: ui.repo.trim()} : {target});
    location.hash = "floor";
  } catch (err) { ui.error = err.message; }
  if (e.target.id === "intake") $("home-top").innerHTML = "";  // let the next render show the error or the line
  refresh(true);
});
document.addEventListener("click", async e => {
  const nav = e.target.closest(".tabs [data-view]");
  if (nav) { if (nav.dataset.view === "leads") { ui.selected = null; if (view() === "leads") renderPanel(); } location.hash = nav.dataset.view; return; }
  if (e.target.closest("[data-close]")) { location.hash = "floor"; return; }
  if (e.target.closest("[data-back]")) { ui.selected = null; ui.rejecting = false; renderPanel(); return; }
  const open = e.target.closest("[data-open]"), act = e.target.closest("[data-act]"), tf = e.target.closest("[data-tier-filter]");
  if (tf) { ui.tier = tf.dataset.tierFilter; renderPanel(); }
  const tu = e.target.closest("[data-topup]");
  if (tu) { await api("/api/billing/top-up", {credits: Number(tu.dataset.topup)}); refresh(true); }
  if (e.target.closest("[data-gmail-disconnect]")) { await api("/api/gmail/disconnect", {}); refresh(true); }
  if (open && open.dataset.goLeads !== undefined) { ui.selected = open.dataset.open; ui.detailFor = null; location.hash = "leads"; renderPanel(); return; }
  if (open) { ui.selected = open.dataset.open; ui.rejecting = false; ui.detailFor = null; renderPanel(); $("panel").scrollTop = 0; }
  if (!act) return;
  const a = act.dataset.act;
  if (a === "start-reject" || a === "cancel") { ui.rejecting = a === "start-reject"; ui.detailKey = ""; detail(); return; }
  try { await decideOpen(a, $("why")?.value || ""); }
  catch (err) { act.closest(".block").insertAdjacentHTML("beforeend", `<p class="error" role="alert">${esc(err.message)}</p>`); }
});
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || view() === "floor" || e.defaultPrevented || document.activeElement?.closest(".ask")) return;
  location.hash = "floor";
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
document.addEventListener("earshot:expansion", async e => { try { await api("/api/expansion", e.detail); } catch (err) { console.error(err); } });
document.addEventListener("earshot:autonomy", async e => { try { await api("/api/autonomy", {level: e.detail.level}); } catch (err) { console.error(err); } refresh(true); });
addEventListener("hashchange", () => {
  if (location.hash === "#pipeline") return location.replace("#leads");
  ui.data && renderPanel();
});
if (location.hash === "#pipeline") location.replace("#leads");
refresh(true);
setInterval(refresh, 2000);
