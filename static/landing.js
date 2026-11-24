// Landing page motion: one-time reveals only. Without this script every element is visible and still.
(() => {
  document.documentElement.classList.add("js");
  document.querySelectorAll(".heard-list li").forEach((li) => li.classList.add("is-in"));
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
  }), { threshold: 0.35 });
  document.querySelectorAll(".mini, .nots").forEach((el) => io.observe(el));
})();
