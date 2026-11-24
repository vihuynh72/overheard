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
