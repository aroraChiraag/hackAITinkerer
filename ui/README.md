# ShruTea UI prototype

Open `index.html` in a browser to try the interface. It is a front-end prototype: choosing a file and clicking **Steep my feedback** displays illustrative feedback; it does not upload, transcribe, or analyse audio yet.

## Production integration path

1. Accept only user-owned/licensed audio or video; extract MP4/MOV audio server-side with FFmpeg.
2. Transcribe vocals with a speech-to-text model, preserve timestamps, then send lyrics plus the chosen musical context to an LLM for concise, singer-friendly coaching. Treat AI feedback as suggestions, never diagnostic claims.
3. Replace the hard-coded reference in `../drift.py` with time-aligned target notes generated from the selected chord progression or a MIDI guide. Return timestamps, signed cents deviation, confidence, and voiced/unvoiced regions.
4. Surface pitch, melody, vibrato, lyric/rhyme, and arrangement as separate evidence-backed cards. Let the singer correct a transcript or chord choice before regenerating feedback.

NCS and YouTube links are not automatically safe-to-download sources. The app should accept a source URL only for attribution and require the user to confirm their usage rights before processing any extracted media.

