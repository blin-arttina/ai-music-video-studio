(function () {
  const script = document.currentScript;
  const projectId = script.dataset.projectId;
  const api = (path) => `/api/projects/${projectId}${path}`;

  // ---- Tabs ----
  const tabs = document.querySelectorAll('[role="tab"]');
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.setAttribute('aria-selected', 'false'));
      document.querySelectorAll('.tabpanel').forEach((p) => { p.hidden = true; p.classList.remove('active'); });
      tab.setAttribute('aria-selected', 'true');
      const panel = document.getElementById(tab.dataset.target);
      panel.hidden = false;
      panel.classList.add('active');
    });
  });

  // ---- Studio branding (account-wide, not scoped to this project) ----
  let studioBrand = { studio_name: '', has_logo: false };

  async function loadStudioBrand() {
    const res = await fetch('/api/studio-brand');
    studioBrand = res.ok ? await res.json() : { studio_name: '', has_logo: false };

    const nameInput = document.getElementById('studio-brand-name');
    const preview = document.getElementById('studio-brand-preview');
    if (nameInput) nameInput.value = studioBrand.studio_name || '';
    if (preview) {
      preview.innerHTML = '';
      if (studioBrand.has_logo) {
        const img = document.createElement('img');
        img.src = `/api/studio-brand/logo?ts=${Date.now()}`;
        img.alt = 'Your saved studio logo';
        img.style.maxHeight = '80px';
        img.style.display = 'block';
        img.style.marginBottom = '6px';
        preview.appendChild(img);
        preview.appendChild(document.createTextNode('Logo saved.'));
      } else {
        preview.textContent = 'No logo saved yet.';
      }
    }

    // Reflect the saved brand in the Export form so it's obvious it'll
    // be used automatically.
    const brandHint = document.getElementById('watermark-text-brand-hint');
    const logoField = document.getElementById('watermark-logo-field');
    if (brandHint) brandHint.hidden = !studioBrand.studio_name;
    if (logoField) logoField.hidden = !studioBrand.has_logo;
  }

  const studioBrandForm = document.getElementById('studio-brand-form');
  if (studioBrandForm) {
    studioBrandForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('studio-brand-status');
      const fd = new FormData();
      fd.append('studio_name', document.getElementById('studio-brand-name').value);
      const logoInput = document.getElementById('studio-brand-logo');
      if (logoInput.files[0]) fd.append('logo', logoInput.files[0]);
      status.textContent = 'Saving...';
      const res = await fetch('/api/studio-brand', { method: 'POST', body: fd });
      if (res.ok) {
        status.textContent = 'Saved.';
        logoInput.value = '';
        loadStudioBrand();
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'could not save');
      }
    });

    document.getElementById('clear-studio-logo-btn')?.addEventListener('click', async () => {
      const status = document.getElementById('studio-brand-status');
      await fetch('/api/studio-brand/logo', { method: 'DELETE' });
      status.textContent = 'Logo removed. Your studio name is unchanged.';
      loadStudioBrand();
    });
  }
  loadStudioBrand();

  // ---- Text / lyrics ----
  async function loadText() {
    const res = await fetch(api('/text'));
    const items = await res.json();
    const list = document.getElementById('text-list');
    if (!items.length) { list.textContent = 'Nothing saved yet.'; return; }
    list.innerHTML = '';
    items.forEach((item) => {
      const div = document.createElement('div');
      div.style.marginBottom = '16px';
      div.innerHTML = `
        <strong>${escapeHtml(item.title)}</strong>
        <span class="badge">${escapeHtml(item.kind)}</span>
        <span class="badge protected">v${item.version}</span>
        ${item.is_private ? '<span class="badge">Private</span>' : '<span class="badge">Shareable</span>'}
        <br>
        <a href="/project/${projectId}/text/${item.id}/ownership">View ownership record</a>
        &middot; <a href="${api(`/text/${item.id}/export`)}">Export with ownership block</a>
      `;
      list.appendChild(div);
    });
  }

  // ---- Text draft auto-save (crash recovery for in-progress, unsaved
  // writing -- this is separate from and does not replace the server-
  // side version history that already covers every explicit Save) ----
  const TEXT_DRAFT_KEY = `music-studio-text-draft-${projectId}`;

  function readTextDraft() {
    try {
      const raw = localStorage.getItem(TEXT_DRAFT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function writeTextDraft(draft) {
    try {
      localStorage.setItem(TEXT_DRAFT_KEY, JSON.stringify(draft));
    } catch (e) {
      // Best-effort only -- if storage is unavailable (private window,
      // cleared site data, etc.) the form still works, it just won't
      // survive a crash or accidental tab close.
    }
  }

  function clearTextDraft() {
    try {
      localStorage.removeItem(TEXT_DRAFT_KEY);
    } catch (e) { /* best-effort */ }
  }

  const newTextForm = document.getElementById('new-text-form');
  if (newTextForm) {
    const kindEl = document.getElementById('text-kind');
    const titleEl = document.getElementById('text-title');
    const bodyEl = document.getElementById('text-body');
    const privateEl = document.getElementById('text-private');
    const draftNotice = document.getElementById('draft-restore-notice');

    const existingDraft = readTextDraft();
    if (existingDraft && (existingDraft.title || existingDraft.body)) {
      kindEl.value = existingDraft.kind || kindEl.value;
      titleEl.value = existingDraft.title || '';
      bodyEl.value = existingDraft.body || '';
      privateEl.checked = existingDraft.is_private !== false;
      if (draftNotice) draftNotice.hidden = false;
    }

    let draftSaveTimer = null;
    const scheduleDraftSave = () => {
      if (draftSaveTimer) clearTimeout(draftSaveTimer);
      draftSaveTimer = setTimeout(() => {
        writeTextDraft({
          kind: kindEl.value, title: titleEl.value, body: bodyEl.value, is_private: privateEl.checked,
        });
      }, 800);
    };
    [kindEl, titleEl, bodyEl, privateEl].forEach((el) => {
      el.addEventListener('input', scheduleDraftSave);
      el.addEventListener('change', scheduleDraftSave);
    });

    document.getElementById('discard-draft-btn')?.addEventListener('click', () => {
      clearTextDraft();
      titleEl.value = '';
      bodyEl.value = '';
      if (draftNotice) draftNotice.hidden = true;
    });

    newTextForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('new-text-status');
      const body = {
        kind: kindEl.value,
        title: titleEl.value,
        body: bodyEl.value,
        is_private: privateEl.checked,
      };
      status.textContent = 'Saving...';
      const res = await fetch(api('/text'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (res.ok) {
        status.textContent = 'Saved with an ownership record.';
        titleEl.value = '';
        bodyEl.value = '';
        clearTextDraft();
        if (draftNotice) draftNotice.hidden = true;
        loadText();
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'could not save');
      }
    });
  }

  // ---- Microphone recording ----
  let mediaRecorder = null;
  let recordedChunks = [];
  let recordingTimerId = null;
  let recordingStartedAt = null;

  const recordStartBtn = document.getElementById('record-start-btn');
  const recordStopBtn = document.getElementById('record-stop-btn');
  const recordStatus = document.getElementById('record-status');

  function formatElapsed(ms) {
    const totalSeconds = Math.floor(ms / 1000);
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  if (recordStartBtn) {
    recordStartBtn.addEventListener('click', async () => {
      if (!navigator.mediaDevices || !window.MediaRecorder) {
        recordStatus.textContent = 'This browser does not support in-browser recording. Try uploading an audio file instead.';
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedChunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunks.push(e.data); };
        mediaRecorder.onstop = async () => {
          stream.getTracks().forEach((track) => track.stop());
          clearInterval(recordingTimerId);
          recordStatus.textContent = 'Recording stopped. Uploading...';
          const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
          const category = document.getElementById('record-category').value;
          const fd = new FormData();
          fd.append('category', category);
          const ext = (blob.type.split('/')[1] || 'webm').split(';')[0];
          fd.append('file', blob, `recording-${Date.now()}.${ext}`);
          const res = await fetch(api('/media'), { method: 'POST', body: fd });
          if (res.ok) {
            recordStatus.textContent = 'Recording saved to your Media Library.';
            loadMedia();
          } else {
            const err = await res.json().catch(() => ({}));
            recordStatus.textContent = 'Error saving recording: ' + (err.error || 'upload failed');
          }
        };
        mediaRecorder.start();
        recordingStartedAt = Date.now();
        recordStatus.textContent = 'Recording... 0:00';
        recordingTimerId = setInterval(() => {
          recordStatus.textContent = `Recording... ${formatElapsed(Date.now() - recordingStartedAt)}`;
        }, 500);
        recordStartBtn.disabled = true;
        recordStopBtn.disabled = false;
      } catch (err) {
        recordStatus.textContent = 'Could not access the microphone: ' + (err.message || 'permission denied.');
      }
    });

    recordStopBtn.addEventListener('click', () => {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
      }
      recordStartBtn.disabled = false;
      recordStopBtn.disabled = true;
    });
  }

  // ---- Media library ----
  async function loadMedia() {
    const res = await fetch(api('/media'));
    const items = await res.json();
    const list = document.getElementById('media-list');
    const select = document.getElementById('export-media-id');
    if (!items.length) { list.textContent = 'No files uploaded yet.'; }
    list.innerHTML = '';
    if (select) select.innerHTML = '';
    items.forEach((item) => {
      const div = document.createElement('div');
      div.style.marginBottom = '14px';
      const fileUrl = api(`/media/${item.id}/file`);
      let player = '';
      if (['audio', 'music', 'voice'].includes(item.category)) {
        player = `<div><audio controls preload="none" src="${fileUrl}" style="width:100%;max-width:480px;">Your browser cannot play this audio type. <a href="${fileUrl}">Download it instead</a>.</audio></div>`;
      } else if (['video', 'animation'].includes(item.category)) {
        player = `<div><video controls preload="none" src="${fileUrl}" style="width:100%;max-width:480px;">Your browser cannot play this video type. <a href="${fileUrl}">Download it instead</a>.</video></div>`;
      } else if (item.category === 'image') {
        player = `<div><img src="${fileUrl}" alt="${escapeHtml(item.filename)}" style="max-width:240px;max-height:180px;border-radius:8px;"></div>`;
      }
      div.innerHTML = `${escapeHtml(item.filename)} <span class="badge">${escapeHtml(item.category)}</span>
        <button class="btn secondary" data-delete-media="${item.id}" type="button">Delete</button>
        ${player}`;
      list.appendChild(div);
      if (select && ['image', 'video', 'animation'].includes(item.category)) {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = `${item.filename} (${item.category})`;
        select.appendChild(opt);
      }
    });
    list.querySelectorAll('[data-delete-media]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        await fetch(api(`/media/${btn.dataset.deleteMedia}`), { method: 'DELETE' });
        loadMedia();
      });
    });
  }

  const uploadForm = document.getElementById('upload-form');
  if (uploadForm) {
    uploadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('upload-status');
      const fileInput = document.getElementById('media-file');
      if (!fileInput.files.length) return;
      const fd = new FormData();
      fd.append('category', document.getElementById('media-category').value);
      fd.append('file', fileInput.files[0]);
      status.textContent = 'Uploading...';
      const res = await fetch(api('/media'), { method: 'POST', body: fd });
      if (res.ok) {
        status.textContent = 'Uploaded.';
        fileInput.value = '';
        loadMedia();
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'upload failed');
      }
    });
  }

  const exportMediaForm = document.getElementById('export-media-form');
  if (exportMediaForm) {
    const exportTypeSelect = document.getElementById('export-media-type');
    const exportFormatSelect = document.getElementById('export-format');
    const videoOnlyFields = exportMediaForm.querySelectorAll('.export-video-only');

    function syncExportSettingsToType() {
      const isVideo = exportTypeSelect.value === 'video';
      videoOnlyFields.forEach((field) => { field.style.display = isVideo ? '' : 'none'; });
      exportFormatSelect.innerHTML = isVideo
        ? '<option value="mp4">MP4 (H.264/AAC — plays almost everywhere)</option>'
          + '<option value="webm">WebM (VP9/Opus — smaller, web-friendly)</option>'
        : '<option value="png">PNG (lossless)</option>'
          + '<option value="jpg">JPG (smaller file)</option>';
    }
    exportTypeSelect.addEventListener('change', syncExportSettingsToType);
    syncExportSettingsToType();

    exportMediaForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('export-media-status');
      const mediaId = document.getElementById('export-media-id').value;
      if (!mediaId) { status.textContent = 'Upload a file first.'; return; }
      const type = exportTypeSelect.value;
      const format = exportFormatSelect.value;
      const fd = new FormData();
      fd.append('media_id', mediaId);
      fd.append('watermark_text', document.getElementById('watermark-text').value);
      fd.append('position', document.getElementById('watermark-position').value);
      fd.append('opacity', document.getElementById('watermark-opacity').value);
      fd.append('resolution', document.getElementById('export-resolution').value);
      fd.append('format', format);
      const includeLogoCheckbox = document.getElementById('watermark-include-logo');
      fd.append('include_studio_logo', includeLogoCheckbox && !includeLogoCheckbox.checked ? 'false' : 'true');
      const invisibleCheckbox = document.getElementById('export-invisible-watermark');
      fd.append('invisible_watermark', invisibleCheckbox && invisibleCheckbox.checked ? 'true' : 'false');
      if (type === 'video') {
        fd.append('frame_rate', document.getElementById('export-frame-rate').value);
        fd.append('video_quality', document.getElementById('export-video-quality').value);
        fd.append('audio_bitrate', document.getElementById('export-audio-bitrate').value);
      }
      status.textContent = 'Exporting with watermark...';
      const res = await fetch(api(`/export/${type}`), { method: 'POST', body: fd });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `watermarked-export.${format}`;
        a.click();
        status.textContent = 'Exported.';
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'export failed');
      }
    });
  }

  const verifyInvisibleForm = document.getElementById('verify-invisible-form');
  if (verifyInvisibleForm) {
    verifyInvisibleForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('verify-invisible-status');
      const file = document.getElementById('verify-invisible-file').files[0];
      if (!file) { status.textContent = 'Choose a file first.'; return; }
      status.textContent = 'Checking...';
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/verify-invisible-watermark', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        status.textContent = 'Error: ' + (data.error || 'could not check this file');
      } else if (!data.found) {
        status.textContent = 'No invisible watermark found in this file.';
      } else {
        const p = data.payload;
        status.textContent = p
          ? `Found: owner "${p.owner || ''}", project "${p.project || ''}"${p.content_hash ? `, hash ${p.content_hash}` : ''}`
          : `Found (raw): ${data.raw}`;
      }
    });
  }

  // ---- Timeline ----
  let mediaCache = [];

  async function refreshMediaCache() {
    const res = await fetch(api('/media'));
    mediaCache = res.ok ? await res.json() : [];
  }

  async function loadTimeline() {
    const container = document.getElementById('tracks-container');
    if (!container) return;
    await refreshMediaCache();
    const res = await fetch(api('/tracks'));
    const data = await res.json();
    document.getElementById('timeline-duration').textContent = (data.duration_seconds || 0).toFixed(1);
    applyHistoryStatus(data.history);
    if (!data.tracks.length) { container.textContent = 'No tracks yet. Add one above.'; return; }
    container.innerHTML = '';
    data.tracks.forEach((track) => container.appendChild(renderTrack(track)));
  }

  function applyHistoryStatus(historyStatus) {
    const undoBtn = document.getElementById('timeline-undo-btn');
    const redoBtn = document.getElementById('timeline-redo-btn');
    if (!undoBtn || !redoBtn || !historyStatus) return;
    undoBtn.disabled = !historyStatus.can_undo;
    redoBtn.disabled = !historyStatus.can_redo;
  }

  const timelineUndoBtn = document.getElementById('timeline-undo-btn');
  const timelineRedoBtn = document.getElementById('timeline-redo-btn');
  const timelineHistoryStatusEl = document.getElementById('timeline-history-status');

  timelineUndoBtn?.addEventListener('click', async () => {
    timelineHistoryStatusEl.textContent = 'Undoing...';
    const res = await fetch(api('/timeline/undo'), { method: 'POST' });
    if (res.ok) {
      timelineHistoryStatusEl.textContent = 'Undone.';
      loadTimeline();
    } else {
      const err = await res.json();
      timelineHistoryStatusEl.textContent = err.error || 'Nothing to undo.';
    }
  });

  timelineRedoBtn?.addEventListener('click', async () => {
    timelineHistoryStatusEl.textContent = 'Redoing...';
    const res = await fetch(api('/timeline/redo'), { method: 'POST' });
    if (res.ok) {
      timelineHistoryStatusEl.textContent = 'Redone.';
      loadTimeline();
    } else {
      const err = await res.json();
      timelineHistoryStatusEl.textContent = err.error || 'Nothing to redo.';
    }
  });

  function renderTrack(track) {
    const wrap = document.createElement('div');
    wrap.className = 'card';
    wrap.innerHTML = `
      <h4>${escapeHtml(track.name)} <span class="badge">${escapeHtml(track.kind)}</span></h4>
      <div>
        <label><input type="checkbox" data-track-flag="muted" ${track.muted ? 'checked' : ''}> Muted</label>
        &nbsp;<label><input type="checkbox" data-track-flag="locked" ${track.locked ? 'checked' : ''}> Locked</label>
        &nbsp;<label><input type="checkbox" data-track-flag="hidden" ${track.hidden ? 'checked' : ''}> Hidden</label>
        &nbsp;<button class="btn secondary" data-delete-track type="button">Delete Track</button>
      </div>
      <div class="clip-list"></div>
      <details>
        <summary>Add clip to this track</summary>
        <div class="field"><label>Label</label><input type="text" data-new-clip-label value="${escapeHtml(track.name)} clip"></div>
        <div class="field"><label>Media file (optional)</label>
          <select data-new-clip-media><option value="">None (e.g. a lyrics/text clip)</option></select>
        </div>
        <div class="field"><label>Start (seconds)</label><input type="number" min="0" step="0.1" value="0" data-new-clip-start></div>
        <div class="field"><label>Duration (seconds)</label><input type="number" min="0.1" step="0.1" value="5" data-new-clip-duration></div>
        <button class="btn secondary" type="button" data-add-clip>Add Clip</button>
        <p class="hint" data-clip-draft-notice hidden>Restored an unsaved "Add clip" entry for this track.</p>
      </details>
    `;

    const mediaSelect = wrap.querySelector('[data-new-clip-media]');
    mediaCache.forEach((m) => {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = `${m.filename} (${m.category})`;
      mediaSelect.appendChild(opt);
    });

    const clipList = wrap.querySelector('.clip-list');
    track.clips.forEach((clip) => clipList.appendChild(renderClip(clip)));

    // Restore/track an in-progress "Add clip" draft for this track (see
    // the Timeline draft safety net further below for why this exists).
    const clipDraftKey = `music-studio-clip-draft-${projectId}-${track.id}`;
    const labelEl = wrap.querySelector('[data-new-clip-label]');
    const startEl = wrap.querySelector('[data-new-clip-start]');
    const durationEl = wrap.querySelector('[data-new-clip-duration]');
    const clipDraftNotice = wrap.querySelector('[data-clip-draft-notice]');
    const existingClipDraft = readLocalDraft(clipDraftKey);
    if (existingClipDraft) {
      if (existingClipDraft.label !== undefined) labelEl.value = existingClipDraft.label;
      if (existingClipDraft.mediaId) mediaSelect.value = existingClipDraft.mediaId;
      if (existingClipDraft.start !== undefined) startEl.value = existingClipDraft.start;
      if (existingClipDraft.duration !== undefined) durationEl.value = existingClipDraft.duration;
      if (clipDraftNotice) clipDraftNotice.hidden = false;
    }
    let clipDraftTimer = null;
    const scheduleClipDraftSave = () => {
      if (clipDraftTimer) clearTimeout(clipDraftTimer);
      clipDraftTimer = setTimeout(() => {
        writeLocalDraft(clipDraftKey, {
          label: labelEl.value, mediaId: mediaSelect.value, start: startEl.value, duration: durationEl.value,
        });
      }, 800);
    };
    [labelEl, mediaSelect, startEl, durationEl].forEach((el) => {
      el.addEventListener('input', scheduleClipDraftSave);
      el.addEventListener('change', scheduleClipDraftSave);
    });

    wrap.querySelectorAll('[data-track-flag]').forEach((cb) => {
      cb.addEventListener('change', async () => {
        await fetch(api(`/tracks/${track.id}`), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [cb.dataset.trackFlag]: cb.checked }),
        });
      });
    });

    wrap.querySelector('[data-delete-track]').addEventListener('click', async () => {
      if (!confirm('Delete this track and all its clips?')) return;
      await fetch(api(`/tracks/${track.id}`), { method: 'DELETE' });
      clearLocalDraft(clipDraftKey);
      loadTimeline();
    });

    wrap.querySelector('[data-add-clip]').addEventListener('click', async () => {
      const label = labelEl.value;
      const mediaId = mediaSelect.value || null;
      const start = parseFloat(startEl.value || '0');
      const duration = parseFloat(durationEl.value || '5');
      const res = await fetch(api(`/tracks/${track.id}/clips`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label, media_asset_id: mediaId, start_seconds: start, duration_seconds: duration }),
      });
      if (res.ok) {
        clearLocalDraft(clipDraftKey);
        loadTimeline();
      }
    });

    return wrap;
  }

  function renderClip(clip) {
    const div = document.createElement('div');
    div.style.borderTop = '1px solid var(--border)';
    div.style.padding = '10px 0';
    div.innerHTML = `
      <strong>${escapeHtml(clip.label)}</strong>
      ${clip.muted ? '<span class="badge">Muted</span>' : ''}
      ${clip.locked ? '<span class="badge">Locked</span>' : ''}
      <div class="field"><label>Start (s)</label><input type="number" min="0" step="0.1" value="${clip.start_seconds}" data-clip-field="start_seconds"></div>
      <div class="field"><label>Duration (s)</label><input type="number" min="0.1" step="0.1" value="${clip.duration_seconds}" data-clip-field="duration_seconds"></div>
      <div class="field"><label>Volume (0-2)</label><input type="number" min="0" max="2" step="0.1" value="${clip.volume}" data-clip-field="volume"></div>
      <button class="btn secondary" type="button" data-clip-split>Split at midpoint</button>
      <button class="btn secondary" type="button" data-clip-mute>${clip.muted ? 'Unmute' : 'Mute'}</button>
      <button class="btn danger" type="button" data-clip-delete>Delete Clip</button>

      <details>
        <summary>Audio effects (for audio/music/voice clips)</summary>
        <div class="field"><label>Bass EQ (-24 to +24 dB)</label><input type="number" min="-24" max="24" step="1" value="${clip.eq_low_db ?? 0}" data-clip-field="eq_low_db"></div>
        <div class="field"><label>Mid EQ (-24 to +24 dB)</label><input type="number" min="-24" max="24" step="1" value="${clip.eq_mid_db ?? 0}" data-clip-field="eq_mid_db"></div>
        <div class="field"><label>Treble EQ (-24 to +24 dB)</label><input type="number" min="-24" max="24" step="1" value="${clip.eq_high_db ?? 0}" data-clip-field="eq_high_db"></div>
        <div class="field"><label>Reverb (0-1)</label><input type="number" min="0" max="1" step="0.1" value="${clip.reverb_amount ?? 0}" data-clip-field="reverb_amount"></div>
        <div class="field"><label>Echo (0-1)</label><input type="number" min="0" max="1" step="0.1" value="${clip.echo_amount ?? 0}" data-clip-field="echo_amount"></div>
        <div class="field"><label>Compression (0-1)</label><input type="number" min="0" max="1" step="0.1" value="${clip.compression ?? 0}" data-clip-field="compression"></div>
        <div class="field"><label>Noise reduction (0-1)</label><input type="number" min="0" max="1" step="0.1" value="${clip.noise_reduction ?? 0}" data-clip-field="noise_reduction"></div>
        <div class="field"><label>Pitch shift (semitones, -12 to +12)</label><input type="number" min="-12" max="12" step="1" value="${clip.pitch_semitones ?? 0}" data-clip-field="pitch_semitones"></div>
        <button class="btn secondary" type="button" data-clip-render-audio>Render Audio with These Settings</button>
        <span data-render-audio-status role="status" class="hint"></span>
      </details>

      <details>
        <summary>Video effects (for video/animation clips)</summary>
        <div class="field"><label>Crop from left (0-1)</label><input type="number" min="0" max="1" step="0.05" value="${clip.crop_x ?? 0}" data-clip-field="crop_x"></div>
        <div class="field"><label>Crop from top (0-1)</label><input type="number" min="0" max="1" step="0.05" value="${clip.crop_y ?? 0}" data-clip-field="crop_y"></div>
        <div class="field"><label>Crop width (0.05-1)</label><input type="number" min="0.05" max="1" step="0.05" value="${clip.crop_width ?? 1}" data-clip-field="crop_width"></div>
        <div class="field"><label>Crop height (0.05-1)</label><input type="number" min="0.05" max="1" step="0.05" value="${clip.crop_height ?? 1}" data-clip-field="crop_height"></div>
        <div class="field"><label>Rotation</label>
          <select data-clip-field="rotation_degrees">
            <option value="0" ${(clip.rotation_degrees ?? 0) === 0 ? 'selected' : ''}>No rotation</option>
            <option value="90" ${clip.rotation_degrees === 90 ? 'selected' : ''}>90° clockwise</option>
            <option value="180" ${clip.rotation_degrees === 180 ? 'selected' : ''}>180°</option>
            <option value="270" ${clip.rotation_degrees === 270 ? 'selected' : ''}>270° clockwise</option>
          </select>
        </div>
        <div class="field"><label>Caption text</label><input type="text" maxlength="300" value="${escapeHtml(clip.caption_text || '')}" data-clip-field="caption_text"></div>
        <div class="field"><label>Caption position</label>
          <select data-clip-field="caption_position">
            <option value="top" ${clip.caption_position === 'top' ? 'selected' : ''}>Top</option>
            <option value="center" ${clip.caption_position === 'center' ? 'selected' : ''}>Center</option>
            <option value="bottom" ${(clip.caption_position ?? 'bottom') === 'bottom' ? 'selected' : ''}>Bottom</option>
          </select>
        </div>
        <button class="btn secondary" type="button" data-clip-render-video>Render Video with These Settings</button>
        <span data-render-video-status role="status" class="hint"></span>
        <p class="hint">Editing here does not add the required watermark — use "Export With Watermark" in the Media Library once you're happy with the edit.</p>
      </details>

      <details>
        <summary>Crossfade into the next clip on this track</summary>
        <p class="hint">Blends the tail of this clip into the clip that starts right after it on the same track (both need an attached media file, and both must be the same kind — both audio-like or both video-like). This renders each clip's own trim/effects first, then crossfades the two results together.</p>
        <div class="field"><label>Crossfade duration (seconds, 0.1-10)</label><input type="number" min="0.1" max="10" step="0.1" value="1.0" data-crossfade-duration></div>
        <div class="field"><label>Video transition style (ignored for audio-only clips)</label>
          <select data-crossfade-style>
            <option value="fade">Fade</option>
            <option value="dissolve">Dissolve</option>
            <option value="wipeleft">Wipe left</option>
            <option value="wiperight">Wipe right</option>
            <option value="slideleft">Slide left</option>
            <option value="slideright">Slide right</option>
          </select>
        </div>
        <button class="btn secondary" type="button" data-clip-crossfade>Crossfade with Next Clip</button>
        <span data-crossfade-status role="status" class="hint"></span>
      </details>
    `;

    const TEXT_CLIP_FIELDS = new Set(['caption_text', 'caption_position']);
    div.querySelectorAll('[data-clip-field]').forEach((input) => {
      input.addEventListener('change', async () => {
        const field = input.dataset.clipField;
        const value = TEXT_CLIP_FIELDS.has(field) ? input.value : parseFloat(input.value);
        await fetch(api(`/clips/${clip.id}`), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [field]: value }),
        });
        loadTimeline();
      });
    });

    div.querySelector('[data-clip-split]').addEventListener('click', async () => {
      const midpoint = clip.start_seconds + clip.duration_seconds / 2;
      const res = await fetch(api(`/clips/${clip.id}/split`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ split_at_seconds: midpoint }),
      });
      if (res.ok) loadTimeline();
    });

    div.querySelector('[data-clip-mute]').addEventListener('click', async () => {
      await fetch(api(`/clips/${clip.id}`), {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ muted: !clip.muted }),
      });
      loadTimeline();
    });

    div.querySelector('[data-clip-delete]').addEventListener('click', async () => {
      await fetch(api(`/clips/${clip.id}`), { method: 'DELETE' });
      loadTimeline();
    });

    div.querySelector('[data-clip-render-audio]')?.addEventListener('click', async () => {
      const status = div.querySelector('[data-render-audio-status]');
      status.textContent = 'Rendering...';
      const res = await fetch(api(`/clips/${clip.id}/render-audio`), { method: 'POST' });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        let preview = status.parentElement.querySelector('audio.render-preview');
        if (!preview) {
          preview = document.createElement('audio');
          preview.className = 'render-preview';
          preview.controls = true;
          preview.style.display = 'block';
          preview.style.marginTop = '8px';
          status.insertAdjacentElement('afterend', preview);
        }
        preview.src = url;
        const a = document.createElement('a');
        a.href = url;
        a.download = `${clip.label || 'clip'}-rendered.wav`;
        a.click();
        status.textContent = 'Rendered — preview below, and downloaded.';
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'could not render audio');
      }
    });

    div.querySelector('[data-clip-render-video]')?.addEventListener('click', async () => {
      const status = div.querySelector('[data-render-video-status]');
      status.textContent = 'Rendering...';
      const res = await fetch(api(`/clips/${clip.id}/render-video`), { method: 'POST' });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        let preview = status.parentElement.querySelector('video.render-preview');
        if (!preview) {
          preview = document.createElement('video');
          preview.className = 'render-preview';
          preview.controls = true;
          preview.style.display = 'block';
          preview.style.maxWidth = '480px';
          preview.style.marginTop = '8px';
          status.insertAdjacentElement('afterend', preview);
        }
        preview.src = url;
        const a = document.createElement('a');
        a.href = url;
        a.download = `${clip.label || 'clip'}-edited.mp4`;
        a.click();
        status.textContent = 'Rendered — preview below, and downloaded.';
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'could not render video');
      }
    });

    div.querySelector('[data-clip-crossfade]')?.addEventListener('click', async () => {
      const status = div.querySelector('[data-crossfade-status]');
      const duration = parseFloat(div.querySelector('[data-crossfade-duration]').value || '1.0');
      const style = div.querySelector('[data-crossfade-style]').value;
      status.textContent = 'Crossfading...';
      const res = await fetch(api(`/clips/${clip.id}/crossfade-with-next`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration_seconds: duration, style }),
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const isVideo = blob.type.includes('video');
        let preview = status.parentElement.querySelector('.crossfade-preview');
        if (!preview) {
          preview = document.createElement(isVideo ? 'video' : 'audio');
          preview.className = 'crossfade-preview';
          preview.controls = true;
          preview.style.display = 'block';
          preview.style.marginTop = '8px';
          if (isVideo) preview.style.maxWidth = '480px';
          status.insertAdjacentElement('afterend', preview);
        }
        preview.src = url;
        const a = document.createElement('a');
        a.href = url;
        a.download = `${clip.label || 'clip'}-crossfaded.${isVideo ? 'mp4' : 'wav'}`;
        a.click();
        status.textContent = 'Crossfaded with the next clip — preview below, and downloaded.';
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'could not crossfade these clips');
      }
    });

    return div;
  }

  // ---- Timeline in-progress-draft safety net -----------------------
  // Everything already committed to a track or clip (renaming, moving,
  // resizing, effects, flags) saves to the server immediately, so there
  // is nothing to lose there. The one place unsaved typing can still be
  // lost -- on a crash/reload, or simply because adding something on one
  // track rebuilds the whole Timeline and wipes any other in-progress
  // "Add clip" form -- is these not-yet-submitted "Add Track" / "Add
  // clip" fields. This mirrors the text-draft safety net above, but for
  // the Timeline's own still-unsaved fields.
  function readLocalDraft(key) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }
  function writeLocalDraft(key, draft) {
    try {
      localStorage.setItem(key, JSON.stringify(draft));
    } catch (e) { /* best-effort only, same as the text draft above */ }
  }
  function clearLocalDraft(key) {
    try {
      localStorage.removeItem(key);
    } catch (e) { /* best-effort */ }
  }

  const TRACK_DRAFT_KEY = `music-studio-track-draft-${projectId}`;

  const newTrackForm = document.getElementById('new-track-form');
  if (newTrackForm) {
    const nameEl = document.getElementById('track-name');
    const kindEl = document.getElementById('track-kind');
    const trackDraftNotice = document.getElementById('track-draft-notice');

    const existingTrackDraft = readLocalDraft(TRACK_DRAFT_KEY);
    if (existingTrackDraft && existingTrackDraft.name) {
      nameEl.value = existingTrackDraft.name;
      if (existingTrackDraft.kind) kindEl.value = existingTrackDraft.kind;
      if (trackDraftNotice) trackDraftNotice.hidden = false;
    }

    let trackDraftTimer = null;
    const scheduleTrackDraftSave = () => {
      if (trackDraftTimer) clearTimeout(trackDraftTimer);
      trackDraftTimer = setTimeout(() => {
        if (nameEl.value.trim()) {
          writeLocalDraft(TRACK_DRAFT_KEY, { name: nameEl.value, kind: kindEl.value });
        } else {
          clearLocalDraft(TRACK_DRAFT_KEY);
          if (trackDraftNotice) trackDraftNotice.hidden = true;
        }
      }, 800);
    };
    [nameEl, kindEl].forEach((el) => {
      el.addEventListener('input', scheduleTrackDraftSave);
      el.addEventListener('change', scheduleTrackDraftSave);
    });

    newTrackForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('new-track-status');
      const name = nameEl.value.trim();
      const kind = kindEl.value;
      if (!name) { status.textContent = 'Please name the track.'; return; }
      const res = await fetch(api('/tracks'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, kind }),
      });
      if (res.ok) {
        status.textContent = 'Track added.';
        nameEl.value = '';
        clearLocalDraft(TRACK_DRAFT_KEY);
        if (trackDraftNotice) trackDraftNotice.hidden = true;
        loadTimeline();
      } else {
        status.textContent = 'Could not add track.';
      }
    });
  }

  // ---- AI Assistant ----
  // Every call below goes through this project's own /ai/* routes, which
  // automatically build and attach AI Project Memory (spec §14) server-
  // side -- media counts, saved-text titles/kinds, timeline size, studio
  // brand -- so the assistant already has real context without the user
  // typing a project description into every question.
  const aiAskBtn = document.getElementById('ai-ask-btn');
  if (aiAskBtn) {
    aiAskBtn.addEventListener('click', async () => {
      const question = document.getElementById('ai-question').value;
      const out = document.getElementById('ai-answer');
      out.textContent = 'Thinking...';
      const res = await fetch(api('/ai/help'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      out.textContent = data.answer || data.message || JSON.stringify(data);
    });
  }

  const aiLyricsBtn = document.getElementById('ai-lyrics-btn');
  if (aiLyricsBtn) {
    aiLyricsBtn.addEventListener('click', async () => {
      const idea = document.getElementById('ai-lyrics-idea').value;
      const out = document.getElementById('ai-lyrics-result');
      out.textContent = 'Drafting...';
      const res = await fetch(api('/ai/lyrics'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ idea }),
      });
      const data = await res.json();
      out.textContent = data.lyrics || data.message || JSON.stringify(data);
    });
  }

  const aiVideoBtn = document.getElementById('ai-video-btn');
  if (aiVideoBtn) {
    aiVideoBtn.addEventListener('click', async () => {
      const concept = document.getElementById('ai-video-concept').value;
      const out = document.getElementById('ai-video-result');
      out.textContent = 'Drafting...';
      const res = await fetch(api('/ai/video-plan'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ concept }),
      });
      const data = await res.json();
      out.textContent = data.script || data.message || JSON.stringify(data);
    });
  }

  document.getElementById('ai-music-btn')?.addEventListener('click', () => callProviderStub(api('/ai/music'), {}));
  document.getElementById('ai-voice-btn')?.addEventListener('click', () => callProviderStub(api('/ai/voice'), { text: 'Hello' }));

  async function callProviderStub(url, payload) {
    const out = document.getElementById('ai-provider-result');
    out.textContent = 'Checking...';
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    out.textContent = data.message || JSON.stringify(data);
  }

  // ---- Project actions ----
  document.getElementById('btn-backup')?.addEventListener('click', async () => {
    const status = document.getElementById('project-action-status');
    const res = await fetch(api('/backup'), { method: 'POST' });
    const data = await res.json();
    status.textContent = res.ok ? `Backup created: ${data.backup_file}` : (data.error || 'Backup failed');
  });

  document.getElementById('btn-export-zip')?.addEventListener('click', () => {
    window.location.href = api('/export');
  });

  document.getElementById('btn-duplicate')?.addEventListener('click', async () => {
    const res = await fetch(api('/duplicate'), { method: 'POST' });
    const data = await res.json();
    if (res.ok) window.location.href = '/project/' + data.id;
  });

  document.getElementById('btn-rename')?.addEventListener('click', async () => {
    const name = document.getElementById('rename-input').value.trim();
    if (!name) return;
    const res = await fetch(api(''), {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
    });
    if (res.ok) document.querySelector('h2').textContent = name;
  });

  document.getElementById('btn-delete')?.addEventListener('click', async () => {
    if (!confirm('Permanently delete this project? This cannot be undone.')) return;
    const res = await fetch(api(''), { method: 'DELETE' });
    if (res.ok) window.location.href = '/';
  });

  async function loadAudit() {
    const el = document.getElementById('audit-log');
    if (!el) return;
    const res = await fetch(api('/audit'));
    if (!res.ok) { el.textContent = 'Not available.'; return; }
    const entries = await res.json();
    if (!entries.length) { el.textContent = 'No activity recorded yet.'; return; }
    el.innerHTML = '<ul>' + entries.map((e) =>
      `<li>${escapeHtml(e.created_at)} — ${escapeHtml(e.action)} ${escapeHtml(e.detail || '')}</li>`
    ).join('') + '</ul>';
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str ?? '';
    return div.innerHTML;
  }

  // ---- Collaboration (spec Phase 5) ----
  const PERMISSION_LABELS = { view: 'View', comment: 'Comment', edit: 'Edit', full: 'Full' };

  async function loadCollaborators() {
    const list = document.getElementById('collaborators-list');
    if (!list) return;
    const res = await fetch(api('/collaborators'));
    if (!res.ok) {
      // Not the owner (or not signed in as one) -- the API is owner-only,
      // so hide the whole card rather than show a confusing error.
      const card = document.getElementById('collaborators-card');
      if (card) card.hidden = true;
      return;
    }
    const collaborators = await res.json();
    if (!collaborators.length) {
      list.textContent = "No collaborators invited yet — you're the only one with access.";
      return;
    }
    list.innerHTML = '';
    collaborators.forEach((collab) => list.appendChild(renderCollaboratorRow(collab)));
  }

  function renderCollaboratorRow(collab) {
    const row = document.createElement('div');
    row.style.borderTop = '1px solid var(--border)';
    row.style.padding = '8px 0';
    row.innerHTML = `
      <strong>${escapeHtml(collab.email)}</strong>
      ${collab.revoked ? '<span class="badge">Revoked</span>' : ''}
      <div class="field" style="display:inline-block; margin-left:12px;">
        <label style="display:inline;">Permission
          <select data-collab-permission>
            ${Object.entries(PERMISSION_LABELS).map(([value, label]) =>
              `<option value="${value}" ${collab.permission === value ? 'selected' : ''}>${label}</option>`
            ).join('')}
          </select>
        </label>
      </div>
      &nbsp;<button class="btn secondary" type="button" data-collab-toggle>${collab.revoked ? 'Restore Access' : 'Revoke Access'}</button>
    `;

    row.querySelector('[data-collab-permission]').addEventListener('change', async (e) => {
      await fetch(api(`/collaborators/${collab.id}`), {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permission: e.target.value }),
      });
      loadCollaborators();
    });

    row.querySelector('[data-collab-toggle]').addEventListener('click', async () => {
      await fetch(api(`/collaborators/${collab.id}`), {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revoked: !collab.revoked }),
      });
      loadCollaborators();
    });

    return row;
  }

  const inviteCollaboratorForm = document.getElementById('invite-collaborator-form');
  if (inviteCollaboratorForm) {
    inviteCollaboratorForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('invite-collaborator-status');
      const email = document.getElementById('collab-email').value.trim();
      const permission = document.getElementById('collab-permission').value;
      status.textContent = 'Inviting...';
      const res = await fetch(api('/collaborators'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, permission }),
      });
      if (res.ok) {
        status.textContent = 'Invited.';
        document.getElementById('collab-email').value = '';
        loadCollaborators();
      } else {
        const err = await res.json();
        status.textContent = 'Error: ' + (err.error || 'could not invite');
      }
    });
  }

  // ---- Downloadable Asset & Template Library (spec section 23) ----
  async function loadLibrary() {
    const templatesList = document.getElementById('library-templates-list');
    const assetsList = document.getElementById('library-assets-list');
    if (!templatesList || !assetsList) return;

    const res = await fetch('/api/library');
    if (!res.ok) {
      templatesList.textContent = 'Could not load the library.';
      assetsList.textContent = '';
      return;
    }
    const items = await res.json();
    const templates = items.filter((i) => i.kind === 'project_template');
    const assets = items.filter((i) => i.kind === 'media_asset');

    templatesList.innerHTML = '';
    if (!templates.length) {
      templatesList.textContent = 'No project templates available yet.';
    } else {
      templates.forEach((item) => templatesList.appendChild(renderLibraryItem(item)));
    }

    assetsList.innerHTML = '';
    if (!assets.length) {
      assetsList.textContent = 'No media assets available yet.';
    } else {
      assets.forEach((item) => assetsList.appendChild(renderLibraryItem(item)));
    }
  }

  function renderLibraryItem(item) {
    const row = document.createElement('div');
    row.className = 'card';
    const priceLabel = item.is_free
      ? 'Free'
      : (item.price_usd != null ? `$${item.price_usd.toFixed(2)} (purchasing not connected)` : 'Paid (purchasing not connected)');
    const actionLabel = item.kind === 'project_template' ? 'Add Tracks to This Project' : 'Add to Media Library';
    row.innerHTML = `
      <strong>${escapeHtml(item.title)}</strong> &mdash; <span class="hint">${priceLabel}</span>
      <p class="hint">${escapeHtml(item.description || '')}</p>
      <button class="btn secondary" type="button" data-library-use>${actionLabel}</button>
      <span role="status" data-library-status></span>
    `;

    row.querySelector('[data-library-use]').addEventListener('click', async () => {
      const status = row.querySelector('[data-library-status]');
      status.textContent = 'Working...';
      const endpoint = item.kind === 'project_template' ? 'apply-template' : 'import-asset';
      const res = await fetch(`/api/library/${item.id}/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId }),
      });
      if (res.ok) {
        status.textContent = 'Added.';
        if (item.kind === 'project_template') { loadTimeline(); } else { loadMedia(); }
      } else {
        const err = await res.json().catch(() => ({}));
        status.textContent = 'Error: ' + (err.error || 'could not add this item');
      }
    });

    return row;
  }

  loadText();
  loadMedia();
  loadAudit();
  loadTimeline();
  loadCollaborators();
  loadLibrary();
})();
