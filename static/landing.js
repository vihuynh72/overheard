// Marks the "How it works" step nearest the middle of the viewport. Without this script every step stays fully visible.
(() => {
  const steps = document.querySelectorAll(".step");
  if (!steps.length || !("IntersectionObserver" in window)) return;
  document.documentElement.classList.add("js");
  const mark = (el) => steps.forEach((s) => (s === el ? s.setAttribute("aria-current", "step") : s.removeAttribute("aria-current")));
  mark(steps[0]);
  const io = new IntersectionObserver(
    (entries) => entries.forEach((e) => e.isIntersecting && mark(e.target)),
    { rootMargin: "-45% 0px -45% 0px" }
  );
  steps.forEach((s) => io.observe(s));
})();

// A live line under the hero, read from the running workbench. Numbers only, no names; textContent only.
(() => {
  const box = document.querySelector(".live"), text = box && box.querySelector(".live-text");
  if (!box || !text) return;
  let facts = [], i = 0;
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
  async function pull() {
    try {
      const d = await (await fetch("/api/state")).json();
      const leads = d.leads || [], fl = d.floor || {}, tr = fl.trust || {}, gates = tr.gates || [];
      const done = leads.filter((l) => l.draft_status === "approved").length;
      const working = (fl.agents || []).filter((a) => a.state === "working").map((a) => a.name);
      facts = [
        working.length ? working.join(", ") + " working right now" : null,
        leads.length ? plural(leads.length, "person", "people") + " found, each linked to what they wrote" : null,
        leads.length ? done + " approved, " + (fl.inbox || []).length + " waiting on the founder" : null,
        gates.length ? gates.filter((g) => g.passed).length + " of " + gates.length + " trust gates met, running " + (tr.level || "supervised") : null,
      ].filter(Boolean);
      if (facts.length) { box.hidden = false; if (!text.textContent) show(); }
    } catch { /* the landing page works without the workbench */ }
  }
  function show() {
    if (!facts.length) return;
    const next = facts[i++ % facts.length];
    if (still.matches) { text.textContent = next; return; }
    text.classList.add("is-out");
    setTimeout(() => { text.textContent = next; text.classList.remove("is-out"); }, 400);
  }
  pull();
  setInterval(pull, 15000);
  setInterval(show, 4000);
})();
