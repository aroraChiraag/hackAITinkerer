const audioFile = document.querySelector('#audio-file');
const filename = document.querySelector('#file-name');
const analyze = document.querySelector('#analyze');
const status = document.querySelector('#status');
const results = document.querySelector('#results');
const count = document.querySelector('#drift-count');
const title = document.querySelector('#result-title');
const summary = document.querySelector('#summary');
const timeline = document.querySelector('#timeline');
const markerList = document.querySelector('#marker-list');
const rawJson = document.querySelector('#raw-json');
const key = document.querySelector('#key');
const chords = document.querySelector('#chords');
const genre = document.querySelector('#genre');
const vocalStyle = document.querySelector('#vocal-style');
const feedback = {
  headline: document.querySelector('#feedback-headline'), summary: document.querySelector('#feedback-summary'),
  rhymeScheme: document.querySelector('#rhyme-scheme'), rhyme: document.querySelector('#rhyme-feedback'),
  melody: document.querySelector('#melody-feedback'), vibrato: document.querySelector('#vibrato-feedback'),
  practice: document.querySelector('#practice-steps'), instruments: document.querySelector('#instrument-recommendations'),
  transcript: document.querySelector('#transcript'),
};

audioFile.addEventListener('change', () => {
  const file = audioFile.files[0];
  filename.textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB` : 'No file selected';
  analyze.disabled = !file;
  status.textContent = file ? 'Ready to run drift.py locally.' : 'Select a WAV to begin.';
});

function render(entries) {
  results.hidden = false;
  count.textContent = entries.length;
  rawJson.textContent = JSON.stringify(entries, null, 2);
  timeline.replaceChildren();
  markerList.replaceChildren();
  if (!entries.length) {
    title.textContent = 'Take is within the 20¢ threshold';
    summary.textContent = 'No drift markers were returned by drift.py for this rendered take.';
    markerList.innerHTML = '<article class="marker good"><b>✓</b><div><strong>In tune</strong><small>No reference windows exceeded 20 cents.</small></div></article>';
    return;
  }
  title.textContent = 'Pitch drift markers';
  const lastTime = Math.max(...entries.map(entry => Number(entry.time)), 0.1);
  summary.textContent = `${entries.length} reference window${entries.length === 1 ? '' : 's'} exceeded the 20¢ threshold. These are the same events the REAPER script marks on its timeline.`;
  entries.forEach(entry => {
    const point = document.createElement('i');
    point.className = 'warn'; point.style.left = `${8 + 84 * Number(entry.time) / lastTime}%`;
    point.title = `${entry.expected_note} → ${entry.actual_note}: ${entry.cents_off}¢`;
    timeline.append(point);
    const card = document.createElement('article'); card.className = 'marker';
    card.innerHTML = `<b>${Math.round(Number(entry.cents_off))}¢</b><div><strong>${entry.expected_note} → ${entry.actual_note}</strong><small>${Number(entry.time).toFixed(2)}s · REAPER marker: ${entry.actual_note}: ${Number(entry.cents_off).toFixed(1)} cents off</small></div>`;
    markerList.append(card);
  });
}

function renderFeedback(transcript, report) {
  feedback.headline.textContent = report.headline; feedback.summary.textContent = report.summary;
  feedback.rhymeScheme.textContent = report.rhyme_scheme; feedback.rhyme.textContent = report.rhyme_feedback;
  feedback.melody.textContent = report.melody_feedback; feedback.vibrato.textContent = report.vibrato_feedback;
  feedback.transcript.textContent = transcript;
  feedback.practice.replaceChildren(...report.practice_steps.map(step => { const item = document.createElement('li'); item.textContent = step; return item; }));
  feedback.instruments.replaceChildren(...report.instrument_recommendations.map(item => { const bullet = document.createElement('li'); bullet.textContent = item; return bullet; }));
}

analyze.addEventListener('click', async () => {
  const file = audioFile.files[0]; if (!file) return;
  analyze.disabled = true; analyze.textContent = 'Analyzing…'; status.textContent = 'Transcribing with OpenAI and measuring local pitch drift…';
  try {
    const form = new FormData(); form.append('audio', file); form.append('key', key.value); form.append('chords', chords.value); form.append('genre', genre.value); form.append('vocal_style', vocalStyle.value);
    const response = await fetch('/api/analyze', { method: 'POST', body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Analysis failed.');
    render(payload.results); renderFeedback(payload.transcript, payload.feedback); status.textContent = 'Analysis complete.'; results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) { status.textContent = `Could not analyze this take: ${error.message}`; }
  finally { analyze.disabled = false; analyze.innerHTML = 'Analyze this take <span>→</span>'; }
});
