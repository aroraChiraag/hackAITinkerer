const audioFile = document.querySelector('#audio-file');
const filename = document.querySelector('#file-name');
const analyze = document.querySelector('#analyze');
const demo = document.querySelector('#demo');
const status = document.querySelector('#status');
const results = document.querySelector('#results');
const count = document.querySelector('#drift-count');
const title = document.querySelector('#result-title');
const summary = document.querySelector('#summary');
const timeline = document.querySelector('#timeline');
const markerList = document.querySelector('#marker-list');
const verdictTitle = document.querySelector('#verdict-title');
const verdictCopy = document.querySelector('#verdict-copy');
const agentMode = document.querySelector('#agent-mode');
const referenceNotes = document.querySelector('#reference-notes');
const reaperPlan = document.querySelector('#reaper-plan');
const key = document.querySelector('#key');
const chords = document.querySelector('#chords');
const genre = document.querySelector('#genre');
const vocalStyle = document.querySelector('#vocal-style');
const lyrics = document.querySelector('#lyrics');
const lyricsNote = document.querySelector('#lyrics-note');
const lyricsStatus = document.querySelector('#lyrics-status');
const recoach = document.querySelector('#recoach');
// Drift results of the last analysis, re-sent when coaching is updated with edited lyrics.
let lastResults = null;
let coachedLyrics = '';
const feedback = {
  headline: document.querySelector('#feedback-headline'),
  summary: document.querySelector('#feedback-summary'),
  rhymeScheme: document.querySelector('#rhyme-scheme'),
  rhyme: document.querySelector('#rhyme-feedback'),
  melody: document.querySelector('#melody-feedback'),
  vibrato: document.querySelector('#vibrato-feedback'),
  practice: document.querySelector('#practice-steps'),
  instruments: document.querySelector('#instrument-recommendations'),
};

audioFile.addEventListener('change', () => {
  const file = audioFile.files[0];
  filename.textContent = file ? file.name + ' · ' + (file.size / 1024 / 1024).toFixed(1) + ' MB' : 'No file selected';
  analyze.disabled = !file;
  status.textContent = file ? 'Ready: ShruTea will check the first 8 seconds of your take.' : 'Choose a recording or try the sample vocal.';
});

function listInto(element, values) {
  element.replaceChildren(...values.map(value => {
    const item = document.createElement('li');
    item.textContent = value;
    return item;
  }));
}

function renderFeedback(report) {
  feedback.headline.textContent = report.headline;
  feedback.summary.textContent = report.summary;
  feedback.rhymeScheme.textContent = report.rhyme_scheme;
  feedback.rhyme.textContent = report.rhyme_feedback;
  feedback.melody.textContent = report.melody_feedback;
  feedback.vibrato.textContent = report.vibrato_feedback;
  listInto(feedback.practice, report.practice_steps);
  listInto(feedback.instruments, report.instrument_recommendations);
}

// Plain-language pitch description for musicians, e.g. "a little flat".
function pitchWords(entry) {
  const cents = Math.abs(Number(entry.cents_off));
  const direction = entry.direction || 'off';
  if (cents < 30) return 'a little ' + direction;
  if (cents < 45) return direction;
  return 'very ' + direction;
}

function noteName(entry) {
  return entry.actual_note && entry.actual_note !== entry.expected_note
    ? entry.expected_note + ' → ' + entry.actual_note
    : entry.expected_note;
}

function clockTime(seconds) {
  const whole = Math.floor(Number(seconds));
  return Math.floor(whole / 60) + ':' + String(whole % 60).padStart(2, '0');
}

function makeMarker(entry) {
  const card = document.createElement('article');
  card.className = 'marker';
  const symbol = document.createElement('b');
  symbol.textContent = entry.direction === 'sharp' ? '♯' : '♭';
  symbol.title = entry.direction === 'sharp' ? 'Sharp' : 'Flat';
  const body = document.createElement('div');
  const heading = document.createElement('strong');
  heading.textContent = noteName(entry) + ' · ' + pitchWords(entry);
  const details = document.createElement('small');
  details.textContent = 'At ' + clockTime(entry.time) + ' in your take';
  body.append(heading, details);
  card.append(symbol, body);
  return card;
}

