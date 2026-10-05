// Read-aloud button (top right of the header): reads the real page content
// out loud using the browser's built-in speech engine -- no account, no key,
// no network request. Unlike a generic "read aloud" browser tool, this reads
// straight from the page's own text, including content inside collapsed
// tab sections that isn't currently on screen, so nothing gets skipped the
// way it did with outside tools.
(function () {
  const btn = document.getElementById('read-aloud-btn');
  const main = document.getElementById('main-content');
  const status = document.getElementById('read-aloud-status');
  if (!btn || !main) return;

  function showStatus(message) {
    if (status) status.textContent = message || '';
  }

  if (!('speechSynthesis' in window)) {
    btn.hidden = true; // nothing we can do on a browser without this API
    return;
  }

  const synth = window.speechSynthesis;
  let utterance = null;
  let keepAliveTimer = null;

  // Chrome (desktop and Android) silently drops speech if no voices have
  // loaded yet, and voices often load asynchronously after the page does.
  // Calling getVoices() once kicks that off; voiceschanged fires when ready.
  synth.getVoices();

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

  function stopKeepAlive() {
    if (keepAliveTimer) { clearInterval(keepAliveTimer); keepAliveTimer = null; }
  }

  function stopReading() {
    stopKeepAlive();
    synth.cancel();
    setSpeakingState(false);
  }

  function describeError(code) {
    switch (code) {
      case 'not-allowed':
        return 'Your browser blocked this. Try tapping the speaker button again, or check site permissions.';
      case 'language-unavailable':
      case 'voice-unavailable':
        return 'No voice is installed for this language on your device. Check Settings > Accessibility > Text-to-speech (or Languages & input) and make sure a voice is downloaded and enabled.';
      case 'synthesis-failed':
      case 'synthesis-unavailable':
      case 'audio-busy':
      case 'audio-hardware':
        return 'Your device could not play the audio. Check that media volume (not just ringer volume) is turned up, and that no other app has the microphone/speaker locked.';
      default:
        return 'Something stopped the reader (' + (code || 'unknown error') + '). If this keeps happening, check that a text-to-speech voice is installed on your device.';
    }
  }

  function speakNow() {
    const text = collectReadableText();
    if (!text) return;
    synth.cancel(); // clear anything queued or already playing first
    utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = document.documentElement.lang || 'en-US';
    utterance.onstart = () => showStatus('');
    utterance.onend = () => { stopKeepAlive(); setSpeakingState(false); };
    utterance.onerror = (e) => {
      stopKeepAlive();
      setSpeakingState(false);
      showStatus(describeError(e.error));
    };
    synth.speak(utterance);
    setSpeakingState(true);

    // Chrome has a long-standing bug where speech stops on its own after
    // about 15 seconds on a long page. Nudging pause/resume periodically
    // while still speaking works around it.
    stopKeepAlive();
    keepAliveTimer = setInterval(() => {
      if (synth.speaking && !synth.paused) {
        synth.pause();
        synth.resume();
      }
    }, 10000);
  }

  function startReading() {
    showStatus('');
    // If voices haven't finished loading yet, wait briefly for them rather
    // than speaking into a configuration with no voice selected (which on
    // some Android browsers produces no sound at all, with no error).
    if (synth.getVoices().length === 0) {
      const onVoices = () => {
        synth.removeEventListener('voiceschanged', onVoices);
        speakNow();
      };
      synth.addEventListener('voiceschanged', onVoices);
      // Fallback in case voiceschanged never fires on this browser.
      setTimeout(() => {
        synth.removeEventListener('voiceschanged', onVoices);
        if (!synth.speaking) speakNow();
      }, 800);
    } else {
      speakNow();
    }
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
  window.addEventListener('pagehide', () => { stopKeepAlive(); if (synth.speaking) synth.cancel(); });
})();
