// Every string from GitHub or the model goes through esc(): it is untrusted text.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const safeUrl = u => /^https?:\/\//.test(u || "") ? esc(u) : "#";
const $ = id => document.getElementById(id);
const EXT = `<svg class="icon" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3.5 8.5 8.5 3.5M4.5 3.5h4v4"/></svg>`;
const VIEWS = ["floor", "leads", "map", "pipeline", "profile", "activity"];
const MOUNTED = {floor: ["Floor", "The line of agents, why it can be trusted, and what needs you.", () => EarshotFactory, "floor"], map: ["Who said what", "Each pain, the people who voiced it, their companies, and where they wrote.", () => EarshotMap, "map"]};
const EMAIL = {valid: "verified by Hunter", accept_all: "domain accepts all mail, unconfirmed", invalid: "failed verification", webmail: "personal webmail", disposable: "disposable address", unknown: "could not be verified", pending: "verification pending"};

const ui = {profileEl: Object.assign(document.createElement("div"), {id: "mount-profile"}), data: null, json: "", selected: null, tier: "All", rejecting: false, desc: "", repo: "", error: "", detailKey: ""};

async function api(path, body) {
  const r = await fetch(path, body ? {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)} : {});
  if (!r.ok) {
    const d = (await r.json().catch(() => ({}))).detail;
    throw new Error(typeof d === "string" ? d : "The request was rejected. Check the fields and try again.");
  }
  return r.json();
}
const view = () => VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "floor";
const lead = () => ui.data.leads.find(l => l.login === ui.selected);

// --- shared pieces -----------------------------------------------------------

function intakeForm() {
  const busy = ui.data.status.running;
  return `<form class="intake" id="intake">
    <div class="field"><label for="desc">What do you sell, and who buys it?</label>
      <textarea id="desc" rows="7" required minlength="20" maxlength="20000">${esc(ui.desc)}</textarea>
      <p class="hint">A paragraph is enough: the product, the buyer, how it is priced.</p></div>
    <div class="field"><label for="repo">Your public GitHub repository, if you have one</label>
      <input type="text" id="repo" placeholder="owner/name" pattern="[\\w.\\-]+/[\\w.\\-]+" value="${esc(ui.repo)}">
      <p class="hint">People who open issues there already use the product or tried to.</p></div>
    <div class="actions"><button class="btn" ${busy ? "disabled" : ""}>${busy ? "Working…" : "Find leads"}</button></div>
    ${ui.error ? `<p class="error" role="alert">${esc(ui.error)}</p>` : ""}
  </form>`;
}
const steps = () => `<ol class="steps" aria-live="polite">${ui.data.status.log.map(l => `<li>${esc(l)}</li>`).join("")}</ol>`;
const tier = t => `<span class="tier" data-tier="${esc(t)}">${esc(t)}</span>`;

// --- views ---------------------------------------------------------------------

function leadsView() {
  const {leads, status} = ui.data;
  if (!leads.length) {
    return status.running
      ? `<header class="view-head"><h1>Reading public issue trackers</h1><p>This takes about two minutes. Each step appears here as it finishes.</p></header>${steps()}`
      : `<header class="view-head"><h1>Find people already describing the problem you solve</h1>
         <p>Earshot reads the public issue trackers of your product and its open-source competitors, and keeps the people whose own words match your customer's pain. Every lead links to what they wrote.</p></header>
         ${status.error ? `<p class="error" role="alert">The last run stopped: ${esc(status.error)}</p>` : ""}${intakeForm()}`;
  }
  const shown = leads.filter(l => ui.tier === "All" || l.tier === ui.tier);
  return `<div class="split"><section aria-label="Leads">
    <header class="view-head"><h1>${leads.length} people described a pain you solve</h1>
      <p>Ranked by fit and by how closely their own words match. Choose a person to read the evidence and the draft.</p></header>
    <div class="list-tools"><span class="muted">${shown.length} shown</span>
      <div class="seg" role="group" aria-label="Filter by tier">${["All", "A", "B", "C"].map(t => `<button type="button" data-tier-filter="${t}" aria-pressed="${ui.tier === t}">${t}</button>`).join("")}</div></div>
    <ul>${shown.map(l => `<li><button type="button" class="row" data-open="${esc(l.login)}" aria-pressed="${l.login === ui.selected}">
      <span class="score num">${l.score}</span>
      <span class="who">${esc(l.name)} ${tier(l.tier)}<small>${esc([l.role !== "unknown" && l.role, l.company].filter(Boolean).join(" · ") || "@" + l.login)}</small></span>
      <span class="why">${l.production ? `<span class="flag">In production.</span> ` : ""}${esc(l.reason)}</span>
      <span class="stage">${esc(l.stage)}</span></button></li>`).join("") || `<li class="empty">No leads in this tier.</li>`}</ul>
  </section><aside class="detail" id="detail" aria-label="Lead detail"></aside></div>`;
}

