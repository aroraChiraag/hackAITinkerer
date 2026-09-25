#!/usr/bin/env python3
"""Serve the ShruTea web companion and analyze rendered vocal takes.

Pitch detection and lyric extraction always run locally: pitch uses the same
capped drift.py command that feeds the REAPER script, and lyrics come from a
local Whisper model, so audio never leaves the machine. With an API key in
.env, the extracted lyrics, measured drift, and musical context are sent to
OpenAI or Claude for structured coaching. A failed or missing network
integration never hides the local results.
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import certifi

try:
    from dotenv import load_dotenv
except ImportError:  # The local-only analyzer still works before optional UI deps are installed.
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:  # Keep the local detector usable without an API SDK.
    OpenAI = None


UI_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = UI_DIRECTORY.parent
DRIFT_SCRIPT = REPOSITORY_ROOT / "drift.py"
DEMO_AUDIO = REPOSITORY_ROOT / "audio" / "Audio Only.wav"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_COACH_REQUEST_BYTES = 1024 * 1024
MAX_LYRICS_CHARACTERS = 5000
UI_ANALYSIS_SECONDS = 8
SUPPORTED_INPUT_SUFFIXES = {
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}
WAV_SUFFIX = ".wav"
CONTEXT_FIELDS = ("key", "chords", "genre", "vocal_style")

FEEDBACK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "rhyme_scheme": {"type": "string"},
        "rhyme_feedback": {"type": "string"},
        "melody_feedback": {"type": "string"},
        "vibrato_feedback": {"type": "string"},
        "practice_steps": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        },
        "instrument_recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 4,
        },
    },
    "required": [
        "headline",
        "summary",
        "rhyme_scheme",
        "rhyme_feedback",
        "melody_feedback",
        "vibrato_feedback",
        "practice_steps",
        "instrument_recommendations",
    ],
}

if load_dotenv:
    load_dotenv(REPOSITORY_ROOT / ".env")

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from commentary import template_commentary  # noqa: E402
from llm_coach import claude_text, coach  # noqa: E402

# Lyrics: a local Whisper model transcribes the first LYRICS_SECONDS of a take.
# "small" handles sung Hindi/Urdu/English well on CPU; "base" is faster.
LYRICS_SECONDS = float(os.getenv("SHRUTEA_LYRICS_SECONDS", "60"))
WHISPER_MODEL = os.getenv("SHRUTEA_WHISPER_MODEL", "small")
# Non-English lyrics are transliterated to Roman script (e.g. Hinglish) with
# Claude unless SHRUTEA_LYRICS_SCRIPT=original.
ROMANIZE_LYRICS = os.getenv("SHRUTEA_LYRICS_SCRIPT", "roman").lower() != "original"
_whisper_model = None
_whisper_lock = threading.Lock()


def load_whisper() -> Any:
    """Load the Whisper model once; callers must hold _whisper_lock."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper_model


def warm_up_whisper() -> None:
    """Download/load the model at startup so the first analysis is not slow."""
    try:
        with _whisper_lock:
            load_whisper()
        print(f"Lyrics model '{WHISPER_MODEL}' ready.")
    except Exception as error:  # Lyrics are optional; pitch analysis still works.
        print(f"Lyrics model unavailable, lyric extraction is off: {error}", file=sys.stderr)


def extract_lyrics(wav_path: Path) -> tuple[str, str]:
    """Transcribe sung lyrics locally, one line per phrase. Returns (lyrics, language code)."""
    import librosa

    samples, _ = librosa.load(wav_path, sr=16_000, mono=True, duration=LYRICS_SECONDS)
    with _whisper_lock:
        segments, info = load_whisper().transcribe(samples, vad_filter=True, beam_size=5)
        # segments is a lazy generator; consume it while holding the lock.
        lines = [segment.text.strip() for segment in segments]
    return "\n".join(line for line in lines if line), info.language


