// Voice control. Hold the button to talk (or click to start and click to stop); the words go to /api/voice,
// the result goes to onResult, and the reply is spoken through /api/speak. Server text is untrusted: textContent only.
window.EarshotVoice = (() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const BARS = 16;
  const HOLD_MS = 450; // a press longer than this is hold-to-talk: release stops. Shorter is click-to-toggle.
  const LABEL = {idle: "Talk to Earshot", listening: "Listening. Release or click to stop", thinking: "Thinking",
    speaking: "Speaking. Click to interrupt", error: "Try again"};
  const still = matchMedia("(prefers-reduced-motion: reduce)");

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  async function post(path, body) {
    const r = await fetch(path, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
    if (!r.ok) throw new Error(r.status);
    return r;
  }

  function mount(container, {getContext = () => ({}), onResult = () => {}} = {}) {
    const root = el("div", "voice");
    const btn = el("button", "voice-btn");
    btn.type = "button";
    const meter = el("span", "voice-meter");
    meter.setAttribute("aria-hidden", "true");
    const bars = Array.from({length: BARS}, () => meter.appendChild(el("span", "voice-bar")));
    const label = el("span", "voice-label");
    btn.append(meter, label);

    const line = el("p", "voice-line");
    line.setAttribute("aria-live", "polite");
    const heard = el("span", "voice-heard");
    const reply = el("span", "voice-reply");
    line.append(heard, reply);
    const retry = el("button", "voice-retry", "Try again");
    retry.type = "button";
    retry.hidden = true;

    const form = el("form", "voice-type");
    const inputId = "voice-text-" + Math.random().toString(36).slice(2, 8);
    const lab = el("label", "voice-type-label", "Or type what you want done");
    lab.htmlFor = inputId;
    const input = el("input", "voice-input");
    Object.assign(input, {id: inputId, type: "text", maxLength: 500, autocomplete: "off", placeholder: "Show me the leads"});
    const send = el("button", "voice-send", "Send");
    send.type = "submit";
    form.append(lab, input, send);
    form.hidden = !!SR; // with no speech recognition the field is the way in; with it, only after a mic problem

    root.append(btn, line, retry, form);
    container.appendChild(root);

    let state = "idle", rec = null, pressedAt = 0, retryText = "", audio = null, stream = null, ctx = null, analyser = null, raf = 0, t0 = 0;
    const freq = new Uint8Array(32);

    function setState(s) {
      state = s;
      root.dataset.state = s;
      btn.setAttribute("aria-pressed", String(s === "listening"));
      btn.setAttribute("aria-disabled", String(s === "thinking"));
      label.textContent = LABEL[s];
      retry.hidden = s !== "error";
      container.dispatchEvent(new CustomEvent("earshot-voice-state", {detail: {state: s}}));
      s === "idle" || s === "error" ? stopLoop() : startLoop();
      if (!raf) paint(0);
    }

    // --- the meter: real microphone level while listening, a travelling swell while thinking and speaking ---
    function level(i, t) {
      if (state === "idle" || state === "error") return 0.12;
      if (still.matches) return {listening: 0.28, thinking: 0.15 + 0.5 * i / BARS, speaking: 0.4}[state] ?? 0.12;
      if (state === "listening" && analyser) {
        analyser.getByteFrequencyData(freq);
        return Math.min(1, 0.1 + (freq[Math.floor(i * freq.length / BARS)] / 255) * 1.4);
      }
      const phase = state === "thinking" ? t / 380 - i * 0.45 : t / 260 + i * 0.7;
      return 0.14 + 0.42 * (0.5 + 0.5 * Math.sin(phase)) * (state === "listening" ? 0.5 : 1);
    }
    function paint(t) {
      bars.forEach((b, i) => { b.style.transform = `scaleY(${level(i, t).toFixed(3)})`; });
    }
    function frame(now) {
      t0 = t0 || now;
      paint(now - t0);
      raf = requestAnimationFrame(frame);
    }
    function startLoop() { if (!raf && !still.matches) raf = requestAnimationFrame(frame); }
    function stopLoop() { cancelAnimationFrame(raf); raf = 0; t0 = 0; }
    still.addEventListener("change", () => { stopLoop(); setState(state); });

    async function openMic() { // the level only; a denied or busy mic just leaves the swell, recognition still runs
      try {
        stream = await navigator.mediaDevices.getUserMedia({audio: true});
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = ctx.createAnalyser();
        analyser.fftSize = 64;
        ctx.createMediaStreamSource(stream).connect(analyser);
      } catch { closeMic(); }
    }
    function closeMic() {
      if (stream) stream.getTracks().forEach(t => t.stop());
      if (ctx) ctx.close().catch(() => {});
      stream = ctx = analyser = null;
    }

    // --- listening ---
    function listen() {
      stopAudio();
      retryText = "";
      heard.textContent = reply.textContent = "";
      form.hidden = !!SR;
      let finalText = "";
      rec = new SR();
      rec.lang = navigator.language || "en-US";
      rec.interimResults = true;
      rec.continuous = false;
      rec.onresult = e => {
        let interim = "";
        for (const r of e.results) r.isFinal ? (finalText += r[0].transcript) : (interim += r[0].transcript);
        heard.textContent = (finalText + interim).trim();
      };
      rec.onerror = e => {
        rec = null;
        if (e.error === "aborted") return;
        const denied = e.error === "not-allowed" || e.error === "service-not-allowed";
        fail(denied ? "The microphone is blocked. Allow it in the browser, or type instead."
          : e.error === "no-speech" ? "I did not hear anything." : "Speech recognition stopped. Try again, or type instead.", denied);
      };
      rec.onend = () => {
        const done = rec; rec = null; closeMic();
        if (!done || state !== "listening") return;
        finalText.trim() ? submit(finalText.trim()) : fail("I did not catch that.");
      };
      setState("listening");
      openMic();
      try { rec.start(); } catch { fail("Speech recognition could not start.", true); }
    }
    function stopListening() { if (rec) rec.stop(); }

    // --- thinking and speaking ---
    function fail(msg, showType) {
      closeMic();
      reply.textContent = msg;
      if (showType) form.hidden = false;
      setState("error");
    }
    async function submit(text) {
      retryText = "";
      heard.textContent = text;
      reply.textContent = "";
      setState("thinking");
      let result;
      try {
        let c = {};
        try { c = getContext() || {}; } catch { /* the page's summary failed; the model still gets the words */ }
        result = await (await post("/api/voice", {text, context: c})).json();
      } catch { retryText = text; return fail("I could not reach Earshot just now."); }
      reply.textContent = result.say || "";
      try { onResult(result); } catch { /* a handler's failure must not silence the reply */ }
      await say(result.say);
    }
    async function say(text) {
      if (!text) return setState("idle");
      setState("speaking");
      try {
        const blob = await (await post("/api/speak", {text})).blob();
        if (state !== "speaking") return; // interrupted while the audio was loading
        const url = URL.createObjectURL(blob);
        audio = new Audio(url);
        const end = () => { URL.revokeObjectURL(url); if (audio) { audio = null; setState("idle"); } };
        audio.onended = audio.onerror = end;
        await audio.play();
      } catch { audio = null; if (state === "speaking") setState("idle"); } // silent: the reply text is already on screen
    }
    function stopAudio() { if (audio) { const a = audio; audio = null; a.pause(); } }

    // --- inputs ---
    function press() { // used by pointer and keyboard alike
      if (state === "thinking") return;
      if (!SR) { input.focus(); return; }
      state === "listening" ? stopListening() : listen();
    }
    btn.addEventListener("pointerdown", e => {
      if (e.button) return;
      pressedAt = state === "listening" ? 0 : performance.now();
      press();
    });
    btn.addEventListener("pointerup", () => {
      if (pressedAt && state === "listening" && performance.now() - pressedAt > HOLD_MS) stopListening(); // held: release ends it
      pressedAt = 0;
    });
    btn.addEventListener("click", e => { if (!e.detail) press(); }); // detail 0 is the keyboard; a pointer press already acted
    retry.addEventListener("click", () => retryText ? submit(retryText) : press());
    form.addEventListener("submit", e => {
      e.preventDefault();
      const t = input.value.trim();
      if (!t || state === "thinking") return;
      input.value = "";
      stopListening(); stopAudio();
      submit(t);
    });
    setState("idle");
    return {destroy() { stopLoop(); stopAudio(); closeMic(); if (rec) rec.abort(); root.remove(); }};
  }
  return {mount};
})();
