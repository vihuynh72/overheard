// Sections fade and rise once on first view. Without this script everything is visible and still.
(() => {
  if (!("IntersectionObserver" in window)) return document.querySelectorAll(".reveal").forEach(el => el.classList.add("is-in"));
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }), {threshold: 0.12});
  document.querySelectorAll(".reveal").forEach(el => io.observe(el));
})();