function detail() {
  const el = $("detail");
  if (!el) return;
  const l = lead();
  const key = l ? l.login + l.draft_status + ui.rejecting : "none";
  if (key === ui.detailKey && el.childElementCount) return;  // keep in-progress edits across polls
  ui.detailKey = key;
  if (!l) { el.innerHTML = `<p class="empty">Choose a person on the left. You will see what they wrote, why they were matched, and a draft you can approve, edit or reject.</p>`; return; }
  const done = l.draft_status !== "pending";
  el.innerHTML = `<div>
    <h2>${esc(l.name)}</h2>
    <p class="facts"><a href="${safeUrl(l.url)}" target="_blank" rel="noopener">${l.url.startsWith("https://github.com/") ? "GitHub profile" : "Where they posted"}${EXT}</a>
      ${l.company ? `<span>${esc(l.company)}</span>` : ""}${l.location ? `<span>${esc(l.location)}</span>` : ""}
      <span>${l.email ? esc(l.email) + " · " + esc(EMAIL[l.email_status] || "not verified") : "No email found"}</span>
      ${safeUrl(l.linkedin_url) !== "#" ? `<a href="${safeUrl(l.linkedin_url)}" target="_blank" rel="noopener">LinkedIn${EXT}</a>` : ""}</p>
    <p class="reason">${esc(l.reason)}</p>
    <p class="facts"><span>Score <span class="num">${l.score}</span></span><span>Fit <span class="num">${l.fit}</span>/100</span>
      <span>${l.production ? "Shows production use" : "No sign of production use"}</span>
      <span>Newest evidence <span class="num">${esc(l.newest)}</span></span>
      <span>Cost <span class="num">${(ui.data.billing.by_lead[l.login] || 0).toFixed(1)}</span> credits</span></p>
    ${l.enrich ? `<p class="hint">Contact lookup: ${esc(l.enrich)}</p>` : ""}
    <section class="block"><h3>What they wrote</h3>
      ${l.signals.map(s => `<article class="signal"><a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.title)}${EXT}</a>
        <p class="meta num">${esc(s.repo)} · ${esc(s.created)} · match ${s.match.toFixed(2)}</p>
        <blockquote>${esc(s.excerpt)}${s.excerpt.length >= 300 ? "…" : ""}</blockquote>
        <p class="pain"><span class="muted">Matched the pain:</span> ${esc(s.pain)}</p></article>`).join("")}</section>
    <section class="block"><h3>Draft message${done ? ` · ${esc(l.draft_status)} by ${esc(l.stage_actor)}` : ""}</h3>
      <div class="field" style="margin-top: var(--space-3)"><label for="subj">Subject</label><input type="text" id="subj" maxlength="300" value="${esc(l.subject)}" ${done ? "disabled" : ""}></div>
      <div class="field"><label for="bodyTxt">Message</label><textarea id="bodyTxt" rows="9" maxlength="5000" ${done ? "disabled" : ""}>${esc(l.body)}</textarea></div>
      ${done ? "" : ui.rejecting
        ? `<div class="field"><label for="why">Why is this lead wrong?</label><input type="text" id="why" maxlength="500" placeholder="For example: hobby project, not a company"></div>
           <div class="actions"><button type="button" class="btn danger" data-act="reject">Reject lead</button><button type="button" class="btn quiet" data-act="cancel">Keep reviewing</button></div>`
        : `<div class="actions"><button type="button" class="btn" data-act="approve">Approve message</button><button type="button" class="btn quiet" data-act="start-reject">Reject</button></div>
           <p class="hint">Approving sends this message to the demo inbox, never to the lead, and moves the lead to Contacted.</p>`}
    </section></div>`;
  if (ui.rejecting) $("why")?.focus();
}