def romanize_lyrics(lyrics: str, language: str) -> str:
    """Transliterate non-Latin-script lyrics so singers who read Roman script can edit them."""
    system = """You transliterate song lyrics. Rewrite the lyrics in Roman (Latin) script the way
a native speaker would casually type them (for Hindi/Urdu, everyday Hinglish spelling). Transliterate,
never translate. Keep the transcribed words; only fix a spelling when the intended word is obvious.
Keep one lyric line per line. Return only the lyrics, with no title or commentary."""
    prompt = f"Automatically transcribed lyrics (detected language code: {language}):\n\n{lyrics}"
    return claude_text(system, prompt, max_tokens=4000, timeout=45.0)


def should_romanize(lyrics: str, language: str) -> bool:
    return bool(lyrics) and language != "en" and ROMANIZE_LYRICS and bool(os.environ.get("ANTHROPIC_API_KEY"))


def clock_time(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def describe_drift(entry: dict[str, Any]) -> str:
    """Describe a drift event in plain words, matching the web page's marker list."""
    note = entry["expected_note"]
    if entry["actual_note"] != note:
        note = f"{note} → {entry['actual_note']}"
    cents = abs(float(entry["cents_off"]))
    direction = entry.get("direction", "off")
    amount = f"a little {direction}" if cents < 30 else direction if cents < 45 else f"very {direction}"
    return f"{note} at {clock_time(float(entry['time']))}, {amount}"


def local_feedback(verdict: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Make every visible UI card useful when no LLM key is configured."""
    worst = max(results, key=lambda entry: float(entry["cents_off"]), default=None)
    if worst:
        note_detail = f"The note to fix first: {describe_drift(worst)}."
        melody_feedback = f"Loop the {worst['expected_note']} at {clock_time(float(worst['time']))}, then sing it without vibrato."
        practice = [
            "Play the expected note and match it with a held vowel for four beats.",
            "Record one slow pass, listening for the note before adding style or grit.",
            "Use the marker on your timeline to re-sing just that line.",
        ]
    else:
        note_detail = "Every note landed on pitch."
        melody_feedback = "Keep this placement; use the clean take as the comp reference."
        practice = [
            "Save this take as a pitch reference before recording another pass.",
            "Keep the same monitor mix and vowel placement for the next section.",
            "Check later sections the same way before you comp the final take.",
        ]
    return {
        "headline": "Local pitch-coach plan",
        "summary": f"{verdict} {note_detail}",
        "rhyme_scheme": "Needs an AI key",
        "rhyme_feedback": "Rhyme analysis of the extracted lyrics needs an API key in .env.",
        "melody_feedback": melody_feedback,
        "vibrato_feedback": "Pitch windows are measured before making any claim about vocal vibrato.",
        "practice_steps": practice,
        "instrument_recommendations": [
            "A sustained reference tone for note matching",
            "A dry vocal monitor mix while re-singing the marker",
            "A gentle pad or piano to make the target pitch easy to hear",
        ],
    }


def mock_feedback(results: list[dict[str, Any]], context: dict[str, str]) -> dict[str, Any]:
    """Return clearly-labelled demo coaching when no API key is configured."""
    style = " / ".join(part for part in (context["genre"], context["vocal_style"]) if part) or "your vocal style"
    worst = max(results, key=lambda entry: abs(float(entry["cents_off"])), default=None)
    landing = (
        f"The strongest marker is {describe_drift(worst)}."
        if worst
        else "Every note landed on pitch."
    )
    return {
        "headline": "Demo AI vocal-coach preview",
        "summary": f"{landing} For {style}, keep the phrase supported before adding grit.",
        "rhyme_scheme": "Sample · add an API key for real rhyme analysis",
        "rhyme_feedback": "With an API key, ShruTea analyzes the rhymes and flow of the extracted lyrics above.",
        "melody_feedback": "Approach the target note cleanly, hold it for two beats, then add the heavier tone on the release.",
        "vibrato_feedback": "Keep the first beat straight; introduce a light, even vibrato only after the note is centered.",
        "practice_steps": [
            "Sing the flagged landing on an open ‘ah’ with a piano reference.",
            "Repeat the phrase at 70% intensity, keeping the pitch stable before adding grit.",
            "Record one full-energy pass and compare it with the clean guide take.",
        ],
        "instrument_recommendations": [
            "Palm-muted electric-guitar riff for rhythmic weight",
            "Sub bass with a tight kick for the hip-hop foundation",
            "Wide distorted guitar or pad in the hook, leaving space for the vocal",
        ],
    }


def convert_to_wav(source_path: Path) -> Path:
    """Convert optional non-WAV input for local pYIN analysis."""
    if source_path.suffix.lower() == WAV_SUFFIX:
        return source_path
    if not shutil.which("ffmpeg"):
        raise ValueError("This file type needs FFmpeg installed. Export your take as a WAV instead.")
    converted_path = source_path.with_suffix(WAV_SUFFIX)
    completed = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-ac", "1", "-ar", "44100", str(converted_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode:
        raise ValueError("We couldn't read this file. Try exporting your take as a WAV.")
    return converted_path


COACH_SYSTEM = """You are ShruTea, a vocal coach embedded in a REAPER session. Coach only from the
supplied evidence: measured pitch-drift events (each sung note compared with its nearest semitone;
"direction" says flat or sharp), lyrics transcribed automatically from the take (they may contain
transcription mistakes unless the singer corrected them), and the singer's stated musical context.
You cannot hear the audio, so never claim to have heard tone or vibrato; frame vibrato and technique
advice as general guidance for this style. Technique suggestions are optional coaching, not medical
advice. Your reader is a singer, not an engineer: describe pitch in plain words ("a little flat",
"quite sharp") and times as m:ss, never in cents or technical terms. Write in English; when quoting
lyrics, write them in Roman (Latin) script. Be concise and specific."""


def coaching_prompt(results: list[dict[str, Any]], lyrics: str, context: dict[str, str]) -> str:
    return f"""Musical context: key={context["key"] or "not supplied"}; chords={context["chords"] or "not supplied"};
genre={context["genre"] or "not supplied"}; vocal style={context["vocal_style"] or "not supplied"}.
Measured pitch-drift events: {json.dumps(results, separators=(",", ":"))}
Lyrics:
{lyrics.strip() or "[no lyrics were extracted]"}

Fill every field. headline: a short title. summary: two sentences naming the most important note,
when it happens, and whether it was flat or sharp (or saying the take is clean). rhyme_scheme: the end-rhyme pattern of the
lyrics (for example AABB), or "No lyrics" if there are none. rhyme_feedback: one or two sentences on
the rhymes and flow, quoting specific words. melody_feedback and vibrato_feedback: one or two
sentences each. practice_steps: exactly 3. instrument_recommendations: 3 or 4 arrangement ideas that
suit the genre and vocal style."""


def openai_feedback(results: list[dict[str, Any]], lyrics: str, context: dict[str, str]) -> dict[str, Any]:
    """Request structured coaching from OpenAI."""
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK is not installed. Run pip install -r requirements.txt.")
    response = OpenAI(timeout=30.0, max_retries=0).responses.create(
        model=os.getenv("SHRUTEA_COACH_MODEL", "gpt-4o-mini"),
        instructions=COACH_SYSTEM,
        input=coaching_prompt(results, lyrics, context),
        max_output_tokens=800,
        store=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "shrutea_vocal_feedback",
                "strict": True,
                "schema": FEEDBACK_SCHEMA,
            }
        },
    )
    feedback = json.loads(response.output_text)
    if not isinstance(feedback, dict):
        raise ValueError("OpenAI returned an unexpected coaching format.")
    return feedback


def claude_feedback(results: list[dict[str, Any]], lyrics: str, context: dict[str, str]) -> dict[str, Any]:
    """Request structured coaching from Claude."""
    # Claude's structured outputs take a plain object schema; list lengths are
    # requested in the prompt and enforced below.
    schema = json.loads(json.dumps(FEEDBACK_SCHEMA))
    for field in ("practice_steps", "instrument_recommendations"):
        schema["properties"][field].pop("minItems")
        schema["properties"][field].pop("maxItems")
    text = claude_text(COACH_SYSTEM, coaching_prompt(results, lyrics, context), max_tokens=4000, schema=schema, timeout=45.0)
    feedback = json.loads(text)
    if len(feedback["practice_steps"]) < 3 or len(feedback["instrument_recommendations"]) < 3:
        raise ValueError("Claude returned too few practice steps or arrangement ideas.")
    feedback["practice_steps"] = feedback["practice_steps"][:3]
    feedback["instrument_recommendations"] = feedback["instrument_recommendations"][:4]
    return feedback


def openrouter_verdict(results: list[dict[str, Any]], context: dict[str, str]) -> tuple[str, str]:
    """Ask a real OpenRouter model for a concise REAPER-aware coaching verdict."""
    model = os.getenv("SHRUTEA_OPENROUTER_MODEL", "openrouter/free")
    session = {
        "analysis_mode": "auto: each sung note compared with its nearest semitone",
        "drift_events": results,
        "musical_context": {field: context[field] or "not supplied" for field in CONTEXT_FIELDS},
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "max_tokens": 160,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are ShruTea, an embedded vocal coach in a REAPER session. Give one concise, specific coaching verdict grounded only in supplied pitch evidence. Name the actual note and cents value when drift exists. Do not claim to hear lyrics, vibrato, or melody beyond the evidence. No generic encouragement.",
                    },
                    {"role": "user", "content": json.dumps(session, separators=(",", ":"))},
                ],
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "ShruTea",
        },
        method="POST",
    )
    certificate_context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=15, context=certificate_context) as response:
        payload = json.load(response)
    content = payload["choices"][0]["message"].get("content")
    if isinstance(content, list):
        verdict = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        ).strip()
    else:
        verdict = str(content or "").strip()
    if not verdict or verdict.lower() == "none":
        raise ValueError("OpenRouter returned no coaching text.")
    return verdict, str(payload.get("model") or model)


def coach_take(results: list[dict[str, Any]], lyrics: str, context: dict[str, str]) -> dict[str, Any]:
    """Return the coaching fields of a response: feedback, verdict, agent_mode, and any warning."""
    local_verdict = template_commentary(results)
    local = {
        "feedback": local_feedback(local_verdict, results),
        "verdict": local_verdict,
        "agent_mode": "Local ShruTea coaching",
    }
    structured = (
        ("OpenAI", openai_feedback) if os.environ.get("OPENAI_API_KEY")
        else ("Claude", claude_feedback) if os.environ.get("ANTHROPIC_API_KEY")
        else None
    )
    if structured:
        name, provider = structured
        try:
            feedback = provider(results, lyrics, context)
            return {"feedback": feedback, "verdict": feedback["summary"], "agent_mode": f"{name} structured coaching"}
        except Exception as error:  # Any API, network, or format failure falls back to local coaching.
            print(f"{name} coaching failed: {error!r}", file=sys.stderr)
            return {**local, "agent_warning": f"{name} coaching failed, showing local coaching instead. ({error})"}
    if os.environ.get("OPENROUTER_API_KEY"):
        try:
            verdict, model = openrouter_verdict(results, context)
        except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
            return {**local, "agent_warning": f"OpenRouter coaching was unavailable; local drift coaching is still complete. ({error})"}
        feedback = local_feedback(verdict, results)
        feedback["headline"] = "OpenRouter live vocal coach"
        feedback["summary"] = verdict
        return {"feedback": feedback, "verdict": verdict, "agent_mode": f"OpenRouter live coach ({model})"}
    feedback = mock_feedback(results, context)
    return {
        "feedback": feedback,
        "verdict": coach(results),
        "agent_mode": "Demo coach — mock feedback",
        "agent_warning": "Demo mode: no API key found in .env, so the coaching plan is a sample.",
    }


def analyze_take(source_path: Path, context: dict[str, str]) -> dict[str, Any]:
    """Measure pitch drift and extract lyrics locally, then add coaching."""
    analysis_path = convert_to_wav(source_path)
    try:
        # Pitch analysis runs in its own process while lyrics are extracted here.
        drift = subprocess.Popen(
            [sys.executable, str(DRIFT_SCRIPT), str(analysis_path), "--max-seconds", str(UI_ANALYSIS_SECONDS)],
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        warnings = []
        lyrics, language = "", ""
        try:
            lyrics, language = extract_lyrics(analysis_path)
        except Exception as error:  # Lyrics are optional; pitch results still render.
            print(f"Lyric extraction failed: {error!r}", file=sys.stderr)
            warnings.append(f"Lyrics could not be extracted ({error}).")
        try:
            stdout, stderr = drift.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            drift.kill()
            raise
        if drift.returncode:
            raise ValueError(stderr.strip() or "drift.py failed.")
        results = json.loads(stdout)
        if not isinstance(results, list):
            raise ValueError("drift.py did not return a JSON array.")

        with ThreadPoolExecutor(max_workers=1) as pool:
            romanized = pool.submit(romanize_lyrics, lyrics, language) if should_romanize(lyrics, language) else None
            coaching = coach_take(results, lyrics, context)
            if romanized:
                try:
                    lyrics = romanized.result()
                except Exception as error:  # Keep the original-script lyrics.
                    print(f"Lyric transliteration failed: {error!r}", file=sys.stderr)
                    warnings.append("Lyrics are shown in their original script (transliteration failed).")
        if coaching.get("agent_warning"):
            warnings.append(coaching.pop("agent_warning"))
        payload: dict[str, Any] = {
            "results": results,
            "analysis_window_seconds": UI_ANALYSIS_SECONDS,
            "lyrics": lyrics,
            "lyrics_language": language,
            "lyrics_seconds": LYRICS_SECONDS,
            **coaching,
        }
        if warnings:
            payload["agent_warning"] = " ".join(warnings)
        return payload
    finally:
        if analysis_path != source_path:
            analysis_path.unlink(missing_ok=True)


def context_from(fields: dict[str, Any]) -> dict[str, str]:
    return {field: str(fields.get(field) or "").strip()[:200] for field in CONTEXT_FIELDS}


class ShruTeaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(UI_DIRECTORY), **kwargs)

    def send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def parse_multipart(self, content_length: int) -> tuple[dict[str, str], str, bytes]:
        """Parse a multipart browser upload without the removed cgi module."""
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/"):
            raise ValueError("Expected a multipart audio upload.")

        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
        message = BytesParser(policy=default).parsebytes(
            header.encode("utf-8") + self.rfile.read(content_length)
        )
        fields: dict[str, str] = {}
        filename = ""
        audio = b""
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            if name == "audio":
                filename = part.get_filename() or ""
                audio = part.get_payload(decode=True) or b""
            else:
                fields[name] = part.get_content().strip()
        return fields, filename, audio

    def handle_coach(self) -> None:
        """Re-run coaching with lyrics the singer corrected, without re-analyzing audio."""
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_COACH_REQUEST_BYTES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid coaching request."})
            return
        try:
            body = json.loads(self.rfile.read(content_length))
            results = body["results"]
            lyrics = str(body.get("lyrics") or "")
            if not isinstance(results, list) or len(lyrics) > MAX_LYRICS_CHARACTERS:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"Send drift results and at most {MAX_LYRICS_CHARACTERS} characters of lyrics."})
            return
        self.send_json(HTTPStatus.OK, coach_take(results, lyrics, context_from(body)))

    def do_POST(self) -> None:
        if self.path == "/api/coach":
            self.handle_coach()
            return

        if self.path == "/api/demo":
            if not DEMO_AUDIO.is_file():
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "The bundled demo take was not found."})
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            try:
                fields = self.parse_multipart(content_length)[0] if content_length else {}
            except ValueError:
                fields = {}
            try:
                self.send_json(HTTPStatus.OK, analyze_take(DEMO_AUDIO, context_from(fields)))
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": f"Demo analysis failed: {error}"})
            return

        if self.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose an audio or video file smaller than 100 MB."})
            return
        if not self.headers.get_content_type().startswith("multipart/"):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Expected a multipart audio upload."})
            return

        try:
            fields, filename, audio = self.parse_multipart(content_length)
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        suffix = Path(filename).suffix.lower()
        if not audio or suffix not in SUPPORTED_INPUT_SUFFIXES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose WAV, MP3, M4A, MP4, MOV, or another supported audio format."})
            return

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(audio)
        try:
            self.send_json(HTTPStatus.OK, analyze_take(temporary_path, context_from(fields)))
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": f"Analysis failed: {error}"})
        finally:
            temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    threading.Thread(target=warm_up_whisper, daemon=True).start()
    print("ShruTea UI running at http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), ShruTeaHandler).serve_forever()
