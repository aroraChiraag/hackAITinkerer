# Functional ShruTea local UI

This UI combines local pitch-drift detection with OpenAI transcription and singer-friendly feedback. The selected file is temporarily sent to OpenAI for those API calls; the local server deletes its temporary upload after processing.

## Run it

Install the repository dependencies first, then start the local server from the repository root:

```bash
python3 -m pip install -r requirements.txt
# PowerShell:
$env:OPENAI_API_KEY = "your_api_key_here"
# Command Prompt: set OPENAI_API_KEY=your_api_key_here
python3 ui/server.py
```

Open `http://127.0.0.1:8000`, select a supported audio/video file, provide its key, chords, genre, and vocal style, then click **Analyze this take**. The browser sends the file to the local server. It converts video with FFmpeg when necessary, uses OpenAI transcription, and asks the Responses API for structured coaching feedback. `drift.py` separately provides the measurable pitch events.

The expected melody remains the hardcoded `REFERENCE_SEQUENCE` in `../drift.py`; edit that before a real session. Install FFmpeg and place it on `PATH` to accept anything other than WAV. Larger files are compressed locally for transcription; temporary source and derived files are deleted after the request.