function render(payload) {
  const entries = payload.results;
  results.hidden = false;
  count.textContent = entries.length;
  verdictTitle.textContent = 'ShruTea is in the session';
  verdictCopy.textContent = payload.verdict;
  agentMode.textContent = payload.agent_mode;
  reaperPlan.textContent = entries.length ? entries.length + ' note' + (entries.length === 1 ? '' : 's') + ' marked on your timeline' : 'No markers needed';

  referenceNotes.replaceChildren();
  const chip = document.createElement('span');
  chip.textContent = 'Checked: first ' + payload.analysis_window_seconds + ' seconds';
  referenceNotes.append(chip);

  timeline.replaceChildren();
  markerList.replaceChildren();
  if (!entries.length) {
    title.textContent = 'Every note is on pitch';
    summary.textContent = 'Nothing slipped off pitch, so there is nothing to mark on your timeline.';
    const clean = document.createElement('article');
    clean.className = 'marker good';
    const check = document.createElement('b');
    check.textContent = '✓';
    const copy = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = 'In tune';
    const note = document.createElement('small');
    note.textContent = 'Every note you sang landed on pitch.';
    copy.append(name, note);
    clean.append(check, copy);
    markerList.append(clean);
  } else {
    title.textContent = 'Notes to revisit';
    const lastTime = Math.max(payload.analysis_window_seconds || 0.1, ...entries.map(entry => Number(entry.time)), 0.1);
    summary.textContent = entries.length + ' note' + (entries.length === 1 ? '' : 's') + ' slipped off pitch. Each one is marked on your timeline.';
    entries.forEach(entry => {
      const point = document.createElement('i');
      point.className = 'warn';
      point.style.left = (8 + 84 * Number(entry.time) / lastTime) + '%';
      point.title = noteName(entry) + ' · ' + pitchWords(entry) + ' at ' + clockTime(entry.time);
      timeline.append(point);
      markerList.append(makeMarker(entry));
    });
  }
  renderFeedback(payload.feedback);
  renderLyrics(payload);
}

function renderLyrics(payload) {
  lastResults = payload.results;
  coachedLyrics = payload.lyrics || '';
  lyrics.value = coachedLyrics;
  const seconds = Math.round(payload.lyrics_seconds || 60);
  lyricsNote.textContent = coachedLyrics
    ? 'Transcribed from the first ' + seconds + 's of the take. Automatic transcription of singing can mishear words: edit anything that is wrong, then update the coaching.'
    : 'No lyrics were detected in the first ' + seconds + 's. Type or paste them to get rhyme and flow coaching.';
  lyricsStatus.textContent = '';
  recoach.disabled = true;
}

lyrics.addEventListener('input', () => {
  recoach.disabled = !lastResults || lyrics.value === coachedLyrics;
  lyricsStatus.textContent = recoach.disabled ? '' : 'Edited: update the coaching to use your changes.';
});

recoach.addEventListener('click', async () => {
  recoach.disabled = true;
  lyricsStatus.textContent = 'Updating coaching with your lyrics…';
  try {
    const response = await fetch('/api/coach', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        results: lastResults,
        lyrics: lyrics.value,
        key: key.value,
        chords: chords.value,
        genre: genre.value,
        vocal_style: vocalStyle.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Coaching failed.');
    renderFeedback(payload.feedback);
    verdictCopy.textContent = payload.verdict;
    agentMode.textContent = payload.agent_mode;
    coachedLyrics = lyrics.value;
    lyricsStatus.textContent = payload.agent_warning || 'Coaching updated with your lyrics.';
  } catch (error) {
    recoach.disabled = false;
    lyricsStatus.textContent = 'Could not update coaching: ' + error.message;
  }
});

async function submit(endpoint, formData = null) {
  analyze.disabled = true;
  demo.disabled = true;
  analyze.textContent = 'Analyzing…';
  status.textContent = 'Listening to your take, writing down the lyrics, and preparing your coaching. This takes up to a minute…';
  try {
    const options = { method: 'POST' };
    if (formData) options.body = formData;
    const response = await fetch(endpoint, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Analysis failed.');
    render(payload);
    status.textContent = payload.agent_warning
      ? 'Pitch analysis complete. ' + payload.agent_warning
      : 'Analysis complete. Review the markers, agent verdict, and practice plan below.';
    results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    status.textContent = 'Could not analyze this take: ' + error.message;
  } finally {
    analyze.disabled = !audioFile.files[0];
    demo.disabled = false;
    analyze.innerHTML = 'Analyze this take <span>→</span>';
  }
}

function contextForm() {
  const form = new FormData();
  form.append('key', key.value);
  form.append('chords', chords.value);
  form.append('genre', genre.value);
  form.append('vocal_style', vocalStyle.value);
  return form;
}

analyze.addEventListener('click', () => {
  const file = audioFile.files[0];
  if (!file) return;
  const form = contextForm();
  form.append('audio', file);
  submit('/api/analyze', form);
});

demo.addEventListener('click', () => submit('/api/demo', contextForm()));
