// Landing page motion. Without this script every element is visible and still; with reduced motion nothing drifts.
(() => {
  const root = document.documentElement;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.add("js");

  // The field drifts with the reader's scroll, alternate rows in opposite directions; it never moves on its own.
  const tracks = [...document.querySelectorAll(".track")];
  if (!still && tracks.length) {
    let queued = false;
    const drift = () => {
      queued = false;
      const y = scrollY;
      tracks.forEach((t, k) => { const v = (k % 2 ? 1 : -1) * y * (0.25 + k * 0.08); t.style.transform = "translateX(" + (v - (k % 2 ? 160 : 0)).toFixed(1) + "px)"; });
    };
    addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(drift); } }, { passive: true });
    drift();
  }

  // Heard: the three real phrasings light up in turn, and each joins the list beside the headline.
  const heardItems = document.querySelectorAll(".heard-list li");
  const said = (i) => document.querySelectorAll('.said[data-i="' + i + '"]');
  if (still) heardItems.forEach((li) => li.classList.add("is-in"));
  else {
    let i = 0;
    const tick = () => {
      document.querySelectorAll(".said.is-heard").forEach((s) => s.classList.remove("is-heard"));
      const k = i % heardItems.length;
      said(k).forEach((s) => s.classList.add("is-heard"));
      if (heardItems[k]) heardItems[k].classList.add("is-in");
      i++;
    };
    setTimeout(() => { tick(); setInterval(tick, 3200); }, 900);
  }

  // One-time reveals for the miniature and the limits ledger.
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
  }), { threshold: 0.35 });
  document.querySelectorAll(".mini, .nots").forEach((el) => io.observe(el));

  // The line between agents draws as the reader scrolls through it.
  const agents = document.querySelector(".agents");
  if (agents && !still) {
    let queued = false;
    const draw = () => {
      queued = false;
      const r = agents.getBoundingClientRect(), vh = innerHeight;
      const p = Math.min(1, Math.max(0, (vh * 0.85 - r.top) / (r.height + vh * 0.3)));
      agents.style.setProperty("--drawn", p.toFixed(3));
    };
    addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(draw); } }, { passive: true });
    draw();
  }

  // Creatures in the habitat's hand: a wobbly seeded body, two eyes, a 1.4px line.
  const hash = (s) => { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const rng = (seed) => () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const NS = "http://www.w3.org/2000/svg";
  document.querySelectorAll(".creature").forEach((box) => {
    const r = rng(hash(box.dataset.seed || "x"));
    const R = 17 + r() * 6, squash = 0.75 + r() * 0.35, n = 9, pts = [];
    for (let k = 0; k < n; k++) {
      const a = (k / n) * Math.PI * 2, w = R * (0.88 + r() * 0.24);
      pts.push([32 + Math.cos(a) * w, 36 + Math.sin(a) * w * squash]);
    }
    let d = "M" + pts[0].map((v) => v.toFixed(1)).join(" ");
    for (let k = 0; k < n; k++) {
      const p1 = pts[(k + 1) % n], p2 = pts[(k + 2) % n];
      const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
      d += " Q" + p1[0].toFixed(1) + " " + p1[1].toFixed(1) + " " + mx.toFixed(1) + " " + my.toFixed(1);
    }
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 64 64");
    svg.setAttribute("aria-hidden", "true");
    const ex = 5 + r() * 3, ey = 33 - R * squash * 0.25;
    const body = '<path d="' + d + 'Z" fill="var(--color-paper-3)" fill-opacity="0.5" stroke="var(--color-ink)" stroke-width="1.4" stroke-linejoin="round"/>';
    const eyes = '<circle cx="' + (32 - ex) + '" cy="' + ey + '" r="1.8" fill="var(--color-ink)"/><circle cx="' + (32 + ex) + '" cy="' + ey + '" r="1.8" fill="var(--color-ink)"/>';
    const ear = '<path d="M' + (32 + R * 0.6) + " " + (36 - R * squash * 0.7) + ' q4 -6 9 -4" fill="none" stroke="var(--color-accent)" stroke-width="1.4" stroke-linecap="round"/>';
    svg.innerHTML = body + eyes + ear;
    box.appendChild(svg);
  });
})();
