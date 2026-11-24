// Earshot Ask: the one place the machine asks the founder something. Silent when nothing needs a person;
// otherwise one question at a time, answerable in a word.
// Every string from the server is untrusted: it reaches the page through textContent only.
window.EarshotAsk = (() => {
  "use strict";
  const LOW_CREDITS = 15;   // mirrors billing.LOW_WATER on the server
  const BRIEF_MS = 6000;    // how long a briefing stays before it fades
  const STALE_DAYS = 180;   // a newest signal older than this offers "Too old" as a reason
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };
  const button = (cls, text, kbd) => {
    const b = el("button", cls);
    b.type = "button";
    b.append(el("span", "ask-btn-label", text));
    if (kbd) { const k = el("kbd", "ask-kbd", kbd); k.setAttribute("aria-hidden", "true"); b.append(k); }
    return b;
  };
  const sentence = s => {
    s = String(s || "").replace(/\s+/g, " ").trim();
    const m = s.match(/^.+?[.!?](?=\s|$)/);
    s = m ? m[0] : s;
    return s.length > 320 ? s.slice(0, 317).replace(/\s+\S*$/, "") + "..." : s;
  };
  const dur = () => reduced.matches ? 0 : 240;

  // --- the surface, built once ---
  let note, firstLead = true, root, card, kicker, progress, person, question, why, evidence, subject, answers, yesB, noB, laterB,
    follow, chips, form, input, skipB, fixB, okB, errorP, idle, resume;
  function build() {
    root = el("section", "ask");
    root.setAttribute("aria-label", "Earshot needs you");
    card = el("div", "ask-card");
    const top = el("div", "ask-top");
    kicker = el("p", "ask-kicker");
    progress = el("p", "ask-progress");
    top.append(kicker, progress);
    person = el("p", "ask-person");
    question = el("p", "ask-q");
    question.id = "ask-q";
    question.setAttribute("aria-live", "polite");
    why = el("p", "ask-why");
    evidence = el("p", "ask-evidence");
    subject = el("div", "ask-letter");
    note = el("p", "ask-note", "Yes sends this message. In this demo it goes to a test inbox, never to the person.");

    answers = el("div", "ask-answers");
    yesB = button("ask-btn ask-yes", "Yes", "Y");
    noB = button("ask-btn", "No", "N");
    laterB = button("ask-btn ask-quiet", "Later", "L");
    fixB = button("ask-btn ask-yes", "");
    okB = button("ask-btn ask-quiet", "OK");
    answers.append(yesB, noB, laterB, fixB, okB);
    yesB.addEventListener("click", () => answer("yes"));
    noB.addEventListener("click", () => answer("no"));
    laterB.addEventListener("click", () => answer("later"));
    okB.addEventListener("click", () => finish());
    fixB.addEventListener("click", () => fix());

    follow = el("div", "ask-follow");
    const fq = el("p", "ask-follow-q", "Why not? I will remember it as a rule.");
    fq.id = "ask-why-q";
    chips = el("div", "ask-chips");
    chips.setAttribute("role", "group");
    chips.setAttribute("aria-labelledby", "ask-why-q");
    form = el("form", "ask-form");
    input = el("input", "ask-input");
    Object.assign(input, {type: "text", maxLength: 500, autocomplete: "off", placeholder: "Or say why in your words"});
    input.setAttribute("aria-label", "Why not, in your words");
    const send = button("ask-btn ask-send", "Send");
    send.type = "submit";
    form.append(input, send);
    form.addEventListener("submit", e => { e.preventDefault(); const t = input.value.trim(); if (t) reject(t); });
    skipB = button("ask-link", "No reason, just skip them");
    skipB.addEventListener("click", () => reject(""));
    follow.append(fq, chips, form, skipB);

    errorP = el("p", "ask-error");
    errorP.setAttribute("role", "alert");
    card.append(top, person, question, why, evidence, subject, note, answers, follow, errorP);

    idle = el("p", "ask-idle", "Nothing needs you");
    resume = el("button", "ask-resume");
    resume.type = "button";
    resume.addEventListener("click", () => {
      const k = later.shift();
      const l = k && k.startsWith("lead:") && leadOf(k.slice(5));
      if (l && l.draft_status === "pending" && !(data.status && data.status.running)) show(leadItem(l));
      else if (k === "trust" && trustReady()) show(trustItem());
      else show(next());
    });
    const bar = el("div", "ask-bar");
    bar.append(idle, resume);
    root.append(card, bar);
    document.body.appendChild(root);

    document.addEventListener("keydown", onKey);
    card.hidden = true;
  }

  // --- state ---
  let data = null, actions = null;
  const asked = new Set();      // keys answered or shown once: never asked again this session
  let later = [];               // keys deferred with Later, oldest first: they go to the back of the queue
  let notices = [];             // one-shot items waiting: briefings and stops
  let current = null, step = "ask", busy = false, batchDone = 0, wasRunning = null, lastError = "";
  let swapToken = 0, briefTimer = 0;

  const leadOf = login => (data && data.leads || []).find(l => l.login === login);
  const pendingLeads = () => (data.leads || []).filter(l => l.draft_status === "pending" && !asked.has("lead:" + l.login));
  function trustReady() {
    const t = data.floor && data.floor.trust;
    if (!t || t.level === "autopilot" || asked.has("trust")) return false;
    const g = t.gates || [];
    return g.length > 0 && g.every(x => x.passed) && (t.agreement || {}).n > 0;
  }

  function leadItem(l) {
    const sig = (l.signals || []).slice().sort((a, b) => (b.match || 0) - (a.match || 0))[0];
    const company = String(l.company || "").replace(/^@/, "").trim();
    const name = l.name || l.login;
    const when = sig && sig.created ? new Date(sig.created) : null;
    const whenText = when && !isNaN(when) ? when.toLocaleDateString(undefined, {month: "short", year: "numeric"}) : "";
    return {
      key: "lead:" + l.login, kind: "lead", login: l.login, yesno: true, name, company,
      face: l.login && !l.login.startsWith("web:") ? `https://github.com/${encodeURIComponent(l.login)}.png?size=64` : "",
      kicker: "Your decision",
      q: `Write to ${name}?`,
      why: sentence(l.reason),
      evidence: sig ? [String(sig.title || "").replace(/^\s*\[[A-Za-z ]+\]:?\s*/, ""), [sig.repo, whenText].filter(Boolean).join(", ")] : null,
      subject: l.subject || "", body: l.body || "",
      reasons: reasonsFor(l, company),
    };
  }
  function reasonsFor(l, company) {
    const out = [];
    if (!company) out.push("Not a company");
    const newest = Date.parse(l.newest || "");
    if (newest && Date.now() - newest > STALE_DAYS * 864e5) out.push("Too old");
    if (l.production === false) out.push("Not using it in production");
    for (const r of ["Wrong person", "Already a customer", "Not a fit for us"]) {
      if (out.length >= 4) break;
      if (!out.includes(r)) out.push(r);
    }
    return out.slice(0, 4);
  }
  function trustItem() {
    const a = data.floor.trust.agreement || {};
    const q = a.agree === a.n ? `I matched your last ${a.n} decisions.` : `I matched ${a.agree} of your last ${a.n} decisions.`;
    return {key: "trust", kind: "trust", yesno: true, kicker: "Trust earned", q: q + " Shall I handle these myself from now on?"};
  }

  // The next thing to show, or null. Notices first, then the autopilot offer, then leads by score with deferred ones last.
  function next() {
    if (notices.length) return notices.shift();
    if (trustReady() && !later.includes("trust")) return trustItem();
    if (!data.status || !data.status.running) {
      const leads = pendingLeads().sort((a, b) => (b.score || 0) - (a.score || 0));
      const fresh = leads.find(l => !later.includes("lead:" + l.login));
      if (fresh) return leadItem(fresh);
    }
    // Deferred questions wait quietly until the founder asks for them, so Later never bounces straight back.
    if (batchDone > 0) { batchDone = 0; return {key: "done:" + Date.now(), kind: "brief", kicker: "Done", q: "That is everything for now. I will carry on."}; }
    return null;
  }

  function stillValid(item) {
    if (item.kind === "lead") {
      const l = leadOf(item.login);
      if (!l || l.draft_status !== "pending") return false;
      return !(data.status && data.status.running) || step === "why"; // a run in progress parks a question, never a half-typed reason
    }
    if (item.kind === "trust") return data.floor && data.floor.trust && data.floor.trust.level !== "autopilot";
    return true;
  }

  function watch() {
    const s = data.status || {};
    const err = String(s.error || "").trim();
    if (err && err !== lastError) {
      notices.push({key: "stop:" + err, kind: "stop", kicker: "Stopped", q: "I stopped: " + sentence(err.replace(/^[A-Za-z]+Error:\s*/, "")).replace(/[.!?]?$/, ".")});
    }
    lastError = err;
    if (wasRunning === true && !s.running && !err) {
      const leads = data.leads || [];
      const strong = leads.filter(l => l.tier === "A").length;
      const need = leads.filter(l => l.draft_status === "pending").length;
      const n = (k, one, many) => `${k} ${k === 1 ? one : many}`;
      notices.unshift({key: "brief:" + Date.now(), kind: "brief", kicker: "Run finished",
        q: `Found ${n(leads.length, "person", "people")}. ${strong} ${strong === 1 ? "looks" : "look"} strong. ${need ? need + " need" + (need === 1 ? "s" : "") + " you." : "None need you."}`});
    }
    wasRunning = !!s.running;
    const credits = data.billing && data.billing.credits;
    if (typeof credits === "number" && credits < LOW_CREDITS && !asked.has("credits") && !notices.some(x => x.key === "credits")) {
      notices.push({key: "credits", kind: "stop", kicker: "Stopped", q: "I stopped: credits are low.",
        fix: actions.topUp ? {label: "Add 20 credits", run: () => actions.topUp(20)} : null});
    }
    notices = notices.filter(x => !asked.has(x.key));
  }

  function update(d, a) {
    if (!d) return;
    data = d;
    if (a) actions = a;
    if (!root) build();
    watch();
    if (current && !busy && !stillValid(current)) current = null;  // decided elsewhere, or parked while a run goes
    if (!current) show(next());
    else if (current.kind === "lead") progress.textContent = progressText();
  }

  function showResume() {
    later = later.filter(k => k === "trust" ? trustReady() : (leadOf(k.slice(5)) || {}).draft_status === "pending");
    resume.hidden = !later.length;
    resume.textContent = later.length === 1 ? "1 saved for later. Ask me now" : `${later.length} saved for later. Ask me now`;
    idle.hidden = !!later.length;
  }

  function progressText() {
    const total = batchDone + pendingLeads().length;
    return total > 1 ? `${batchDone + 1} of ${total}` : "";
  }

  // --- showing: one authored motion in, the same motion out ---
  function show(item) {
    const token = ++swapToken, hadFocus = root.contains(document.activeElement);
    clearTimeout(briefTimer);
    current = item;
    step = "ask";
    const wasIn = card.classList.contains("is-in");
    card.classList.remove("is-in");
    const fill = () => {
      if (token !== swapToken) return;
      if (!item) { card.hidden = true; root.dataset.state = "idle"; showResume(); if (hadFocus) resume.focus({preventScroll: true}); return; }
      render(item);
      card.hidden = false;
      root.dataset.state = "open";
      const body = subject.querySelector(".ask-letter-body");
      if (body) subject.classList.toggle("is-long", body.scrollHeight > body.clientHeight + 4);
      void card.offsetWidth;                      // commit the start state so the arrival animates
      card.classList.add("is-in");
      if (hadFocus) (item.yesno ? yesB : item.fix ? fixB : item.kind === "stop" ? okB : card).focus({preventScroll: true});
      if (item.kind === "lead" && actions.open) { try { actions.open(item.login); } catch { /* the card still works without the page behind it */ } }
      if (item.kind === "brief") { asked.add(item.key); briefTimer = setTimeout(() => { if (current === item) finish(); }, BRIEF_MS); }
      if (item.kind === "stop") asked.add(item.key);
    };
    wasIn ? setTimeout(fill, dur()) : fill();
  }

  function render(item) {
    kicker.textContent = item.kicker;
    progress.textContent = item.kind === "lead" ? progressText() : "";
    person.replaceChildren();
    person.hidden = item.kind !== "lead";
    if (item.kind === "lead") {
      const av = el("span", "av");
      av.append(el("span", "av-i", String(item.name).split(/[\s._-]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("")));
      if (item.face) { const img = el("img"); Object.assign(img, {src: item.face, alt: "", width: 32, height: 32, loading: "lazy"}); img.onerror = () => img.remove(); av.append(img); }
      person.append(av, el("span", "ask-name", item.name));
      if (item.company) person.append(el("span", "ask-co", item.company));
    }
    question.textContent = item.q;
    why.textContent = item.why || "";
    why.hidden = !item.why;
    evidence.replaceChildren();
    evidence.hidden = !item.evidence;
    if (item.evidence) {
      evidence.append(el("span", "ask-label", "They wrote"), el("q", "ask-title", item.evidence[0]));
      if (item.evidence[1]) evidence.append(el("span", "ask-where", item.evidence[1]));
    }
    // The draft is shown as the letter it will be, so the decision is made on what will be sent.
    subject.replaceChildren();
    subject.hidden = !item.subject;
    subject.classList.remove("is-open", "is-long");
    if (item.subject) {
      const msg = el("div", "ask-letter-body");
      msg.append(el("strong", "ask-letter-subj", item.subject), el("span", "", item.body || ""));
      const more = button("ask-link ask-more", "Read all");
      more.addEventListener("click", () => { subject.classList.add("is-open"); more.remove(); });
      subject.append(el("p", "ask-label", "The message"), msg, more);
    }
    note.hidden = !(item.kind === "lead" && firstLead);
    if (item.kind === "lead") firstLead = false;
    yesB.hidden = noB.hidden = laterB.hidden = !item.yesno;
    yesB.querySelector(".ask-btn-label").textContent = item.kind === "lead" ? "Yes, send it" : "Yes";
    fixB.hidden = !item.fix;
    if (item.fix) fixB.querySelector(".ask-btn-label").textContent = item.fix.label;
    okB.hidden = item.kind !== "stop";
    chips.replaceChildren(...(item.reasons || []).map(r => {
      const c = button("ask-chip", r);
      c.addEventListener("click", () => reject(r));
      return c;
    }));
    setStep("ask");
    setError("");
    card.dataset.kind = item.kind;
  }

  function setStep(s) {
    step = s;
    follow.hidden = s !== "why";
    answers.hidden = s === "why";
    card.dataset.step = s;
  }
  function setError(msg) { errorP.textContent = msg; errorP.hidden = !msg; }
  function setBusy(b) {
    busy = b;  // aria-disabled, not disabled: the pressed button keeps focus while the answer is sent
    card.setAttribute("aria-busy", String(b));
    for (const n of card.querySelectorAll("button")) n.setAttribute("aria-disabled", String(b));
    input.readOnly = b;
  }

  // --- answering ---
  async function act(run, after) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await run();
      setBusy(false);
      after && after(r);
    } catch (e) {
      setBusy(false);
      setError((e && e.message) || "That did not go through. Try again.");
    }
  }
  function answer(word) {
    if (!current || !current.yesno || step !== "ask" || busy) return;
    if (word === "later") { later = later.filter(k => k !== current.key).concat(current.key); return finish(); }
    if (current.kind === "trust") {
      if (word === "no") { asked.add("trust"); return finish(); }
      return act(() => actions.autonomy("autopilot"), r => {
        asked.add("trust");
        if (r && r.allowed === false && r.note) notices.unshift({key: "note:" + Date.now(), kind: "brief", kicker: "Not yet", q: sentence(r.note)});
        finish();
      });
    }
    if (word === "no") {
      setStep("why");
      const first = chips.querySelector("button") || input;
      first.focus({preventScroll: true});
      return;
    }
    const item = current;
    act(() => actions.decide(item.login, "approve", ""), () => { asked.add(item.key); batchDone++; finish(); });
  }
  function reject(reason) {
    const item = current;
    if (!item || item.kind !== "lead") return;
    act(() => actions.decide(item.login, "reject", reason), () => { asked.add(item.key); batchDone++; input.value = ""; finish(); });
  }
  function fix() {
    const item = current;
    if (item && item.fix) act(item.fix.run, () => finish());
  }
  function finish() {  // each answer path has already recorded what it settled
    current = null;
    show(data ? next() : null);
  }

  function onKey(e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || !current) return;
    if (!root || root.offsetParent === null) return;  // a key must never answer a question the founder cannot see
    const t = e.target;
    if (step === "why" && e.key === "Escape" && !busy) { e.preventDefault(); setStep("ask"); noB.focus({preventScroll: true}); return; }
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    const k = e.key.toLowerCase();
    if (current.yesno && step === "ask" && (k === "y" || k === "n" || k === "l")) {
      e.preventDefault();
      answer({y: "yes", n: "no", l: "later"}[k]);
    }
  }

  return {update};
})();
