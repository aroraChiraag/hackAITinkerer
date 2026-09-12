# Functional ShruTea local UI

This UI runs the repository's real `drift.py` on a WAV selected in the browser. It does not upload audio to a remote service.

## Run it

Install the repository dependencies first, then start the local server from the repository root:

```bash
python3 -m pip install -r requirements.txt
python3 ui/server.py
```

Open `http://127.0.0.1:8000`, select a rendered WAV, and click **Analyze this take**. The browser sends the WAV to the local server, which calls `drift.py` and renders its returned JSON.

The expected melody remains the hardcoded `REFERENCE_SEQUENCE` in `../drift.py`; edit that before a real session.