function pipelineView() {
  const {leads, stages} = ui.data;
  if (!leads.length) return `<header class="view-head"><h1>Pipeline</h1><p>Leads appear here once a run finishes. Start one from the Leads view.</p></header>`;
  const pct = n => Math.round(100 * n / leads.length);
  const tiers = ["A", "B", "C"];
  return `<header class="view-head"><h1>Pipeline</h1><p>Each lead shows who moved it last: the agent that matched it, or you.</p></header>
    <div class="board">${stages.map(s => { const inS = leads.filter(l => l.stage === s); return `<section class="col" aria-label="${esc(s)}">
      <h2>${esc(s)} <span class="num">${inS.length}</span></h2><p class="pct num">${pct(inS.length)}% of leads</p>
      ${inS.map(l => `<div class="chip"><strong>${esc(l.name)}</strong> ${tier(l.tier)}<div class="muted">by ${esc(l.stage_actor)}</div>
        <select id="st-${esc(l.login)}" data-stage="${esc(l.login)}" aria-label="Move ${esc(l.name)} to stage">${stages.map(x => `<option ${x === l.stage ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></div>`).join("")}
    </section>`; }).join("")}</div>
    <section class="section"><h2>Conversion by tier</h2><div class="table-wrap"><table>
      <thead><tr><th>Tier</th><th class="num">Leads</th>${stages.map(s => `<th class="num">${esc(s)}</th>`).join("")}<th class="num">Approved</th></tr></thead>
      <tbody>${tiers.map(t => { const inT = leads.filter(l => l.tier === t); const decided = inT.filter(l => l.draft_status !== "pending");
        return `<tr><td>${tier(t)}</td><td class="num">${inT.length}</td>${stages.map(s => `<td class="num">${inT.filter(l => l.stage === s).length}</td>`).join("")}
          <td class="num">${decided.length ? Math.round(100 * decided.filter(l => l.draft_status === "approved").length / decided.length) + "%" : "—"}</td></tr>`; }).join("")}</tbody>
    </table></div></section>`;
}

function profileView() {
  return `<header class="view-head"><h1>Customer profile</h1><p>Inferred from your description. The pains below are the exact statements searched for in other people's words.</p></header>
    <div class="profile"><section aria-label="Product intake"><h2 style="margin-bottom:var(--space-4)">Your product</h2>${intakeForm()}</section>
    <section aria-label="Inferred profile"><div id="mount-profile"></div></section></div>`;
}

function activityView() {
  const {events, status, checks, billing} = ui.data;
  return `<header class="view-head"><h1>Activity</h1><p>What the agent did on the last run, and every decision made on a lead.</p></header>
    <section><h2 style="margin-bottom:var(--space-3)">Last run</h2>${status.log.length ? steps() : `<p class="empty">No run yet.</p>`}</section>
    <section class="section"><h2>Self-check</h2>${checks.length
      ? `<p class="muted" style="margin-bottom:var(--space-2)">${checks.length} findings. Each is a rule a lead or draft broke.</p><ul class="log">${checks.map(c => `<li><span class="num muted">${esc(c.rule)}</span><span>${esc(c.login)}</span><span class="what muted">${esc(c.detail)}</span></li>`).join("")}</ul>`
      : `<p class="muted">${ui.data.leads.length ? `All ${ui.data.leads.length} leads pass every rule: evidence linked, score and tier consistent, draft within limits, nothing moved forward without a decision.` : "Runs after each lead run."}</p>`}</section>
    <section class="section"><h2>Credits</h2>
      <p class="muted" style="margin-bottom:var(--space-3)">${billing.mode === "flexprice" ? "Metered by Flexprice." : "Local wallet. Set the Flexprice keys to meter there."} Enriching a lead costs ${billing.costs["lead.enriched"]} credits and an approved message ${billing.costs["outreach.sent"]}. Below ${billing.low_water} credits, weak-fit leads are paused.</p>
      <div class="actions" style="margin:0 0 var(--space-4)"><strong class="num" style="font-size:var(--text-xl);font-weight:500">${billing.credits.toFixed(1)}</strong>
        ${billing.mode === "local" ? `<button type="button" class="btn quiet" data-topup="20">Add 20 credits</button>` : ""}</div>
      ${billing.ledger.length ? `<div class="table-wrap"><table><thead><tr><th>Time</th><th>Event</th><th>Lead</th><th class="num">Credits</th></tr></thead><tbody>${billing.ledger.map(e => `<tr><td class="num muted">${esc(String(e.ts).slice(11, 19))}</td><td>${esc(e.event)}${e.ok ? "" : " (not recorded)"}</td><td>${esc(e.lead)}</td><td class="num">${Number(e.credits).toFixed(1)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">No spend yet.</p>`}</section>
    <section class="section"><h2>Decisions</h2>${events.length ? `<ul class="log">${events.map(e => `<li>
      <span class="num muted">${esc(e.ts.slice(11, 19))}</span><span class="actor" data-actor="${esc(e.actor)}">${esc(e.actor)}</span>
      <span class="what"><strong style="font-weight:500">${esc(e.action)}</strong> ${esc(e.login)}${e.detail ? `<span class="muted"> · ${esc(e.detail)}</span>` : ""}</span></li>`).join("")}</ul>` : `<p class="empty">Nothing recorded yet.</p>`}</section>`;
}

// --- render loop -----------------------------------------------------------------

function render() {
  const v = view(), {status} = ui.data;
  document.querySelectorAll(".tabs a").forEach(a => a.dataset.view === v ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  $("status").dataset.running = status.running;
  $("status").textContent = status.running ? (status.log.at(-1) || "Starting") : status.error ? "Last run stopped with an error" : ui.data.leads.length ? `${ui.data.leads.length} leads · ${ui.data.billing.credits.toFixed(0)} credits` : "No run yet";
  if (MOUNTED[v]) {
    // These views draw themselves and keep their own state, so the mount point is created once and reused.
    const [title, sub, lib, key] = MOUNTED[v];
    if (!$("mount-" + v)) $("view").innerHTML = `<header class="view-head"><h1>${title}</h1><p>${sub}</p></header>${v === "floor" ? `<div id="mount-habitat"></div>` : ""}<div id="mount-${v}"></div>`;
    if (v === "floor") EarshotHabitat.render($("mount-habitat"), ui.data.floor);
    lib().render($("mount-" + v), ui.data[key]);
    return;
  }
  const focusId = document.activeElement?.id;
  $("view").innerHTML = {leads: leadsView, pipeline: pipelineView, profile: profileView, activity: activityView}[v]();
  ui.detailKey = "";
  detail();
  // One element for the profile across re-renders, so it keeps its choices and does not replay its drawing.
  if ($("mount-profile")) { $("mount-profile").replaceWith(ui.profileEl); EarshotProfile.render(ui.profileEl, {icp: ui.data.icp, leads: ui.data.leads}); }
  if (focusId) $(focusId)?.focus();
}

async function refresh(force) {
  try {
    const data = await api("/api/state"), json = JSON.stringify(data);
    if (!force && json === ui.json) return;  // nothing changed: leave focus and typing alone
    ui.data = data; ui.json = json;
    window.EarshotPilot?.update(data);
    if (!ui.desc && data.icp?.description) { ui.desc = data.icp.description; ui.repo = data.icp.product_repo || ""; }
    render();
  } catch (e) { $("status").textContent = "Cannot reach the server"; }
}

document.addEventListener("input", e => {
  if (e.target.id === "desc") ui.desc = e.target.value;
  if (e.target.id === "repo") ui.repo = e.target.value;
});
document.addEventListener("submit", async e => {
  if (e.target.id !== "intake") return;
  e.preventDefault();
  ui.error = "";
  try { await api("/api/run", {description: ui.desc, product_repo: ui.repo.trim()}); location.hash = "leads"; }
  catch (err) { ui.error = err.message; }
  refresh(true);
});
document.addEventListener("change", async e => {
  const login = e.target.dataset.stage;
  if (login) { await api(`/api/leads/${encodeURIComponent(login)}/stage`, {stage: e.target.value}); refresh(true); }
});
document.addEventListener("click", async e => {
  const open = e.target.closest("[data-open]"), act = e.target.closest("[data-act]"), tf = e.target.closest("[data-tier-filter]");
  if (tf) { ui.tier = tf.dataset.tierFilter; render(); }
  const tu = e.target.closest("[data-topup]");
  if (tu) { await api("/api/billing/top-up", {credits: Number(tu.dataset.topup)}); refresh(true); }
  if (open) { ui.selected = open.dataset.open; ui.rejecting = false; render(); if (innerWidth < 960) $("detail").scrollIntoView({behavior: "smooth"}); }
  if (!act) return;
  const a = act.dataset.act;
  if (a === "start-reject" || a === "cancel") { ui.rejecting = a === "start-reject"; ui.detailKey = ""; detail(); return; }
  try { await decideOpen(a, $("why")?.value || ""); }
  catch (err) { act.closest(".block").insertAdjacentHTML("beforeend", `<p class="error" role="alert">${esc(err.message)}</p>`); }
});

// The open lead's draft as shown, so an edit in progress is what gets approved.
async function decideOpen(action, reason) {
  await api(`/api/leads/${encodeURIComponent(ui.selected)}/decision`, {action, subject: $("subj")?.value, body: $("bodyTxt")?.value, reason});
  ui.rejecting = false;
  refresh(true);
}

// --- voice: each spoken action goes through the same route a click would ---------

function voiceContext() {
  const d = ui.data, open = view() === "leads" && lead();  // only a lead on screen can be approved by voice
  ui.spokenAbout = open ? open.login : null;  // the decision applies to this lead and no other
  return {view: view(), open_lead: open && open.draft_status === "pending" ? open.name : "",
    leads: d.leads.map(l => ({name: l.name, score: l.score, tier: l.tier})), level: d.floor.trust.level,
    credits: d.billing.credits, inbox: d.floor.inbox.map(i => i.name)};
}

async function onVoice({action, args}) {
  try {
    if (action === "run") { await api("/api/run", args); location.hash = "floor"; }
    else if (action === "show") location.hash = args.view;
    else if (action === "open_lead") {
      const l = ui.data.leads.find(x => x.name === args.name);
      if (l) document.dispatchEvent(new CustomEvent("earshot:open", {detail: {login: l.login}}));
    }
    else if (action === "approve" || action === "reject") {
      // The reply takes seconds: if a different lead is open by now, do nothing rather than decide on the wrong person.
      if (ui.spokenAbout && ui.spokenAbout === ui.selected && view() === "leads") await decideOpen(action, args.reason || "");
    }
    else if (action === "set_policy") {
      const p = {...args};
      if (p.never_say) p.never_say = [...new Set([...(ui.data.floor.policy.never_say || []), ...p.never_say].map(x => String(x).trim().toLowerCase()))];  // add, never replace
      await api("/api/policy", p);
    }
    else if (action === "autonomy") await api("/api/autonomy", {level: args.level});
    else return;
  } catch (err) { $("status").textContent = err.message; return; }
  refresh(true);
}
EarshotVoice.mount($("voice"), {getContext: () => ui.data ? voiceContext() : {}, onResult: onVoice});
document.addEventListener("earshot:open", e => { ui.selected = e.detail.login; ui.rejecting = false; location.hash = "leads"; ui.data && render(); });
document.addEventListener("earshot:expansion", async e => { try { await api("/api/expansion", e.detail); } catch (err) { console.error(err); } });
document.addEventListener("earshot:autonomy", async e => { try { await api("/api/autonomy", {level: e.detail.level}); } catch (err) { console.error(err); } refresh(true); });
addEventListener("hashchange", () => ui.data && render());
refresh(true);
setInterval(refresh, 2000);
