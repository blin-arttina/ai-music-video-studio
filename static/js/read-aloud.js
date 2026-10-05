// Read-aloud button (top right of the header): reads the real page content
// out loud using the browser's built-in speech engine -- no account, no key,
// no network request. Unlike a generic "read aloud" browser tool, this reads
// straight from the page's own text, including content inside collapsed
// tab sections that isn't currently on screen, so nothing gets skipped the
// way it did with outside tools.
(function () {
  const btn = document.getElementById('read-aloud-btn');
  const main = document.getElementById('main-content');
  if (!btn || !main) return;

  if (!('speechSynthesis' in window)) {
    btn.hidden = true; // nothing we can do on a browser without this API
    return;
  }

  const synth = window.speechSynthesis;
  let utterance = null;

  function collectReadableText() {
    const clone = main.cloneNode(true);
    // Drop anything that isn't meant to be read aloud as prose: dropdown
    // option lists, form controls, media players, and hidden scripts/styles.
    clone.querySelectorAll('select, input, script, style, svg, audio, video').forEach((el) => el.remove());
    return clone.textContent.replace(/\s+/g, ' ').trim();
  }

  function setSpeakingState(isSpeaking) {
    btn.setAttribute('aria-pressed', isSpeaking ? 'true' : 'false');
    btn.classList.toggle('speaking', isSpeaking);
    btn.querySelector('.sr-only').textContent = isSpeaking ? 'Stop reading this page aloud' : 'Read this page aloud';
  }

  function stopReading() {
    synth.cancel();
    setSpeakingState(false);
  }

  function startReading() {
    const text = collectReadableText();
    if (!text) return;
    synth.cancel(); // clear anything queued or already playing first
    utterance = new SpeechSynthesisUtterance(text);
    utterance.onend = () => setSpeakingState(false);
    utterance.onerror = () => setSpeakingState(false);
    synth.speak(utterance);
    setSpeakingState(true);
  }

  btn.addEventListener('click', () => {
    if (synth.speaking) {
      stopReading();
    } else {
      startReading();
    }
  });

  // If the page is navigated away from or hidden, stop speaking rather
  // than let it keep talking over the next page.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && synth.speaking) stopReading();
  });
  window.addEventListener('pagehide', () => { if (synth.speaking) synth.cancel(); });
})();
