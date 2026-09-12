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
const rawJson = document.querySelector('#raw-json');
const verdictTitle = document.querySelector('#verdict-title');
const verdictCopy = document.querySelector('#verdict-copy');
const agentMode = document.querySelector('#agent-mode');
const referenceNotes = document.querySelector('#reference-notes');
const reaperPlan = document.querySelector('#reaper-plan');
const key = document.querySelector('#key');
const chords = document.querySelector('#chords');
const genre = document.querySelector('#genre');
const vocalStyle = document.querySelector('#vocal-style');
const feedback = {
  headline: document.querySelector('#feedback-headline'),
  summary: document.querySelector('#feedback-summary'),
  rhymeScheme: document.querySelector('#rhyme-scheme'),
  rhyme: document.querySelector('#rhyme-feedback'),
  melody: document.querySelector('#melody-feedback'),
  vibrato: document.querySelector('#vibrato-feedback'),
  practice: document.querySelector('#practice-steps'),
  instruments: document.querySelector('#instrument-recommendations'),
  transcript: document.querySelector('#transcript'),
};

audioFile.addEventListener('change', () => {
  const file = audioFile.files[0];
  filename.textContent = file ? file.name + ' · ' + (file.size / 1024 / 1024).toFixed(1) + ' MB' : 'No file selected';
  analyze.disabled = !file;
  status.textContent = file ? 'Ready: local drift analysis will use the first 8 seconds.' : 'Select a WAV or try the included demo take.';
});

function listInto(element, values) {
  element.replaceChildren(...values.map(value => {
    const item = document.createElement('li');
    item.textContent = value;
    return item;
  }));
}

function renderFeedback(transcript, report) {
  feedback.headline.textContent = report.headline;
  feedback.summary.textContent = report.summary;
  feedback.rhymeScheme.textContent = report.rhyme_scheme;
  feedback.rhyme.textContent = report.rhyme_feedback;
  feedback.melody.textContent = report.melody_feedback;
  feedback.vibrato.textContent = report.vibrato_feedback;
  feedback.transcript.textContent = transcript;
  listInto(feedback.practice, report.practice_steps);
  listInto(feedback.instruments, report.instrument_recommendations);
}

function makeMarker(entry) {
  const card = document.createElement('article');
  card.className = 'marker';
  const cents = document.createElement('b');
  cents.textContent = Math.round(Number(entry.cents_off)) + '¢';
  const body = document.createElement('div');
  const heading = document.createElement('strong');
  heading.textContent = entry.expected_note + ' → ' + entry.actual_note;
  const details = document.createElement('small');
  details.textContent = Number(entry.time).toFixed(2) + 's · REAPER marker: ' + entry.actual_note + ': ' + Number(entry.cents_off).toFixed(1) + ' cents off';
  body.append(heading, details);
  card.append(cents, body);
  return card;
}

function render(payload) {
  const entries = payload.results;
  results.hidden = false;
  count.textContent = entries.length;
  rawJson.textContent = JSON.stringify(entries, null, 2);
  verdictTitle.textContent = 'ShruTea is in the session';
  verdictCopy.textContent = payload.verdict;
  agentMode.textContent = payload.agent_mode;
  reaperPlan.textContent = entries.length ? entries.length + ' marker' + (entries.length === 1 ? '' : 's') + ' ready for REAPER' : 'No drift markers needed';

  referenceNotes.replaceChildren();
  (payload.reference_sequence || []).forEach(([time, note]) => {
    const chip = document.createElement('span');
    chip.textContent = note + ' @ ' + Number(time).toFixed(2) + 's';
    referenceNotes.append(chip);
  });

  timeline.replaceChildren();
  markerList.replaceChildren();
  if (!entries.length) {
    title.textContent = 'Take is within the 20¢ threshold';
    summary.textContent = 'No drift markers were returned by the same local detector that feeds the REAPER ReaScript.';
    const clean = document.createElement('article');
    clean.className = 'marker good';
    const check = document.createElement('b');
    check.textContent = '✓';
    const copy = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = 'In tune';
    const note = document.createElement('small');
    note.textContent = 'No reference windows exceeded 20 cents.';
    copy.append(name, note);
    clean.append(check, copy);
    markerList.append(clean);
  } else {
    title.textContent = 'Pitch drift markers';
    const lastTime = Math.max(payload.analysis_window_seconds || 0.1, ...entries.map(entry => Number(entry.time)), 0.1);
    summary.textContent = entries.length + ' reference window' + (entries.length === 1 ? '' : 's') + ' exceeded 20 cents. The ReaScript places these same events on the REAPER timeline.';
    entries.forEach(entry => {
      const point = document.createElement('i');
      point.className = 'warn';
      point.style.left = (8 + 84 * Number(entry.time) / lastTime) + '%';
      point.title = entry.expected_note + ' → ' + entry.actual_note + ': ' + entry.cents_off + '¢';
      timeline.append(point);
      markerList.append(makeMarker(entry));
    });
  }
  renderFeedback(payload.transcript, payload.feedback);
}

async function submit(endpoint, formData = null) {
  analyze.disabled = true;
  demo.disabled = true;
  analyze.textContent = 'Analyzing…';
  status.textContent = 'Measuring local pitch drift and assembling the coaching workspace…';
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

analyze.addEventListener('click', () => {
  const file = audioFile.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('audio', file);
  form.append('key', key.value);
  form.append('chords', chords.value);
  form.append('genre', genre.value);
  form.append('vocal_style', vocalStyle.value);
  submit('/api/analyze', form);
});

demo.addEventListener('click', () => submit('/api/demo'));
